"""Download the Computer Science PDFs by driving the real web app in a browser.

The site resolves PDF URLs client-side (the API's own CDN links 404), so we let the
app do the resolving and capture the bytes it fetches.

    python browser_download.py                 # Computer Science, all subfolders
    python browser_download.py --sub "Notes & Material"
    python browser_download.py --headless      # once you trust it

Login is interactive the first time only; the session persists in .browser-profile/.
"""

import argparse
import re
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
PROFILE = ROOT / ".browser-profile"
OUT_DIR = ROOT / "downloads"
URL = "https://course.margdarshanprep.com/new-courses/152/content?activeTab=Content"
ROW = "text=/Created on:/i"  # PDF rows carry a created-on line; folders show a file count


def safe(name: str) -> str:
    name = re.sub(r"\s+", " ", str(name))
    return re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name).strip(" ._")[:120] or "untitled"


def log(*a):
    print("[*]", *a, flush=True)


class Catcher:
    """Saves the bytes of whichever PDF the browser is currently fetching."""

    def __init__(self, context):
        self.dest: Path | None = None
        self.saved = 0
        context.on("response", self._on)

    def _on(self, resp):
        if self.dest is None:
            return
        try:
            ctype = (resp.headers or {}).get("content-type", "").lower()
        except Exception:
            return
        if "pdf" not in ctype and not resp.url.lower().split("?")[0].endswith(".pdf"):
            return
        try:
            body = resp.body()
        except Exception:
            return
        if not body.startswith(b"%PDF"):
            return
        dest, self.dest = self.dest, None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        self.saved += 1
        log(f"    saved {dest.relative_to(ROOT)} ({len(body) // 1024} KB)")


def login_if_needed(page, phone: str):
    box = page.locator("input[placeholder*='phone' i], input[type=tel]").first
    if not (box.count() and box.is_visible()):
        return
    log("login required")
    box.fill(phone)
    page.locator("button:has-text('Next')").first.click()
    page.wait_for_timeout(4000)

    otp = input("\n>>> Enter the OTP you received, then press Enter: ").strip()
    boxes = page.locator("input[maxlength='1']")
    if boxes.count() >= len(otp):
        for i, ch in enumerate(otp):
            boxes.nth(i).fill(ch)
    else:
        page.locator("input[type=tel], input[type=text], input[type=number]").last.fill(otp)
    for label in ("Verify", "Submit", "Next", "Login"):
        b = page.locator(f"button:has-text('{label}')").first
        if b.count() and b.is_visible():
            b.click()
            break
    page.wait_for_timeout(9000)
    log("logged in — session saved to .browser-profile/")


def drill(page, names: list[str]) -> bool:
    """From the course root, click down through the given folder names."""
    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    for name in names:
        loc = page.get_by_text(name, exact=True).first
        if not loc.count():
            log(f"  !! folder not found: {name}")
            return False
        try:
            loc.click(timeout=12000)
        except PWTimeout:
            log(f"  !! could not click folder: {name}")
            return False
        page.wait_for_timeout(5000)
    return True


def row_titles(page) -> list[str]:
    out = []
    rows = page.locator(ROW)
    for i in range(rows.count()):
        try:
            card = rows.nth(i).locator("xpath=ancestor::div[3]")
            out.append(card.inner_text(timeout=3000).splitlines()[0].strip())
        except Exception:
            out.append("")
    return out


def subfolder_names(page) -> list[str]:
    """Folder cards = headings whose card has no 'Created on:' line."""
    names = []
    heads = page.locator("h1,h2,h3,h4,h5,h6,b,strong")
    for i in range(heads.count()):
        try:
            t = heads.nth(i).inner_text(timeout=1500).strip()
        except Exception:
            continue
        if t and t not in names and len(t) < 60:
            names.append(t)
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone", default="6206114473")
    ap.add_argument("--top", default="Computer Science")
    ap.add_argument("--sub", action="append", default=[], help="limit to these subfolders")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument(
        "--wait", type=int, default=14, help="seconds to wait for a PDF to load"
    )
    ap.add_argument("--only", action="append", default=[], help="only these PDF titles")
    args = ap.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE),
            headless=args.headless,
            accept_downloads=True,
            viewport={"width": 1440, "height": 1000},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        catcher = Catcher(ctx)

        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_timeout(7000)
        login_if_needed(page, args.phone)

        # which subfolders of the top folder to visit
        subs = args.sub
        if not subs:
            if not drill(page, [args.top]):
                raise SystemExit(f"could not open {args.top!r}")
            subs = [n for n in subfolder_names(page) if n.lower() != args.top.lower()]
            log(f"{args.top}: subfolders {subs}")

        for sub in subs:
            if not drill(page, [args.top, sub]):
                continue
            titles = row_titles(page)
            log(f"[{args.top} / {sub}] {len(titles)} PDFs")

            for idx, title in enumerate(titles):
                if not title or (args.only and title not in args.only):
                    continue
                dest = OUT_DIR / safe(args.top) / safe(sub) / (safe(title) + ".pdf")
                if dest.exists():
                    log(f"  skip (have) {title}")
                    continue
                # re-drill each time: opening a PDF replaces the listing
                if idx and not drill(page, [args.top, sub]):
                    break
                log(f"  open {title}")
                catcher.dest = dest
                try:
                    page.locator(ROW).nth(idx).locator("xpath=ancestor::div[3]").click(
                        timeout=12000
                    )
                except PWTimeout:
                    log("    !! click failed")
                    catcher.dest = None
                    continue
                for _ in range(args.wait):
                    page.wait_for_timeout(1000)
                    if catcher.dest is None:  # captured
                        break
                if catcher.dest is not None:
                    log("    ?? no PDF response captured")
                    catcher.dest = None

        log(f"done — {catcher.saved} PDFs under {OUT_DIR}")
        ctx.close()


if __name__ == "__main__":
    main()
