"""Extract MCQs (question, options, answer, explanation) from the course PDFs into JSON.

These are GATE-style textbooks: each chapter has question sections ("Practice Problems 1/2",
"Previous Years' Questions") followed by an "Answer Keys" grid that maps question numbers to
letters. Answers are matched back to questions by (chapter, section, number). Some books also
carry inline "Solution:"/"Explanation:" text, which is captured when present.
"""

import argparse
import json
import re
from pathlib import Path

import pymupdf

ROOT = Path(__file__).parent
IN_DIR = ROOT / "downloads"
OUT_DIR = ROOT / "mcqs"

# running page header — books vary: "Chapter 1 • Asymptotic Analysis | 3.91"
# and "4.20 | Unit 4 • Databases" both occur, so match the label anywhere in the line.
HEADER = re.compile(r"(?:Chapter|Unit)\s+(\d+)\s*[•·■]\s*([^|■]+?)\s*(?:[|■].*)?$", re.I)
CHAPTER_NUM = re.compile(r"^Chapter\s+(\d+)\s*$", re.I)
SECTION = re.compile(
    r"^(Practice\s+Problems\s*\d*|Previous\s+Years[’']?\s+Questions|Exercises)\s*$", re.I
)
ANSWER_KEYS = re.compile(r"^Answer\s*Keys?\s*$", re.I)
DIRECTIONS = re.compile(r"^Directions\s+for\s+question", re.I)
QUESTION = re.compile(r"^(\d{1,3})\.\s+(.*)$")
OPTION = re.compile(r"^\(([A-Da-d])\)\s*(.*)$")
EXPLAIN = re.compile(r"^(?:Solution|Explanation|Hints?)\s*[:.]\s*(.*)$", re.I)
# solved-paper books answer inline: "Ans. (c) : <worked solution>"
ANS_INLINE = re.compile(r"^Ans(?:wer)?\b\.?\s*\(?([A-Da-d])\)?\s*[:.)]?\s*(.*)$", re.I)
# exam attribution lines that sit between the options and the answer
EXAM_LINE = re.compile(
    r"^(?:SSC|RRB|UPSC|IBPS|CGL|CHSL|MTS|CPO|GD|NTPC|Group\s*D)\b.*", re.I
)
# "1.  A" and also multi-part forms like "1.  (i)  B   (ii)  A"
KEY_PAIR = re.compile(r"(\d{1,3})\.\s*(?:\([ivx]+\)\s*)?\(?([A-Da-d])\)?(?!\w)")
NOISE = re.compile(r"^(?:www\.|https?://|©|\d+\s*\|\s*Page|Page\s*\d+)", re.I)


def clean(line: str) -> str:
    """Normalise the odd whitespace pdf text extraction produces."""
    return re.sub(r"[\t   ]+", " ", line).strip()


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strip_running_head(lines: list[str]) -> list[str]:
    """Some books print a 'Chapter / page-no / publisher' head as the first lines
    of every page (e.g. 'Algebra', '40', 'YCT'). Drop it so it can't leak into
    the question or option it would otherwise be appended to."""
    for i, raw in enumerate(lines[:4]):
        if raw.strip().upper() == "YCT":
            return lines[i + 1:]
    return lines


def pages(pdf: Path):
    with pymupdf.open(pdf) as doc:
        for i, page in enumerate(doc, 1):
            yield i, strip_running_head(page.get_text("text").splitlines())


