"""Turn PDF, DOC/DOCX and image files into a list of pages.

Every page becomes a PNG image (what vision extractors read) plus any text layer
the file already had (cheap and exact for typed documents).
"""

from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

SUPPORTED = {".pdf", ".docx", ".doc", ".jpg", ".jpeg", ".png"}
MAX_EDGE = 2000  # px; plenty for handwriting, keeps API payloads small
PDF_DPI = 200


@dataclass
class PageInput:
    page_id: str
    source_file: str
    page_number: int  # 1-based
    image_png: Optional[bytes]
    text_layer: Optional[str] = None


def _normalize_image(img: Image.Image) -> bytes:
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((MAX_EDGE, MAX_EDGE))
    img = ImageOps.autocontrast(img, cutoff=1)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _page_id(path: Path, page_number: int, payload: bytes) -> str:
    digest = hashlib.sha256(payload).hexdigest()[:16]
    return f"{path.stem}-p{page_number}-{digest}"


def _load_pdf(path: Path) -> list[PageInput]:
    import pymupdf

    pages = []
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text().strip() or None
            pix = page.get_pixmap(dpi=PDF_DPI)
            png = _normalize_image(Image.open(io.BytesIO(pix.tobytes("png"))))
            pages.append(PageInput(_page_id(path, i, png), str(path), i, png, text))
    return pages


def _load_image(path: Path) -> list[PageInput]:
    with Image.open(path) as img:
        png = _normalize_image(img)
    return [PageInput(_page_id(path, 1, png), str(path), 1, png)]


def _docx_text(path: Path) -> str:
    import docx

    d = docx.Document(str(path))
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for table in d.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(parts)


def _soffice_convert(path: Path, fmt: str) -> Path:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError(f"LibreOffice is needed to read {path.suffix} files but was not found.")
    out_dir = Path(tempfile.mkdtemp(prefix="medtimeline-"))
    subprocess.run(
        [soffice, "--headless", "--convert-to", fmt, "--outdir", str(out_dir), str(path)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    converted = out_dir / f"{path.stem}.{fmt}"
    if not converted.exists():
        raise RuntimeError(f"LibreOffice could not convert {path.name} to {fmt}.")
    return converted


def _load_word(path: Path) -> list[PageInput]:
    if path.suffix.lower() == ".doc":
        path_docx = _soffice_convert(path, "docx")
    else:
        path_docx = path
    text = _docx_text(path_docx)
    # Word files can contain scanned images or layout that matters, so render
    # pages too when LibreOffice is available; otherwise fall back to text only.
    try:
        pages = _load_pdf(_soffice_convert(path_docx, "pdf"))
        for p in pages:
            p.source_file = str(path)
        if pages and not any(p.text_layer for p in pages):
            pages[0].text_layer = text
        return pages
    except (RuntimeError, subprocess.SubprocessError):
        payload = text.encode()
        return [PageInput(_page_id(path, 1, payload), str(path), 1, None, text)]


def load_document(path: str | Path) -> list[PageInput]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(f"Unsupported file type: {path.name}")
    if suffix == ".pdf":
        return _load_pdf(path)
    if suffix in {".docx", ".doc"}:
        return _load_word(path)
    return _load_image(path)


def load_folder(folder: str | Path) -> list[PageInput]:
    pages: list[PageInput] = []
    for f in sorted(Path(folder).rglob("*")):
        if f.is_file() and f.suffix.lower() in SUPPORTED:
            pages.extend(load_document(f))
    return pages
