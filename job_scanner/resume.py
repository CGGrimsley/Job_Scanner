"""Turning an uploaded résumé file into text. Word and plain text are read here; a PDF is read by Claude."""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree

from . import ai

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MAX_FILE = 8_000_000


class ResumeError(ValueError):
    pass


def docx_text(blob: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            xml = z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError):
        raise ResumeError("That doesn't look like a Word (.docx) file.") from None
    root = ElementTree.fromstring(xml)
    lines = []
    for p in root.iter(W + "p"):
        text = "".join(t.text or "" for t in p.iter(W + "t"))
        bullet = p.find(f"{W}pPr/{W}numPr") is not None
        if text.strip():
            lines.append(("- " if bullet else "") + text.strip())
    return "\n".join(lines)


def read(filename: str, blob: bytes) -> dict:
    """{'resume_text', and when Claude read it, 'skills', 'titles', 'years_experience'}"""
    if len(blob) > MAX_FILE:
        raise ResumeError("That file is over 8 MB.")
    name = (filename or "").lower()
    if name.endswith(".docx"):
        return {"resume_text": docx_text(blob)}
    if name.endswith((".txt", ".md", ".text")):
        return {"resume_text": blob.decode("utf-8", errors="replace").strip()}
    if name.endswith(".pdf") or blob[:5] == b"%PDF-":
        out = ai.read_resume(filename, blob)
        out["resume_text"] = re.sub(r"\n{3,}", "\n\n", str(out.get("resume_text") or "")).strip()
        return out
    raise ResumeError("Upload a PDF, Word (.docx) or text file, or paste your résumé instead.")
