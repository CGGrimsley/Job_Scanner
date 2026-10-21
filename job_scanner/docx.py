"""A plain Word document from résumé text ('# Name', '## Section', '- bullet' lines), with only the standard library."""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                 '<Default Extension="xml" ContentType="application/xml"/>'
                 '<Override PartName="/word/document.xml" '
                 'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                 '</Types>')
RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>')


def _para(text: str, size: int = 21, bold: bool = False, before: int = 0, after: int = 60, indent: bool = False,
          center: bool = False, rule: bool = False) -> str:
    ppr = f'<w:spacing w:before="{before}" w:after="{after}"/>'
    if indent:
        ppr += '<w:ind w:left="360" w:hanging="220"/>'
    if center:
        ppr += '<w:jc w:val="center"/>'
    if rule:
        ppr = '<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="808080"/></w:pBdr>' + ppr
    rpr = f'<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="{size}"/>' + ("<w:b/>" if bold else "")
    return f'<w:p><w:pPr>{ppr}</w:pPr><w:r><w:rPr>{rpr}</w:rPr><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def from_text(text: str) -> bytes:
    body = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        if line.startswith("# "):
            body.append(_para(line[2:].strip(), size=32, bold=True, after=40, center=True))
        elif line.startswith("## "):
            body.append(_para(line[3:].strip().upper(), size=22, bold=True, before=200, after=80, rule=True))
        elif line.startswith("### "):
            body.append(_para(line[4:].strip(), size=21, bold=True, before=100, after=20))
        elif line.lstrip().startswith(("- ", "* ", "• ")):
            body.append(_para("•\t" + line.lstrip()[2:].strip(), indent=True, after=30))
        else:
            body.append(_para(line.strip()))
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           + "".join(body) +
           '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1080" w:right="1080" w:bottom="1080" '
           'w:left="1080" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr></w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc)
    return buf.getvalue()
