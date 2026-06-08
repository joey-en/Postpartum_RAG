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

r'''
python src\pdf_ingestion_docling.py OR src\pdf_ingestion_docling.py SRC001.pdf

scans data\raw_pdfs\*.pdf then writes parsed markdown to
data\parsed_pdf_docling\{same_name}.md. skips any PDF that already
has a matching `.md`
'''


ROOT_DIR = Path(__file__).resolve().parents[1]
PARSED_PDF_DOCLING_DIR = ROOT_DIR / "data" / "parsed_pdf_docling"


def load_pdf_parser():
    try:
        from docling.document_converter import DocumentConverter
        from docling.document_converter import PdfFormatOption
        from docling.datamodel.accelerator_options import AcceleratorOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
    except ImportError as exc:
        message = (
            "docling is not installed. "
            "Install it first with `pip install docling`."
        )
        raise RuntimeError(message) from exc

    pipeline_options = PdfPipelineOptions(
        accelerator_options=AcceleratorOptions(
            num_threads=1,
            device="cpu",
        ),
        do_ocr=False,
        force_backend_text=True,
        layout_batch_size=1,
        table_batch_size=1,
        ocr_batch_size=1,
        generate_page_images=False,
        generate_picture_images=False,
        generate_table_images=False,
    )
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
            )
        }
    )

    def to_markdown(pdf_path: str) -> str:
        result = converter.convert(pdf_path)
        return result.document.export_to_markdown()

    return to_markdown


def main() -> None:
    args = parse_args()
    validate_inputs(RAW_PDF_DIR)
    ensure_directory(PARSED_PDF_DOCLING_DIR)

    pdf_paths = select_pdfs(args.pdf_path, RAW_PDF_DIR)
    pending_pdfs, skipped_pdfs = split_processed_pdfs(
        pdf_paths,
        PARSED_PDF_DOCLING_DIR,
    )

    for pdf_path in skipped_pdfs:
        output_path = build_output_path(pdf_path, PARSED_PDF_DOCLING_DIR)
        print(f"SKIP  {pdf_path.name} -> {output_path.name}")

    if not pending_pdfs:
        print(f"Finished. Processed: 0. Skipped: {len(skipped_pdfs)}.")
        return

    to_markdown = load_pdf_parser()
    processed_count, pending_skipped_count = process_pdfs(
        pdf_paths=pending_pdfs,
        parsed_dir=PARSED_PDF_DOCLING_DIR,
        to_markdown=to_markdown,
    )

    print(
        "Finished. "
        f"Processed: {processed_count}. "
        f"Skipped: {len(skipped_pdfs) + pending_skipped_count}."
    )


if __name__ == "__main__":
    main()
