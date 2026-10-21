"""A clean PDF from résumé or letter text ('# Name', '## Section', '- bullet' lines), with only the standard library.

Uses the PDF's built-in Helvetica, so there are no fonts to embed; text is written in Windows-1252, which covers
English and Western European accents, curly quotes, dashes and bullets.
"""

from __future__ import annotations

PAGE_W, PAGE_H, MARGIN = 612, 792, 54
# Helvetica advance widths (1/1000 em) for characters 32-126, from the standard AFM
_W = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556,
      556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833,
      722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556,
      556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334,
      260, 334, 584]


def _width(text: str, size: float, bold: bool) -> float:
    w = sum(_W[ord(c) - 32] if 32 <= ord(c) <= 126 else 556 for c in text)
    return w * size / 1000 * (1.07 if bold else 1)


def _wrap(text: str, size: float, bold: bool, width: float) -> list:
    lines, cur = [], ""
    for word in text.split(" "):
        trial = f"{cur} {word}" if cur else word
        if _width(trial, size, bold) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + [cur]


def _esc(text: str) -> bytes:
    raw = text.encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def from_text(text: str, letter: bool = False) -> bytes:
    """letter=True: plain paragraphs (a cover letter); otherwise résumé markup."""
    pages, ops, y = [], [], PAGE_H - MARGIN
    usable = PAGE_W - 2 * MARGIN

    def new_page():
        nonlocal ops, y
        pages.append(ops)
        ops, y = [], PAGE_H - MARGIN

    def write(line: str, size: float, bold=False, x=MARGIN, center=False, gap=0.0, rule=False, indent=0.0, bullet=False):
        nonlocal y
        lead = size * 1.3
        wrapped = _wrap(line, size, bold, usable - indent)
        if y - gap - lead * len(wrapped) < MARGIN and y < PAGE_H - MARGIN:
            new_page()
        y -= gap
        for i, part in enumerate(wrapped):
            y -= lead
            if y < MARGIN:
                new_page()
                y -= lead
            px = (PAGE_W - _width(part, size, bold)) / 2 if center else x + indent
            if bullet and i == 0:
                ops.append(b"BT /F1 %.1f Tf %.1f %.1f Td (\x95) Tj ET" % (size, x + indent - 10, y))
            ops.append(b"BT /%s %.1f Tf %.1f %.1f Td (%s) Tj ET" % (b"F2" if bold else b"F1", size, px, y, _esc(part)))
        if rule:
            ops.append(b"0.6 G 0.6 w %.1f %.1f m %.1f %.1f l S 0 G" % (MARGIN, y - 4, PAGE_W - MARGIN, y - 4))
            y -= 4

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            y -= 11 if letter else 0
            continue
        if letter:
            write(line.strip(), 11, gap=2)
        elif line.startswith("# "):
            write(line[2:].strip(), 17, bold=True, center=True)
        elif line.startswith("## "):
            write(line[3:].strip().upper(), 11, bold=True, gap=10, rule=True)
        elif line.startswith("### "):
            write(line[4:].strip(), 10.5, bold=True, gap=4)
        elif line.lstrip().startswith(("- ", "* ", "• ")):
            write(line.lstrip()[2:].strip(), 10.5, indent=14, bullet=True, gap=1)
        else:
            write(line.strip(), 10.5, gap=1)
    pages.append(ops)

    # objects: 1 catalog, 2 pages, 3 regular font, 4 bold font, then a page and its content stream for each page
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", None,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
    kids = []
    for page_ops in pages:
        stream = b"\n".join(page_ops)
        content_id, page_id = len(objs) + 2, len(objs) + 1
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                    b"/Contents %d 0 R >>" % (PAGE_W, PAGE_H, content_id))
        objs.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        kids.append(b"%d 0 R" % page_id)
    objs[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(kids), len(kids))
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)
