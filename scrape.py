"""Download every PDF from a margdarshanprep (Appx/ClassX) course via its REST API.

Phone-OTP login, then walks the course's folder tree (folder_contentsv3) and saves
each PDF under downloads/<Folder>/<Subfolder>/<title>.pdf
"""

import argparse
import base64
import json
import re
import time
from pathlib import Path

import requests
from Crypto.Cipher import AES

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "downloads"
RAW_DIR = ROOT / "raw"
AUTH_FILE = ROOT / ".auth.json"

DOMAIN = "course.margdarshanprep.com"
CONFIG_BOOTSTRAP = "https://tempapi.classx.co.in/get/getWebAppConfig"
CONST_HEADERS = {
    "Client-Service": "Appx",
    "Auth-Key": "appxapi",
    "source": "website",
    "Origin": f"https://{DOMAIN}",
    "Referer": f"https://{DOMAIN}/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}
PAGE = 20
ROOT_PARENT = "-1"

# The CDN only serves the signed PDF URLs to the pdf.js viewer's origin — without
# this Referer every link 404s ("Google-Edge-Cache: not found").
PDF_HEADERS = {
    "User-Agent": CONST_HEADERS["User-Agent"],
    "Referer": "https://pdfweb.classx.co.in/",
    "Origin": "https://pdfweb.classx.co.in",
}

# AES-128-CBC key + IV the platform hardcodes for `file_link` / `pdf_link`
# (constants VALUE and SALT in its _app bundle). Override with --key if rotated.
LINK_KEYS: list[str] = ["638udh3829162018"]
LINK_IV = b"fedcba9876543210"


def log(*a):
    print("[*]", *a, flush=True)


def safe(name: str) -> str:
    name = re.sub(r"\s+", " ", str(name))
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name).strip(" ._")
    return name[:120] or "untitled"


# ------------------------------------------------------------------ link crypto


def _unpad(b: bytes) -> bytes:
    if b and 1 <= b[-1] <= 16:
        return b[: -b[-1]]
    return b


def decrypt_link(value: str, keys: list[str]) -> str | None:
    """Appx encrypts links as base64(ciphertext):base64(iv-ascii), AES-CBC."""
    if not value:
        return None
    if value.startswith("http"):
        return value

    # the site splits on ":" and keeps only the ciphertext, hardcoding the IV to SALT
    ct_b64 = value.split(":")[0]
    try:
        ct = base64.b64decode(ct_b64)
    except Exception:
        return None
    iv = LINK_IV
    if len(iv) != 16 or len(ct) % 16:
        return None

    for key in keys:
        kb = key.encode()
        if len(kb) not in (16, 24, 32):
            continue
        try:
            out = _unpad(AES.new(kb, AES.MODE_CBC, iv).decrypt(ct))
            text = out.decode("utf-8", "strict").strip()
        except Exception:
            continue
        if text.startswith("http"):
            return text
    return None


class Appx:
    def __init__(self, dump_raw=False):
        self.s = requests.Session()
        self.s.headers.update(CONST_HEADERS)
        self.base = self._resolve_base()
        self.dump_raw = dump_raw
        log(f"api base {self.base}")

    def _resolve_base(self) -> str:
        r = self.s.get(CONFIG_BOOTSTRAP, params={"domain": DOMAIN}, timeout=30)
        r.raise_for_status()
        cfg_url = r.json()["web_config_url"]
        cfg = self.s.get(cfg_url, timeout=30).json()
        return cfg["web_apiurl"].rstrip("/")

    def get(self, path: str, **params):
        url = f"{self.base}/{path.lstrip('/')}"
        for attempt in range(3):
            try:
                r = self.s.get(url, params=params, timeout=60)
            except requests.RequestException as e:
                log(f"  network error ({e}); retrying")
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 401:
                raise SystemExit(
                    "API returned 401 Invalid Token — session expired. "
                    f"Delete {AUTH_FILE.name} and run again to re-login."
                )
            if r.status_code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            try:
                body = r.json()
            except ValueError as e:
                raise SystemExit(f"Non-JSON reply from {path}: {r.text[:300]}") from e
            if self.dump_raw:
                RAW_DIR.mkdir(exist_ok=True)
                stamp = safe(path + "_" + "_".join(f"{k}{v}" for k, v in params.items()))
                (RAW_DIR / f"{stamp}.json").write_text(json.dumps(body, indent=2))
            return body
        raise SystemExit(f"{path} kept failing")

    # ------------------------------------------------------------------- login

    def login(self, phone: str):
        if AUTH_FILE.exists():
            saved = json.loads(AUTH_FILE.read_text())
            self._apply_auth(saved)
            log(f"reusing saved session for {saved.get('name') or saved.get('userid')}")
            return

        r = self.get("get/sendotp", phone=phone)
        log(f"OTP requested for {phone}: {r.get('message') or r.get('msg') or r}")

        otp = input("\n>>> Enter the OTP you received, then press Enter: ").strip()
        body = self.get("get/otpverify", useremail=phone, otp=otp)

        # the token lives under "user"; other builds use "data" or the top level
        data = {}
        for candidate in (body.get("user"), body.get("data"), body):
            if isinstance(candidate, list):
                candidate = candidate[0] if candidate else None
            if isinstance(candidate, dict) and candidate.get("token"):
                data = candidate
                break

        token = data.get("token") or data.get("auth_token")
        userid = data.get("userid") or data.get("user_id") or data.get("id")
        if not token or not userid:
            raise SystemExit(f"OTP verify did not return a token: {json.dumps(body)[:500]}")

        auth = {
            "token": str(token),
            "userid": str(userid),
            "user_app_category": str(data.get("app_category") or ""),
            "name": data.get("name") or data.get("username") or "",
        }
        AUTH_FILE.write_text(json.dumps(auth, indent=2))
        self._apply_auth(auth)
        log(f"logged in as {auth['name'] or auth['userid']} (session saved to .auth.json)")

    def _apply_auth(self, auth: dict):
        self.userid = auth["userid"]
        self.s.headers.update(
            {
                "Authorization": auth["token"],
                "User-ID": auth["userid"],
                "user_app_category": auth.get("user_app_category", ""),
            }
        )


