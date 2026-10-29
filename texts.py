"""Text sources (not video): documents such as web pages, PDFs and plain text, plus the common header of every
corpus file.

To read another format, add a reader like these and call it from ingest.
"""
from __future__ import annotations

import hashlib
import html as _html
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

from i18n import tr

def header(title: str, mentor: str, url: str, sid: str, language: str, date: str = "", duration: str = "?") -> str:
    """Header of every corpus file (search.meta() also reads the older Spanish keys)."""
    return (f"# {title}\nmentor: {mentor}\ndate: {date}\nurl: {url}\nduration: {duration}\nid: {sid}\n"
            f"language: {language}\n---\n\n")


# ---------------------------------------------------------------- documents: web pages, PDF and text
# A public-domain book, an article, your own PDF... Each document becomes one corpus file.
# Markers: [p. 12] in a PDF (the citation opens that page: url#page=12) and [¶ 3] in a web page or a text.

PDF_JXA = """ObjC.import('Quartz');
function run(argv) {
  const doc = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(argv[0]));
  if (!doc || doc.isNil()) return '';
  const out = [];
  for (let i = 0; i < doc.pageCount; i++) { const s = doc.pageAtIndex(i).string; out.push(s && !s.isNil() ? s.js : ''); }
  return out.join('\\f');
}"""


class _HtmlText(HTMLParser):
    """HTML to paragraphs, without menus, scripts or footers."""
    SKIP = {"script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg"}
    BLOCKS = {"p", "li", "h1", "h2", "h3", "h4", "blockquote", "pre", "div", "section", "article", "br", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs, self.current, self.skipping, self.title, self._in_title = [], [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skipping += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCKS:
            self.cut()

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skipping:
            self.skipping -= 1
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCKS:
            self.cut()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skipping:
            self.current.append(data)

    def cut(self):
        t = re.sub(r"\s+", " ", "".join(self.current)).strip()
        if len(t) > 1:
            self.paragraphs.append(t)
        self.current = []


def pdf_pages(path: Path) -> list:
    """Text of each page. macOS: PDFKit (built in). Elsewhere: pdftotext if installed."""
    if shutil.which("osascript"):
        r = subprocess.run(["osascript", "-l", "JavaScript", "-e", PDF_JXA, str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.split("\f")
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-enc", "UTF-8", str(path), "-"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        if r.returncode == 0:
            return r.stdout.split("\f")
    raise RuntimeError(tr("I could not read the PDF: on Linux or Windows install pdftotext (poppler).",
                          "No pude leer el PDF: en Linux o Windows instala pdftotext (poppler)."))


def _blocks(paragraphs: list, size: int = 900) -> list:
    """Joins short paragraphs into ~900-character blocks so search has context."""
    out, current = [], ""
    for p in paragraphs:
        if current and len(current) + len(p) > size:
            out.append(current)
            current = ""
        current = (current + " " + p).strip()
    if current:
        out.append(current)
    return out


def document_id(key: str) -> str:
    return "doc-" + hashlib.sha1(key.encode()).hexdigest()[:12]


def document(d: Path, file: Path, url: str, mentor_name: str, language: str, title: str = "", sid: str = "") -> str:
    """Turns an already downloaded PDF, HTML or text into a corpus file. Returns a note."""
    import store
    raw = file.read_bytes()
    sid = sid or document_id(url or file.name)
    if raw[:5] == b"%PDF-":
        pages = pdf_pages(file)
        body = "\n\n".join(f"[p. {i}] {re.sub(chr(10) + '+', ' ', t).strip()}" for i, t in enumerate(pages, 1) if t.strip())
        detail = tr("{n} pages", "{n} páginas", n=len(pages))
    else:
        text = raw.decode("utf-8", errors="replace")
        if re.search(r"<(html|body|p|div)\b", text[:5000], re.I):
            p = _HtmlText()
            p.feed(text)
            p.cut()
            title = title or _html.unescape(p.title).strip()
            paragraphs = p.paragraphs
        else:
            paragraphs = [re.sub(r"\s+", " ", x).strip() for x in re.split(r"\n\s*\n", text) if x.strip()]
        blocks = _blocks(paragraphs)
        body = "\n\n".join(f"[¶ {i}] {b}" for i, b in enumerate(blocks, 1))
        detail = tr("{n} blocks", "{n} bloques", n=len(blocks))
    if not body.strip():
        raise RuntimeError(tr("The document has no readable text ({f}). A scanned PDF needs OCR.",
                              "El documento no trae texto que se pueda leer ({f}). Si es un PDF escaneado, necesita OCR.", f=file.name))
    title = (title or file.stem)[:200].replace("\n", " ")
    out_dir = store.text_dir(d)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{sid}.txt").write_text(header(title, mentor_name, url, sid, language) + body + "\n", encoding="utf-8")
    return tr("Document «{t}»: {d}.", "Documento «{t}»: {d}.", t=title, d=detail)
