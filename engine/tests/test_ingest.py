import docx

from medtimeline.ingest import MAX_EDGE, load_document, load_folder


def test_load_folder_reads_pdf_and_images(sample_folder):
    pages = load_folder(sample_folder)
    assert [p.source_file.split("/")[-1] for p in pages] == ["visit_a.pdf", "visit_b.png", "visit_c.png"]
    assert all(p.image_png and p.image_png.startswith(b"\x89PNG") for p in pages)
    assert len({p.page_id for p in pages}) == 3


def test_large_images_are_downscaled(tmp_path):
    from io import BytesIO

    from PIL import Image

    Image.new("RGB", (4000, 3000), "white").save(tmp_path / "big.jpg")
    [page] = load_document(tmp_path / "big.jpg")
    assert max(Image.open(BytesIO(page.image_png)).size) == MAX_EDGE


def test_docx_text_is_kept(tmp_path):
    d = docx.Document()
    d.add_paragraph("Diagnosis: Hypertension")
    d.save(tmp_path / "note.docx")
    pages = load_document(tmp_path / "note.docx")
    assert any("Hypertension" in (p.text_layer or "") for p in pages)
