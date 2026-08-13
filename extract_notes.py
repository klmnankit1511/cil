"""Extract the readable study material (theory, not questions) from the course PDFs.

The books alternate: chapter theory, then "Exercises"/"Previous Years' Questions",
then "Answer Keys". The question parts are already handled by extract_mcqs.py, so
this keeps only the theory and turns it into structured blocks:

    {"t": "h1"|"h2"|"p"|"li"|"code", "x": "text"}

Font size decides headings: each book's body size is measured, and spans clearly
larger (or short bold lines) become headings.
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import pymupdf

ROOT = Path(__file__).parent
IN_DIR = ROOT / "downloads"
OUT_DIR = ROOT / "notes"

# where the question material starts — theory stops here until the next chapter
STOP = re.compile(
    r"^\s*(Exercises|Practice\s+Problems\s*\d*|Previous\s+Years[’']?\s+Questions|"
    r"Answer\s*Keys?|Hints?\s*/?\s*Explanations?)\s*$",
    re.I,
)
CHAPTER = re.compile(r"^\s*(?:Chapter|Unit)\s+(\d+)\s*$", re.I)
RUNNING_HEAD = re.compile(
    r"(?:Chapter|Unit)\s+\d+\s*[•·■]|^\s*[\d.]+\s*\|\s*|^\s*YCT\s*$|\|\s*[\d.]+\s*$", re.I
)
BULLET = re.compile(r"^\s*[•▪◦‣·☞☛➤▶]+\s*(.+)$")  # '••' and '☞' both occur
NUMBERED = re.compile(r"^\s*(\d{1,2})[.)]\s+(\S.*)$")
NOISE = re.compile(r"^\s*(?:www\.|https?://|©|Page\s*\d+|\d{1,4})\s*$", re.I)
# a line that is only maths/symbol debris once the equation layer is flattened
JUNK = re.compile(r"^[\s\d\W_]{0,40}$")

MIN_PARA = 40          # characters; shorter standalone paragraphs are usually debris
MAX_BLOCKS_PER_BOOK = 4000
SKIP_BOOKS = {
    # CamScanner scan: its text layer is OCR-free noise (also skipped for MCQs)
    "QUANT PRACTISE BOOK",
    # a solved-paper question bank, not a textbook — 79% of its prose is flattened
    # working ("lim lim x x f x x x a → →"). Its value is the 2,835 MCQs plus
    # explanations that extract_mcqs.py already recovers.
    "REASONING PRACTISE BOOK",
}

# Symbol/MT-Extra glyphs (big braces, integrals) map into the private-use area and
# render as empty boxes. They carry no recoverable meaning, so drop them.
PRIVATE_USE = re.compile("[\ue000-\uf8ff\ufffd]+")

GARBLE_LIMIT = 0.45   # above this a block is flattened maths, not readable prose
# symbols that never appear in a real chapter title
MATHY = re.compile(r"[∫∑∏√∂≤≥≠⇒⋅{}=]|\|")


def dehyphenate(text: str) -> str:
    """Repair the two artefacts PDF text extraction leaves behind.

    Line wrapping splits words ('adja- cency'), and ligature glyphs come out as a
    bare 'fi'/'fl' followed by a space ('fi nite', 'Defi niteness'). Neither of
    those fragments is an English word, so rejoining them is safe.
    """
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    text = re.sub(r"\b(fi|fl|ffi|ffl)\s+(?=[a-z])", r"\1", text)
    text = re.sub(r"([A-Za-z])(fi|fl)\s+(?=[a-z])", r"\1\2", text)
    return re.sub(r"\s+", " ", text).strip()


def garble_score(text: str) -> float:
    """How unreadable a block is: 0 is clean prose, 1 is flattened equation debris.

    When PDF text extraction loses an equation's layout it leaves a trail of
    orphaned single letters and operators ("f x x x x x x ( ) , = - + + +"), which
    reads as noise. Runs of single-character tokens and a high operator-to-letter
    ratio are what separate that from real sentences.
    """
    toks = text.split()
    if len(toks) < 6:
        return 0.0
    singles = sum(1 for t in toks if len(t) == 1 and t.lower() not in "ai")
    letters = len(re.findall(r"[A-Za-z]", text))
    ops = len(re.findall(r"[=+\-−⇒→|<>()∈∑≠≤≥∞]", text))
    return max(singles / len(toks), ops / max(letters, 1))


SYMBOLIC = re.compile(r"^[()\[\]{}=+\-−→⇒<>|∈∑∏∫,.;:·⋅‘’“”/^*≤≥≠≈∞]+$")
# a lone letter or digit: in flattened maths these are stranded variables. 'a' and
# 'I' are included (they are variables too), which is safe because a run only
# counts as an equation when it also contains operators — see collapse_math.
ATOMIC = re.compile(r"^(?:[A-Za-z]|\d+)$")
EQ_MARK = "⟨eq⟩"      # the reader renders this as an "equation" chip


def collapse_math(text: str) -> str:
    """Replace runs of orphaned equation tokens with a single marker.

    A flattened equation inside otherwise-readable prose leaves a stretch of
    single letters and operators ('If lim ( ) ( ) x c f x f c -> = We observe').
    Nothing can reconstruct the equation, so say so rather than print the rubble.
    """
    out: list[str] = []
    run: list[str] = []                     # the atomic tokens seen so far

    def close():
        # a lost equation is a long run that also carries operators; without them
        # it is just ordinary prose ('a', 'I', 'x = a') and must be left alone
        symbols = sum(1 for t in run if SYMBOLIC.match(t))
        if len(run) >= 4 and symbols >= 2:
            out.append(EQ_MARK)
        else:
            out.extend(run)
        run.clear()

    for tok in text.split():
        if ATOMIC.match(tok) or SYMBOLIC.match(tok):
            run.append(tok)
            continue
        close()
        out.append(tok)
    close()

    joined = " ".join(out)
    joined = re.sub(rf"(?:{re.escape(EQ_MARK)}[\s,.]*){{2,}}", EQ_MARK + " ", joined)
    return re.sub(r"\s+", " ", joined).strip()


def strip_glyphs(text: str) -> str:
    """Remove unmapped private-use glyphs, then tidy the gaps they leave."""
    text = PRIVATE_USE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def fix_smallcaps(text: str) -> str:
    """Small-caps headings extract with scrambled case ('aLGoRithm'). A lower-case
    letter immediately followed by an upper-case one is the tell; acronyms and
    normally-capitalised titles never look like that."""
    if text != text.upper() and re.search(r"[a-z][A-Z]", text):
        return text.title()
    # a word with exactly two leading capitals is a small-cap leftover
    # ('EQuations'); three or more is a genuine acronym ('SQLite', 'HTTPServer')
    return re.sub(r"\b([A-Z])([A-Z])([a-z]{2,})\b",
                  lambda m: m.group(1) + m.group(2).lower() + m.group(3), text)


def is_heading(text: str) -> bool:
    """Headings are short, titular, and not sentences."""
    if len(re.findall(r"[A-Za-z]", text)) < 4:
        return False                       # '∑2' and similar maths debris
    if len(text.split()) > 9 or text.rstrip().endswith((".", ";", ",")):
        return False
    # equation fragments picked up a large font too: '∫ curl', '= Max {', '∑cosnx'
    if MATHY.search(text):
        return False
    return not NUMBERED.match(text)        # '1. Priori Analysis: ...' is a paragraph


def body_size(doc) -> float:
    """The most common span size in the book — its body text."""
    sizes = Counter()
    for page in doc[: min(60, doc.page_count)]:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span["text"].strip():
                        sizes[round(span["size"], 1)] += len(span["text"])
    return sizes.most_common(1)[0][0] if sizes else 10.0


def page_lines(page) -> list[tuple[str, float, bool, float]]:
    """(text, max span size, is_bold, left edge) per visual line."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line.get("spans", []) if s["text"].strip()]
            if not spans:
                continue
            # spans carry their own spacing only sometimes; when one ends and the
            # next starts with a visible gap, that gap is a real space
            parts = [spans[0]["text"]]
            for prev, cur in zip(spans, spans[1:], strict=False):
                gap = cur["bbox"][0] - prev["bbox"][2]
                if gap > 0.18 * cur["size"] and not prev["text"].endswith((" ", "-")) \
                        and not cur["text"].startswith(" "):
                    parts.append(" ")
                parts.append(cur["text"])
            text = "".join(parts)
            size = max(s["size"] for s in spans)
            bold = any((s["flags"] & 2 ** 4) or "Bold" in s["font"] for s in spans)
            out.append((text.rstrip(), round(size, 1), bold, round(line["bbox"][0], 1)))
    return out