def parse(pdf: Path) -> list[dict]:
    questions: list[dict] = []
    pending: list[dict] = []  # questions since the last Answer Keys block
    keys: dict[tuple, str] = {}  # (section, number) -> letter, for the current block

    chapter = ""
    section = ""
    in_keys = False
    key_section = ""
    cur: dict | None = None
    field = None  # "question" | "option" | "explanation"
    opt_key = None
    pending_chapter_num = None

    def flush():
        nonlocal cur
        if cur and cur["question"] and len(cur["options"]) >= 2:
            cur["question"] = squash(cur["question"])
            cur["options"] = {k: squash(v) for k, v in cur["options"].items()}
            cur["explanation"] = squash(cur["explanation"]) or None
            questions.append(cur)
            pending.append(cur)
        cur = None

    def apply_keys():
        """Answer Keys follow the questions they belong to, so match positionally."""
        for q in pending:
            letter = keys.get((q["section"], q["number"]))
            if letter and not q["answer"]:
                q["answer"] = letter
        pending.clear()
        keys.clear()

    for pageno, raw_lines in pages(pdf):
        for raw in raw_lines:
            line = clean(raw)
            if not line or NOISE.match(line):
                continue

            # the label sits at either end of the running head:
            # "Chapter 1 • Asymptotic Analysis | 3.91" and "3.96 | Unit 3 • Algorithms"
            # some unit titles run long ("Unit 8 • Networks, Information Systems,
            # Software Engineering and Web Technology"), so the position of the
            # label — not the line length — is what keeps this from eating prose
            m = HEADER.search(line)
            if m and m.start() <= 14 and len(line) < 160:
                chapter = f"{m.group(1)} - {m.group(2)}"
                continue
            m = CHAPTER_NUM.match(line)
            if m:
                pending_chapter_num = m.group(1)
                continue
            if pending_chapter_num and not SECTION.match(line):
                chapter = f"{pending_chapter_num} - {line}"
                pending_chapter_num = None
                continue

            if ANSWER_KEYS.match(line):
                flush()
                in_keys = True
                # books with a single bare "Exercises" heading print no section label
                # inside the keys block, so default to the section just parsed
                key_section = section
                continue

            m = SECTION.match(line)
            if m:
                name = squash(m.group(1))
                if in_keys:
                    key_section = name
                else:
                    flush()
                    section = name
                    field = None
                continue

            if in_keys:
                # a grid of "1.  A   2.  D   ..." pairs
                found = KEY_PAIR.findall(line)
                if found:
                    for num, letter in found:
                        keys.setdefault((key_section, int(num)), letter.upper())
                    continue
                # a question/option line means the keys block is over
                if QUESTION.match(line) or OPTION.match(line):
                    in_keys = False
                    apply_keys()
                else:
                    continue

            if DIRECTIONS.match(line):
                continue

            m = ANS_INLINE.match(line)
            if m and cur:
                cur["answer"] = m.group(1).upper()
                cur["explanation"] += " " + m.group(2)
                field = "explanation"
                continue

            if EXAM_LINE.match(line) and field == "option":
                continue

            m = OPTION.match(line)
            if m and cur:
                opt_key = m.group(1).upper()
                cur["options"][opt_key] = m.group(2)
                field = "option"
                continue

            m = EXPLAIN.match(line)
            if m and cur:
                cur["explanation"] += " " + m.group(1)
                field = "explanation"
                continue

            m = QUESTION.match(line)
            # solved-paper books have no section headings at all, so accept a bare
            # numbered question too — flush() drops anything without real options
            if m:
                flush()
                cur = {
                    "chapter": chapter,
                    "section": section,
                    "number": int(m.group(1)),
                    "question": m.group(2),
                    "options": {},
                    "answer": None,
                    "explanation": "",
                    "page": pageno,
                }
                field, opt_key = "question", None
                continue

            if not cur:
                continue
            if field == "question":
                cur["question"] += " " + line
            elif field == "option" and opt_key:
                cur["options"][opt_key] += " " + line
            elif field == "explanation":
                cur["explanation"] += " " + line

    flush()
    apply_keys()
    return questions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-dir", default=str(IN_DIR))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()

    in_dir, out_dir = Path(args.in_dir), Path(args.out_dir)
    pdfs = sorted(in_dir.rglob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs under {in_dir} — run browser_download.py first.")
    out_dir.mkdir(exist_ok=True)

    total = 0
    for pdf in pdfs:
        rel = pdf.relative_to(in_dir)
        qs = parse(pdf)
        for q in qs:
            q["subject"] = pdf.stem
            q["source"] = str(rel)
        path = out_dir / (re.sub(r"[^\w.-]+", "_", pdf.stem) + ".json")
        path.write_text(json.dumps(qs, indent=2, ensure_ascii=False))
        total += len(qs)

        with_ans = sum(1 for q in qs if q["answer"])
        with_exp = sum(1 for q in qs if q["explanation"])
        full = sum(1 for q in qs if len(q["options"]) == 4)
        print(
            f"[+] {pdf.stem:<32} {len(qs):>4} questions  "
            f"({full} with 4 options, {with_ans} with answer, {with_exp} with explanation)"
        )

    print(f"\n{total} questions written to {out_dir}/")


if __name__ == "__main__":
    main()
