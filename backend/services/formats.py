"""Dependency-free writers for XLSX and PDF.

Both formats are written with the standard library only:

* **XLSX** — a minimal but valid Office Open XML package (one sheet, shared
  inline strings, numeric cells, column widths, bold header row).
* **PDF** — a text-only PDF 1.4 document using the base-14 Helvetica font, with
  automatic pagination and simple headings. No external renderer required.

Keeping these local avoids pulling `openpyxl`/`reportlab` into a project that
otherwise has five runtime dependencies.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence
from xml.sax.saxutils import escape

# ------------------------------------------------------------------- XLSX

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_WORKBOOK = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="{sheet}" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""

_WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2">
 <font><sz val="10"/><name val="Calibri"/></font>
 <font><b/><sz val="10"/><name val="Calibri"/></font>
</fonts>
<fills count="2"><fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill></fills>
<borders count="1"><border/></borders>
<cellStyleXfs count="1"><xf/></cellStyleXfs>
<cellXfs count="2">
 <xf xfId="0" fontId="0"/>
 <xf xfId="0" fontId="1"/>
</cellXfs>
</styleSheet>"""


def _col(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def write_xlsx(path: Path, rows: Sequence[Sequence[Any]], sheet_name: str = "Report") -> Path:
    """Write a single-sheet workbook. Header row is bold."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    xml_rows = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{_col(c)}{r}"
            style = ' s="1"' if r == 1 else ""
            if value is None or value == "":
                continue
            if isinstance(value, bool):
                cells.append(f'<c r="{ref}" t="b"{style}><v>{int(value)}</v></c>')
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"{style}><v>{value}</v></c>')
            else:
                text = escape(str(value))
                cells.append(f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{text}</t></is></c>')
        xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    widths = ""
    if rows:
        for c in range(len(rows[0])):
            widths += f'<col min="{c + 1}" max="{c + 1}" width="22" customWidth="1"/>'
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<cols>{widths}</cols><sheetData>{''.join(xml_rows)}</sheetData></worksheet>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("xl/workbook.xml", _WORKBOOK.format(sheet=escape(sheet_name[:31])))
        zf.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS)
        zf.writestr("xl/styles.xml", _STYLES)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    return path


# -------------------------------------------------------------------- PDF

@dataclass
class PdfLine:
    text: str
    size: float = 10.0
    bold: bool = False
    space_after: float = 3.0
    indent: float = 0.0


def _wrap(text: str, size: float, width: float) -> list[str]:
    # Helvetica average glyph width is ~0.5 em; this is an estimate but keeps
    # long lines inside the page without an external text measurement library.
    max_chars = max(20, int(width / (size * 0.5)))
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _pdf_escape(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace("(", r"\(")
        .replace(")", r"\)")
        .encode("latin-1", "replace")
        .decode("latin-1")
    )


def write_pdf(path: Path, lines: Iterable[PdfLine], title: str = "Report") -> Path:
    """Write a paginated text PDF using Helvetica / Helvetica-Bold."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    page_w, page_h = 595.0, 842.0  # A4 in points
    margin = 48.0
    content_w = page_w - 2 * margin

    pages: list[list[str]] = []
    current: list[str] = []
    y = page_h - margin

    def new_page() -> None:
        nonlocal current, y
        if current:
            pages.append(current)
        current = []
        y = page_h - margin

    for line in lines:
        for segment in _wrap(line.text, line.size, content_w - line.indent) or [""]:
            if y < margin + line.size + 10:
                new_page()
            font = "F2" if line.bold else "F1"
            current.append(
                f"BT /{font} {line.size} Tf 1 0 0 1 {margin + line.indent:.1f} {y:.1f} Tm "
                f"({_pdf_escape(segment)}) Tj ET"
            )
            y -= line.size + 3.2
        y -= line.space_after
    if current:
        pages.append(current)
    if not pages:
        pages = [["BT /F1 10 Tf 1 0 0 1 48 794 Tm (Empty report) Tj ET"]]

    objects: list[bytes] = []
    n_pages = len(pages)
    font_f1 = 3 + 2 * n_pages
    font_f2 = font_f1 + 1
    page_obj_numbers = [3 + 2 * i for i in range(n_pages)]

    header = f"%PDF-1.4\n%BTI\n".encode("latin-1")
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{n} 0 R" for n in page_obj_numbers)
    objects.append(f"<< /Type /Pages /Count {n_pages} /Kids [{kids}] >>".encode())
    for i, content in enumerate(pages):
        content_bytes = "\n".join(content).encode("latin-1", "replace")
        content_obj = 3 + 2 * i + 1
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w} {page_h}] "
                f"/Resources << /Font << /F1 {font_f1} 0 R /F2 {font_f2} 0 R >> >> "
                f"/Contents {content_obj} 0 R >>"
            ).encode()
        )
        objects.append(
            b"<< /Length " + str(len(content_bytes)).encode() + b" >>\nstream\n" + content_bytes + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    info_obj = len(objects) + 1
    from datetime import timezone

    stamp = datetime.now(timezone.utc).strftime("D:%Y%m%d%H%M%SZ")
    objects.append(
        f"<< /Title ({_pdf_escape(title)}) /Producer (Brij Trading Intelligence) "
        f"/CreationDate ({stamp}) >>".encode()
    )

    out = bytearray(header)
    offsets: list[int] = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {info_obj} 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    path.write_bytes(bytes(out))
    return path
