"""Render a methodology memo to a Word file at a controlled page count.

Pasting markdown straight into Word applies its default heading styles, which are
sized for reports rather than memos and push the Part 1 memo to four pages. This
builds the document directly instead, so point sizes, leading, margins and tables
are all set explicitly.

Run:
    .venv/bin/python src/memo_to_docx.py                       # Part 1, two pages
    .venv/bin/python src/memo_to_docx.py docs/cardinal_methodology_memo.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MEMO = ROOT / "docs" / "methodology_memo.md"

# Part 1 has a hard two-page limit and no tables. Part 2 runs three to five pages, so
# it can afford slightly more leading and the tables that carry the triangulation.
PROFILES = {
    "compact": {"body": 10.0, "h1": 13.0, "h2": 10.5, "h3": 10.0, "lead": 1.10, "after": 4},
    "standard": {"body": 9.5, "h1": 13.5, "h2": 11.0, "h3": 10.0, "lead": 1.10, "after": 4},
}
PROFILE_BY_MEMO = {"methodology_memo": "compact"}

FONT = "Calibri"
MONO = "Consolas"
MARGIN = Inches(0.8)
RULE = RGBColor(0x99, 0x99, 0x99)


def set_cell_margins(table, top: int, bottom: int, side: int = 72) -> None:
    """Word defaults to a loose cell inset; these memos need a tight one. Twips."""
    margins = table._tbl.tblPr.makeelement(qn("w:tblCellMar"), {})
    for edge, value in (("top", top), ("left", side), ("bottom", bottom), ("right", side)):
        node = margins.makeelement(qn(f"w:{edge}"), {})
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")
        margins.append(node)
    table._tbl.tblPr.append(margins)


def set_cell_background(cell, hex_colour: str) -> None:
    shd = cell._tc.get_or_add_tcPr().makeelement(qn("w:shd"), {})
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hex_colour)
    cell._tc.get_or_add_tcPr().append(shd)


def add_runs(paragraph, text: str, size: float) -> None:
    """Apply the inline markdown these memos use: **bold**, *italic*, `code`."""
    for token in re.split(r"(\*\*[^*]+\*\*|(?<!\*)\*[^*]+\*(?!\*)|`[^`]+`)", text):
        if not token:
            continue
        run = paragraph.add_run()
        run.font.size = Pt(size)
        if token.startswith("**") and token.endswith("**"):
            run.text, run.bold = token[2:-2], True
        elif token.startswith("`") and token.endswith("`"):
            run.text = token[1:-1]
            run.font.name = MONO
            run.font.size = Pt(size - 0.5)
        elif token.startswith("*") and token.endswith("*"):
            run.text, run.italic = token[1:-1], True
        else:
            run.text = token


def style_paragraph(paragraph, profile: dict, size: float, space_after: float, keep=False):
    fmt = paragraph.paragraph_format
    fmt.line_spacing = profile["lead"]
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(space_after)
    fmt.keep_with_next = keep
    return paragraph


def split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_table(lines: list[str]) -> bool:
    return (
        len(lines) >= 2
        and lines[0].startswith("|")
        and bool(re.fullmatch(r"\|[\s:|-]+\|", lines[1]))
    )


def add_table(doc: Document, lines: list[str], profile: dict) -> None:
    header = split_row(lines[0])
    # A colon on the right of the divider means the column is numeric, so right-align.
    aligns = [
        WD_ALIGN_PARAGRAPH.RIGHT
        if c.endswith(":") and not c.startswith(":")
        else WD_ALIGN_PARAGRAPH.LEFT
        for c in split_row(lines[1])
    ]
    body = [split_row(ln) for ln in lines[2:]]

    table = doc.add_table(rows=len(body) + 1, cols=len(header))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    set_cell_margins(table, top=10, bottom=10)
    size = profile["body"] - 0.5

    for j, text in enumerate(header):
        cell = table.rows[0].cells[j]
        cell.text = ""
        p = style_paragraph(cell.paragraphs[0], profile, size, 0, keep=True)
        p.alignment = aligns[j] if j < len(aligns) else WD_ALIGN_PARAGRAPH.LEFT
        add_runs(p, f"**{text}**" if text else "", size)
        set_cell_background(cell, "EEEEEE")

    for i, row in enumerate(body, start=1):
        for j, text in enumerate(row):
            cell = table.rows[i].cells[j]
            cell.text = ""
            p = style_paragraph(cell.paragraphs[0], profile, size, 0)
            p.alignment = aligns[j] if j < len(aligns) else WD_ALIGN_PARAGRAPH.LEFT
            add_runs(p, text, size)

    style_paragraph(doc.add_paragraph(), profile, 4, profile["after"])


def build(markdown: str, profile: dict) -> Document:
    doc = Document()
    section = doc.sections[0]
    section.top_margin = section.bottom_margin = MARGIN
    section.left_margin = section.right_margin = MARGIN

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(profile["body"])

    for block in re.split(r"\n\s*\n", markdown.strip()):
        lines = [ln.strip() for ln in block.strip().splitlines()]
        if is_table(lines):
            add_table(doc, lines, profile)
        elif all(ln.startswith(("- ", "* ")) for ln in lines):
            for ln in lines:
                p = doc.add_paragraph(style="List Bullet")
                style_paragraph(p, profile, profile["body"], 1)
                p.paragraph_format.left_indent = Inches(0.25)
                add_runs(p, ln[2:], profile["body"])
            style_paragraph(doc.add_paragraph(), profile, 3, profile["after"] - 3)
        elif re.match(r"^\d+\.\s", lines[0]):
            for ln in lines:
                p = doc.add_paragraph(style="List Number")
                style_paragraph(p, profile, profile["body"], 1)
                p.paragraph_format.left_indent = Inches(0.25)
                add_runs(p, re.sub(r"^\d+\.\s+", "", ln), profile["body"])
            style_paragraph(doc.add_paragraph(), profile, 3, profile["after"] - 3)
        elif lines[0].startswith(("# ", "## ", "### ")):
            level = len(lines[0]) - len(lines[0].lstrip("#"))
            size = profile[f"h{level}"]
            p = doc.add_paragraph()
            style_paragraph(p, profile, size, 2 if level > 1 else 3, keep=True)
            p.paragraph_format.space_before = Pt(0 if level == 1 else 7 - level)
            run = p.add_run(lines[0].lstrip("# ").strip())
            run.bold = True
            run.font.size = Pt(size)
        else:
            p = doc.add_paragraph()
            style_paragraph(p, profile, profile["body"], profile["after"])
            for i, ln in enumerate(lines):
                if i:
                    p.add_run().add_break()
                add_runs(p, ln, profile["body"])
    return doc


def main() -> int:
    memo = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_MEMO
    if not memo.exists():
        raise SystemExit(f"no such memo: {memo}")
    profile = PROFILES[PROFILE_BY_MEMO.get(memo.stem, "standard")]

    docx = memo.with_suffix(".docx")
    build(memo.read_text(), profile).save(docx)
    print(f"Wrote {docx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
