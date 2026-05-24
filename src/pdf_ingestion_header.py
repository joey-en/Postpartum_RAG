from __future__ import annotations

from pathlib import Path

from pdf_ingestion import (
    RAW_PDF_DIR,
    build_output_path,
    ensure_directory,
    parse_args,
    process_pdfs,
    select_pdfs,
    split_processed_pdfs,
    validate_inputs,
)


PARSED_PDF_NEW_HEADERS_DIR = Path(__file__).resolve().parents[1] / "data" / "parsed_pdf_new_headers"


def load_pdf_parser():
    try:
        import pymupdf
        import pymupdf4llm
    except ImportError as exc:
        message = (
            "pymupdf and pymupdf4llm are required. "
            "Run `pip install -r requirements.txt` first."
        )
        raise RuntimeError(message) from exc

    pymupdf4llm.use_layout(False)

    def to_markdown_with_headers(pdf_path: str) -> str:
        with pymupdf.open(pdf_path) as document:
            if document.get_toc():
                headers = pymupdf4llm.TocHeaders(document)
            else:
                headers = pymupdf4llm.IdentifyHeaders(document, max_levels=5)

            return pymupdf4llm.to_markdown(document, hdr_info=headers)

    return to_markdown_with_headers


def main() -> None:
    args = parse_args()
    validate_inputs(RAW_PDF_DIR)
    ensure_directory(PARSED_PDF_NEW_HEADERS_DIR)

    pdf_paths = select_pdfs(args.pdf_path, RAW_PDF_DIR)
    pending_pdfs, skipped_pdfs = split_processed_pdfs(
        pdf_paths,
        PARSED_PDF_NEW_HEADERS_DIR,
    )

    for pdf_path in skipped_pdfs:
        output_path = build_output_path(pdf_path, PARSED_PDF_NEW_HEADERS_DIR)
        print(f"SKIP  {pdf_path.name} -> {output_path.name}")

    if not pending_pdfs:
        print(f"Finished. Processed: 0. Skipped: {len(skipped_pdfs)}.")
        return

    to_markdown = load_pdf_parser()
    processed_count, pending_skipped_count = process_pdfs(
        pdf_paths=pending_pdfs,
        parsed_dir=PARSED_PDF_NEW_HEADERS_DIR,
        to_markdown=to_markdown,
    )

    print(
        "Finished. "
        f"Processed: {processed_count}. "
        f"Skipped: {len(skipped_pdfs) + pending_skipped_count}."
    )


if __name__ == "__main__":
    main()
