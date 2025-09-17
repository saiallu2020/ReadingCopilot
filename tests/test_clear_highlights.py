from readingcopilot.core.annotations import AnnotationDocument, Highlight, Rect


def test_clear_highlights(tmp_path):
    pdf_path = str(tmp_path / "sample.pdf")
    # Create doc with two highlights
    doc = AnnotationDocument(pdf_path=pdf_path)
    h1 = Highlight(page_index=0, rects=[Rect(x1=0, y1=0, x2=10, y2=10)])
    h2 = Highlight(page_index=1, rects=[Rect(x1=5, y1=5, x2=15, y2=15)])
    doc.add_highlight(h1)
    doc.add_highlight(h2)
    assert len(doc.highlights) == 2

    doc.clear_highlights()
    assert doc.highlights == []