# ------------------------------------------------------------------- downloading

LINK_FIELDS = ("pdf_link", "file_link", "download_link", "study_material_link")


def title_of(item: dict, fallback: str) -> str:
    for key in ("Title", "title", "name", "file_name"):
        if item.get(key):
            return str(item[key])
    return fallback


class Downloader:
    def __init__(self, api: Appx, course_id: str, keys: list[str], only: str | None = None):
        self.api = api
        self.course_id = course_id
        self.keys = keys
        self.only = only  # limit to this top-level folder
        self.manifest: list[dict] = []
        self.seen: set[str] = set()
        self.undecryptable = 0
        self.cdn = requests.Session()  # plain session: the API's auth headers break the CDN
        self.cdn.headers.update(PDF_HEADERS)

    def folder(self, parent_id: str) -> list[dict]:
        items, start = [], 0
        while True:
            body = self.api.get(
                "get/folder_contentsv3",
                course_id=self.course_id,
                parent_id=parent_id,
                start=start,
            )
            batch = body.get("data") or []
            if isinstance(batch, dict):
                batch = [batch]
            items.extend(batch)
            if len(batch) < PAGE:
                break
            start += len(batch)
            if start > 5000:
                log("  !! safety cap hit while paging a folder")
                break
        return items

    def resolve_url(self, item: dict) -> str | None:
        for field in LINK_FIELDS:
            url = decrypt_link(item.get(field) or "", self.keys)
            if url:
                return url
        return None

    def save(self, url: str, path: Path, crumbs: list[str], item: dict):
        if url in self.seen:
            return
        self.seen.add(url)
        if path.exists():
            self.manifest.append({"path": crumbs, "file": str(path), "url": url})
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        try:
            with self.cdn.get(url, timeout=300, stream=True) as r:
                if r.status_code != 200:
                    log(f"    !! HTTP {r.status_code} for {url[:100]}")
                    return
                with tmp.open("wb") as fh:
                    for chunk in r.iter_content(65536):
                        fh.write(chunk)
            with tmp.open("rb") as fh:
                if fh.read(4) != b"%PDF":
                    log(f"    !! not a PDF: {url[:100]}")
                    tmp.unlink(missing_ok=True)
                    return
            tmp.rename(path)
        except requests.RequestException as e:
            log(f"    !! download failed: {e}")
            tmp.unlink(missing_ok=True)
            return
        log(f"    saved {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")
        self.manifest.append(
            {"path": crumbs, "file": str(path), "url": url, "id": item.get("id")}
        )

    def walk(self, parent_id: str, crumbs: list[str], depth: int = 0):
        if depth > 6:
            log(f"  !! max depth at {'/'.join(crumbs)}")
            return
        for item in self.folder(parent_id):
            kind = (item.get("material_type") or "").upper()
            title = title_of(item, f"item-{item.get('id')}")

            if depth == 0 and self.only and self.only.lower() not in title.lower():
                continue
            if kind == "FOLDER":
                log("  " * depth + f"[{title}]")
                self.walk(item["id"], crumbs + [title], depth + 1)
                continue
            if kind != "PDF":
                continue

            url = self.resolve_url(item)
            if not url:
                self.undecryptable += 1
                log("  " * depth + f"  ?? could not resolve link for {title!r}")
                continue
            self.save(
                url,
                OUT_DIR.joinpath(*map(safe, crumbs), safe(title) + ".pdf"),
                crumbs + [title],
                item,
            )

    def run(self):
        roots = self.folder(ROOT_PARENT)
        log(f"{len(roots)} root entries")
        for entry in roots:
            title = title_of(entry, "Home")
            if (entry.get("material_type") or "").upper() == "FOLDER":
                log(f"[{title}]")
                self.walk(entry["id"], [] if title.lower() == "home" else [title])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone", default="6206114473")
    ap.add_argument("--course-id", default="152")
    ap.add_argument("--key", action="append", default=[], help="extra AES link key to try")
    ap.add_argument("--raw", action="store_true", help="dump API replies to raw/")
    ap.add_argument(
        "--only",
        default="Computer Science",
        help="limit to this top-level folder ('' for the whole course)",
    )
    args = ap.parse_args()

    keys = args.key + LINK_KEYS
    if not keys:
        raise SystemExit(
            "No AES link key configured. Pass one with --key '<16-char-key>' "
            "or add it to LINK_KEYS in this file."
        )

    OUT_DIR.mkdir(exist_ok=True)
    api = Appx(dump_raw=args.raw)
    api.login(args.phone)

    dl = Downloader(api, args.course_id, keys, only=args.only or None)
    dl.run()

    (ROOT / "downloads-manifest.json").write_text(json.dumps(dl.manifest, indent=2))
    log(f"done — {len(dl.manifest)} PDFs; {dl.undecryptable} links unresolved")


if __name__ == "__main__":
    main()
