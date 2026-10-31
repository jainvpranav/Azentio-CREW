"""Detect file type + PDF layout, dispatch to the right parser."""
import pdfplumber

from app.ingest import pdf_layout_a, pdf_layout_b, pdf_parser, structured_parser
from app.ingest.pdf_parser import ParsedStatement, PDFParseError


def parse_pdf_document(file_path: str) -> ParsedStatement:
    """
    Try each known layout's can_parse(first_page_text) signature in order.
    No match -> fall back to the generic table parser so arbitrary
    real-world statements still work, but flag the layout as unrecognized.
    """
    try:
        with pdfplumber.open(file_path) as pdf:
            first_page_text = pdf.pages[0].extract_text() if pdf.pages else None
    except Exception as e:
        statement = ParsedStatement()
        statement.errors.append(PDFParseError(1, f"pdf_read_error: {str(e)}"))
        return statement

    if pdf_layout_a.can_parse(first_page_text or ""):
        return pdf_layout_a.parse_pdf(file_path)

    if pdf_layout_b.can_parse(first_page_text or ""):
        return pdf_layout_b.parse_pdf(file_path)

    statement = pdf_parser.parse_pdf(file_path)
    if (first_page_text or "").strip():
        # There was real text, just not a layout we recognize - distinct
        # from a scanned/image-only page, which already reports its own error.
        statement.errors.insert(0, PDFParseError(1, "unknown_layout"))
    return statement


def parse_statement(file_path: str, file_type: str) -> ParsedStatement:
    """Dispatch to the appropriate parser based on file type."""
    if file_type == "pdf":
        return parse_pdf_document(file_path)
    elif file_type == "csv":
        return structured_parser.parse_csv(file_path)
    elif file_type in ("xlsx", "xls"):
        return structured_parser.parse_excel(file_path)
    elif file_type == "json":
        return structured_parser.parse_json(file_path)
    elif file_type in ("png", "jpg", "jpeg"):
        from app.ingest.ocr_parser import parse_image
        return parse_image(file_path)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")