def parse_notes(pdf: Path) -> list[dict]:
    blocks: list[dict] = []
    para: list[str] = []
    skipping = False           # inside the exercise/answer-key part of a chapter
    chapter_pending = None

    with pymupdf.open(pdf) as doc:
        base = body_size(doc)
        h1_min, h2_min = base + 2.4, base + 0.9

        def flush():
            nonlocal para
            if para:
                text = collapse_math(strip_glyphs(dehyphenate(" ".join(para))))
                if (len(text) >= MIN_PARA and not JUNK.match(text)
                        and garble_score(text) <= GARBLE_LIMIT):
                    blocks.append({"t": "p", "x": text})
            para = []

        li_x0 = None       # left edge of the bullet currently being read
        for page in doc:
            for raw, size, bold, x0 in page_lines(page):
                line = raw.strip()
                if not line or NOISE.match(line) or RUNNING_HEAD.search(line):
                    continue

                if STOP.match(line):
                    flush()
                    skipping = True
                    continue

                m = CHAPTER.match(line)
                if m:
                    flush()
                    skipping = False
                    chapter_pending = m.group(1)
                    continue

                # the line after "Chapter N" is its title
                if chapter_pending:
                    flush()
                    blocks.append({"t": "h1", "x": f"{chapter_pending}. {fix_smallcaps(dehyphenate(line))}"})
                    chapter_pending = None
                    skipping = False
                    continue

                if skipping:
                    # a big heading means the next chapter's theory has begun
                    if size >= h1_min and is_heading(dehyphenate(line)):
                        skipping = False
                        blocks.append({"t": "h1", "x": fix_smallcaps(dehyphenate(line))})
                    continue

                m = BULLET.match(line)
                if m:
                    flush()
                    text = collapse_math(strip_glyphs(dehyphenate(m.group(1))))
                    if len(text) > 8 and garble_score(text) <= GARBLE_LIMIT:
                        blocks.append({"t": "li", "x": text})
                        li_x0 = x0
                    continue

                # a bullet's wrapped lines are indented past the bullet itself, so
                # they belong to that list item — but only while it reads as
                # unfinished; once it ends in a full stop the list item is complete
                if (li_x0 is not None and blocks and blocks[-1]["t"] == "li"
                        and not para and x0 > li_x0 + 3
                        and not blocks[-1]["x"].rstrip().endswith((".", "?", "!"))):
                    blocks[-1]["x"] = dehyphenate(blocks[-1]["x"] + " " + line)
                    continue
                li_x0 = None

                text = strip_glyphs(dehyphenate(line))
                if size >= h1_min and is_heading(text):
                    flush()
                    blocks.append({"t": "h1", "x": fix_smallcaps(text)})
                    continue
                if (size >= h2_min or bold) and is_heading(text):
                    flush()
                    blocks.append({"t": "h2", "x": fix_smallcaps(text)})
                    continue

                para.append(line)
                if len(blocks) > MAX_BLOCKS_PER_BOOK:
                    break
        flush()

    return tidy(blocks)


