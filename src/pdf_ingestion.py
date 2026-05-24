from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

'''
python src\pdf_ingestion.py OR src\pdf_ingestion.py SRC001.pdf

scans data\raw_pdfs\*.pdf then writes parsed markdown to 
data\parsed_pdf\{same_name}.md. skips any PDF that already 
has a matching `.md`
'''


ROOT_DIR = Path(__file__).resolve().parents[1]
RAW_PDF_DIR = ROOT_DIR / "data" / "raw_pdfs"
PARSED_PDF_DIR = ROOT_DIR / "data" / "parsed_pdf"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse raw PDFs into Markdown files."
    )
    parser.add_argument(
        "pdf_path",
        nargs="?",
        help="Optional path or filename for a single PDF to process.",
    )
    return parser.parse_args()


def load_pdf_parser():
    try:
        import pymupdf4llm
    except ImportError as exc:
        message = (
            "pymupdf4llm is not installed. "
            "Run `pip install -r requirements.txt` first."
        )
        raise RuntimeError(message) from exc

    return pymupdf4llm.to_markdown


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def list_raw_pdfs(raw_dir: Path) -> list[Path]:
    return sorted(raw_dir.glob("*.pdf"))


def build_output_path(pdf_path: Path, parsed_dir: Path) -> Path:
    return parsed_dir / f"{pdf_path.stem}.md"


def is_processed(pdf_path: Path, parsed_dir: Path) -> bool:
    return build_output_path(pdf_path, parsed_dir).exists()


def resolve_pdf_path(pdf_input: str, raw_dir: Path) -> Path:
    candidate = Path(pdf_input)

    if candidate.exists():
        return candidate.resolve()

    raw_candidate = raw_dir / candidate.name
    if raw_candidate.exists():
        return raw_candidate.resolve()

    if candidate.suffix.lower() != ".pdf":
        named_candidate = raw_dir / f"{candidate.name}.pdf"
        if named_candidate.exists():
            return named_candidate.resolve()

    raise FileNotFoundError(f"PDF not found: {pdf_input}")


def select_pdfs(pdf_arg: str | None, raw_dir: Path) -> list[Path]:
    if pdf_arg:
        return [resolve_pdf_path(pdf_arg, raw_dir)]

    return list_raw_pdfs(raw_dir)


def split_processed_pdfs(
    pdf_paths: Iterable[Path],
    parsed_dir: Path,
) -> tuple[list[Path], list[Path]]:
    pending_pdfs: list[Path] = []
    skipped_pdfs: list[Path] = []

    for pdf_path in pdf_paths:
        if is_processed(pdf_path, parsed_dir):
            skipped_pdfs.append(pdf_path)
        else:
            pending_pdfs.append(pdf_path)

    return pending_pdfs, skipped_pdfs


def parse_pdf_to_markdown(pdf_path: Path, to_markdown) -> str:
    return to_markdown(str(pdf_path))


def write_markdown(output_path: Path, markdown: str) -> None:
    output_path.write_text(markdown, encoding="utf-8")


def process_pdf(pdf_path: Path, parsed_dir: Path, to_markdown) -> str:
    output_path = build_output_path(pdf_path, parsed_dir)

    if output_path.exists():
        return f"SKIP  {pdf_path.name} -> {output_path.name}"

    markdown = parse_pdf_to_markdown(pdf_path, to_markdown)
    write_markdown(output_path, markdown)
    return f"DONE  {pdf_path.name} -> {output_path.name}"


def process_pdfs(
    pdf_paths: Iterable[Path],
    parsed_dir: Path,
    to_markdown,
) -> tuple[int, int]:
    processed_count = 0
    skipped_count = 0

    for pdf_path in pdf_paths:
        status = process_pdf(pdf_path, parsed_dir, to_markdown)
        print(status)

        if status.startswith("DONE"):
            processed_count += 1
        else:
            skipped_count += 1

    return processed_count, skipped_count


def validate_inputs(raw_dir: Path) -> None:
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw PDF directory not found: {raw_dir}")


def main() -> None:
    args = parse_args()
    validate_inputs(RAW_PDF_DIR)
    ensure_directory(PARSED_PDF_DIR)

    pdf_paths = select_pdfs(args.pdf_path, RAW_PDF_DIR)
    pending_pdfs, skipped_pdfs = split_processed_pdfs(
        pdf_paths,
        PARSED_PDF_DIR,
    )

    for pdf_path in skipped_pdfs:
        output_path = build_output_path(pdf_path, PARSED_PDF_DIR)
        print(f"SKIP  {pdf_path.name} -> {output_path.name}")

    if not pending_pdfs:
        print(f"Finished. Processed: 0. Skipped: {len(skipped_pdfs)}.")
        return

    to_markdown = load_pdf_parser()
    processed_count, pending_skipped_count = process_pdfs(
        pdf_paths=pending_pdfs,
        parsed_dir=PARSED_PDF_DIR,
        to_markdown=to_markdown,
    )

    print(
        "Finished. "
        f"Processed: {processed_count}. "
        f"Skipped: {len(skipped_pdfs) + pending_skipped_count}."
    )


if __name__ == "__main__":
    main()
