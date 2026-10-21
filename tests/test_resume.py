import io
import zipfile

import pytest

from job_scanner import resume


def docx(paragraphs):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f'<w:p>{"<w:pPr><w:numPr/></w:pPr>" if b else ""}<w:r><w:t>{t}</w:t></w:r></w:p>' for t, b in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


def test_docx():
    out = resume.read("me.docx", docx([("Jane Doe", False), ("Built dashboards in Tableau", True)]))
    assert out["resume_text"] == "Jane Doe\n- Built dashboards in Tableau"


def test_text_and_bad_files():
    assert resume.read("cv.txt", "Hello".encode())["resume_text"] == "Hello"
    with pytest.raises(resume.ResumeError):
        resume.read("cv.exe", b"MZ")
    with pytest.raises(resume.ResumeError):
        resume.read("cv.docx", b"not a zip")
