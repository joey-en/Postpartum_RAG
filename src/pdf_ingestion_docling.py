from __future__ import annotations

import tempfile
from pathlib import Path

from pdf_ingestion import (
    RAW_PDF_DIR,
    build_output_path,
    ensure_directory,
    parse_args,
    select_pdfs,
    split_processed_pdfs,
    validate_inputs,
    write_markdown,
)

r'''
python src\pdf_ingestion_docling.py OR src\pdf_ingestion_docling.py SRC001.pdf

scans data\raw_pdfs\*.pdf then writes parsed markdown to
data\parsed_pdf_docling\{same_name}.md. skips any PDF that already
has a matching `.md`
'''


ROOT_DIR = Path(__file__).resolve().parents[1]
PARSED_PDF_DOCLING_DIR = ROOT_DIR / "data" / "parsed_pdf_docling"
CHUNK_PAGE_COUNT = 30


def load_pdf_parser():
    try:
        from docling.document_converter import DocumentConverter
        from docling.document_converter import PdfFormatOption
        from docling_core.types.doc import ImageRefMode, PictureItem
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
        generate_picture_images=True,
        generate_table_images=False,
    )
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
            )
        }
    )

    def convert_pdf(pdf_path: str):
        return converter.convert(pdf_path)

    return convert_pdf, ImageRefMode, PictureItem


def get_pdf_page_count(pdf_path: Path) -> int:
    try:
        import pymupdf
    except ImportError as exc:
        message = (
            "pymupdf is not installed. "
            "Install it first with `pip install pymupdf`."
        )
        raise RuntimeError(message) from exc

    with pymupdf.open(pdf_path) as document:
        return document.page_count


def split_pdf_into_chunks(
    pdf_path: Path,
    chunk_page_count: int,
    temp_dir: Path,
) -> list[Path]:
    import pymupdf

    chunk_paths: list[Path] = []

    with pymupdf.open(pdf_path) as source_document:
        for start_page in range(0, source_document.page_count, chunk_page_count):
            end_page = min(start_page + chunk_page_count, source_document.page_count)
            chunk_path = temp_dir / (
                f"{pdf_path.stem}_pages_{start_page + 1:04d}_{end_page:04d}.pdf"
            )

            chunk_document = pymupdf.open()
            chunk_document.insert_pdf(
                source_document,
                from_page=start_page,
                to_page=end_page - 1,
            )
            chunk_document.save(chunk_path)
            chunk_document.close()
            chunk_paths.append(chunk_path)

    return chunk_paths


def save_picture_images(
    conversion_result,
    picture_item_class,
    image_dir: Path,
    start_index: int,
) -> int:
    picture_count = start_index
    image_dir.mkdir(parents=True, exist_ok=True)

    for element, _level in conversion_result.document.iterate_items():
        if not isinstance(element, picture_item_class):
            continue

        image = element.get_image(conversion_result.document)
        if image is None:
            continue

        picture_count += 1
        image_path = image_dir / f"picture-{picture_count:03d}.png"
        image.save(image_path, "PNG")

    return picture_count


def build_picture_reference_markdown(
    markdown_text: str,
    picture_count: int,
    image_reference_prefix: str,
) -> str:
    placeholder = "<!-- image -->"

    for picture_index in range(1, picture_count + 1):
        image_reference = (
            f"![Picture {picture_index}]"
            f"({image_reference_prefix}/picture-{picture_index:03d}.png)"
        )
        markdown_text = markdown_text.replace(placeholder, image_reference, 1)

    return markdown_text


def parse_pdf_to_markdown(
    pdf_path: Path,
    convert_pdf,
    image_ref_mode,
    picture_item_class,
) -> str:
    page_count = get_pdf_page_count(pdf_path)
    image_dir = PARSED_PDF_DOCLING_DIR / "images" / pdf_path.stem
    picture_count = 0
    image_reference_prefix = f"images/{pdf_path.stem}"

    if page_count <= CHUNK_PAGE_COUNT:
        result = convert_pdf(str(pdf_path))
        picture_count = save_picture_images(
            result,
            picture_item_class,
            image_dir,
            picture_count,
        )
        markdown = result.document.export_to_markdown(image_mode=image_ref_mode.PLACEHOLDER)
        return build_picture_reference_markdown(
            markdown,
            picture_count,
            image_reference_prefix,
        )

    markdown_parts: list[str] = []
    with tempfile.TemporaryDirectory(prefix="docling_pdf_chunks_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        chunk_paths = split_pdf_into_chunks(
            pdf_path=pdf_path,
            chunk_page_count=CHUNK_PAGE_COUNT,
            temp_dir=temp_dir,
        )

        for chunk_index, chunk_path in enumerate(chunk_paths, start=1):
            print(f"INFO  {pdf_path.name} chunk {chunk_index}/{len(chunk_paths)}")
            result = convert_pdf(str(chunk_path))
            picture_count = save_picture_images(
                result,
                picture_item_class,
                image_dir,
                picture_count,
            )
            markdown_parts.append(
                result.document.export_to_markdown(
                    image_mode=image_ref_mode.PLACEHOLDER,
                )
            )

    return build_picture_reference_markdown(
        "\n\n".join(markdown_parts),
        picture_count,
        image_reference_prefix,
    )


def process_pdf(
    pdf_path: Path,
    parsed_dir: Path,
    convert_pdf,
    image_ref_mode,
    picture_item_class,
) -> str:
    output_path = build_output_path(pdf_path, parsed_dir)

    if output_path.exists():
        return f"SKIP  {pdf_path.name} -> {output_path.name}"

    try:
        markdown = parse_pdf_to_markdown(
            pdf_path,
            convert_pdf,
            image_ref_mode,
            picture_item_class,
        )
    except Exception as exc:
        return f"FAIL  {pdf_path.name} -> {exc}"

    write_markdown(output_path, markdown)
    return f"DONE  {pdf_path.name} -> {output_path.name}"


def process_pdfs_one_by_one(
    pdf_paths: list[Path],
    parsed_dir: Path,
    convert_pdf,
    image_ref_mode,
    picture_item_class,
) -> tuple[int, int, int]:
    processed_count = 0
    skipped_count = 0
    failed_count = 0

    for pdf_path in pdf_paths:
        status = process_pdf(
            pdf_path,
            parsed_dir,
            convert_pdf,
            image_ref_mode,
            picture_item_class,
        )
        print(status)

        if status.startswith("DONE"):
            processed_count += 1
        elif status.startswith("SKIP"):
            skipped_count += 1
        else:
            failed_count += 1

    return processed_count, skipped_count, failed_count


def main() -> None:
    args = parse_args()
    validate_inputs(RAW_PDF_DIR)
    ensure_directory(PARSED_PDF_DOCLING_DIR)
    ensure_directory(PARSED_PDF_DOCLING_DIR / "images")

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

    convert_pdf, image_ref_mode, picture_item_class = load_pdf_parser()
    processed_count, pending_skipped_count, failed_count = process_pdfs_one_by_one(
        pdf_paths=pending_pdfs,
        parsed_dir=PARSED_PDF_DOCLING_DIR,
        convert_pdf=convert_pdf,
        image_ref_mode=image_ref_mode,
        picture_item_class=picture_item_class,
    )

    print(
        "Finished. "
        f"Processed: {processed_count}. "
        f"Skipped: {len(skipped_pdfs) + pending_skipped_count}. "
        f"Failed: {failed_count}."
    )


if __name__ == "__main__":
    main()
