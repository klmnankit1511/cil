"""Regression tests for the MCQ parser.

Builds small synthetic PDFs in the layouts the real course books use, then checks
the parser recovers questions, options, answers and explanations from each.
Run directly: python tests/test_extract.py
"""

import sys
import tempfile
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extract_mcqs import parse  # noqa: E402


def make_pdf(pages: list[str]) -> Path:
    """Render each string as one page and return the file path."""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(40, 40, 545, 780), text, fontsize=9)
    path = Path(tempfile.mkdtemp()) / "sample.pdf"
    doc.save(path)
    doc.close()
    return path


def check(name: str, cond: bool, detail: str = "") -> bool:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{'' if cond else '  <- ' + detail}")
    return cond


# --------------------------------------------------------------------------- cases


def test_answer_key_grid() -> bool:
    """Textbook layout: questions, then a separate Answer Keys grid."""
    pdf = make_pdf([
        "Chapter 1  •  Asymptotic Analysis  |  3.91\n"
        "Exercises\n"
        "Practice Problems 1\n"
        "Directions for questions 1 to 3:  Select the correct alternative.\n"
        "1. What is the time complexity of binary search?\n"
        "(A) O(n)\n(B) O(log n)\n(C) O(n log n)\n(D) O(1)\n"
        "2. Which structure is LIFO?\n"
        "(A) Queue\n(B) Stack\n(C) Heap\n(D) Graph\n"
        "3. Worst case of quicksort?\n"
        "(A) O(n)\n(B) O(n log n)\n(C) O(n2)\n(D) O(1)\n",

        "Chapter 1  •  Asymptotic Analysis  |  3.97\n"
        "Answer Keys\n"
        "Exercises\n"
        "Practice Problems 1\n"
        "1.  B\t2.  B\t3.  C\n",
    ])
    qs = parse(pdf)
    ok = check("grid: 3 questions parsed", len(qs) == 3, f"got {len(qs)}")
    if len(qs) == 3:
        got = [q["answer"] for q in qs]
        ok &= check("grid: answers B/B/C", got == ["B", "B", "C"], str(got))
        ok &= check("grid: 4 options each",
                    all(len(q["options"]) == 4 for q in qs))
        ok &= check("grid: question text kept",
                    "binary search" in qs[0]["question"], qs[0]["question"][:50])
    return ok


def test_inline_solved_paper() -> bool:
    """Solved-paper layout: 'Ans. (c) :' inline, followed by a worked solution."""
    pdf = make_pdf([
        "169. If x = 2 - p, then x3 + 6xp + p3 is equal to?\n"
        "(a) 12\n(b) 6\n(c) 8\n(d) 4\n"
        "SSC CGL (TIER-I)-2018 - 07.06.2019 (Shift-I)\n"
        "Ans. (c) : On cubing both sides we get 8.\n",
    ])
    qs = parse(pdf)
    ok = check("inline: 1 question parsed", len(qs) == 1, f"got {len(qs)}")
    if qs:
        q = qs[0]
        ok &= check("inline: answer C", q["answer"] == "C", str(q["answer"]))
        ok &= check("inline: explanation captured",
                    bool(q["explanation"]) and "cubing" in q["explanation"],
                    str(q["explanation"]))
        ok &= check("inline: exam line not in options",
                    not any("SSC CGL" in v for v in q["options"].values()),
                    str(q["options"]))
    return ok


def test_running_head_not_leaked() -> bool:
    """'Algebra / 40 / YCT' head must not append itself to the last option."""
    pdf = make_pdf([
        "Algebra\n40\nYCT\n"
        "12. What is 2 + 2?\n"
        "(a) 3\n(b) 4\n(c) 5\n(d) 6\n"
        "Ans. (b) : Simple addition.\n",
    ])
    qs = parse(pdf)
    ok = check("head: 1 question parsed", len(qs) == 1, f"got {len(qs)}")
    if qs:
        vals = " ".join(qs[0]["options"].values()) + qs[0]["question"]
        ok &= check("head: no YCT leak", "YCT" not in vals, vals[:80])
    return ok


def test_page_number_first_header() -> bool:
    """'3.96 | Unit 3 · Algorithms' is a header, not option text.

    The books use U+2022; the base-14 PDF font here cannot encode it (it would
    extract as '?'), so this uses the Latin-1 middle dot — the ordering being
    tested, page number before the label, is identical.
    """
    pdf = make_pdf([
        "Exercises\n"
        "Practice Problems 1\n"
        "1. Complexity of setting twin pointers?\n"
        "(A) O(n2)\n(B) O(n + m)\n(C) O(m2)\n(D) O(n4)\n"
        "3.96  |  Unit 3  ·  Algorithms\n",
    ])
    qs = parse(pdf)
    ok = check("hdr: 1 question parsed", len(qs) == 1, f"got {len(qs)}")
    if qs:
        vals = " ".join(qs[0]["options"].values())
        ok &= check("hdr: header not in options",
                    "Unit 3" not in vals and "3.96" not in vals, vals[:80])
    return ok


def main() -> int:
    tests = [
        ("answer-key grid", test_answer_key_grid),
        ("inline solved paper", test_inline_solved_paper),
        ("running head stripped", test_running_head_not_leaked),
        ("page-number-first header", test_page_number_first_header),
    ]
    failed = []
    for name, fn in tests:
        print(f"\n{name}:")
        if not fn():
            failed.append(name)

    print("\n" + "-" * 52)
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print(f"All {len(tests)} extraction tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