def tidy(blocks: list[dict]) -> list[dict]:
    """Drop headings with no content under them and collapse repeats."""
    out: list[dict] = []
    for b in blocks:
        if out and out[-1]["t"] == b["t"] and out[-1]["x"] == b["x"]:
            continue                                   # repeated running text
        if b["t"] in ("h1", "h2") and out and out[-1]["t"] in ("h1", "h2"):
            if out[-1]["t"] == b["t"]:                 # heading with nothing beneath
                out[-1] = b
                continue
        out.append(b)
    while out and out[-1]["t"] in ("h1", "h2"):
        out.pop()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-dir", default=str(IN_DIR))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()

    in_dir, out_dir = Path(args.in_dir), Path(args.out_dir)
    pdfs = sorted(in_dir.rglob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs under {in_dir} — run scrape.py first.")
    out_dir.mkdir(exist_ok=True)

    total = 0
    for pdf in pdfs:
        if pdf.stem in SKIP_BOOKS:
            print(f"[-] {pdf.stem:<32} skipped (not usable as reading material)")
            continue
        blocks = parse_notes(pdf)
        if not blocks:
            print(f"[-] {pdf.stem:<32} no readable theory found")
            continue
        path = out_dir / (re.sub(r"[^\w.-]+", "_", pdf.stem) + ".json")
        path.write_text(json.dumps(blocks, ensure_ascii=False, indent=1))
        words = sum(len(b["x"].split()) for b in blocks)
        heads = sum(1 for b in blocks if b["t"] == "h1")
        total += words
        print(f"[+] {pdf.stem:<32} {len(blocks):>5} blocks  {heads:>3} chapters  {words:>7,} words")

    print(f"\n{total:,} words of study material -> {out_dir}/")


if __name__ == "__main__":
    main()
