from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
PARSED_PDF_DIR = ROOT_DIR / "data" / "parsed_pdf"
SOURCE_METADATA_PATH = (
    ROOT_DIR / "data" / "raw_pdfs" / "postpartum_rag_sources_master_for_chunking.csv"
)
CHUNKS_DIR = ROOT_DIR / "data" / "chunks"
WINDOWS_JSON_PATH = CHUNKS_DIR / "windows.json"
WINDOWS_METADATA_PATH = CHUNKS_DIR / "windows_metadata.csv"

GUIDELINE_CHUNK_SIZE = 650
GUIDELINE_OVERLAP = 100
PATIENT_EDUCATION_CHUNK_SIZE = 475
PATIENT_EDUCATION_OVERLAP = 80
WEBPAGE_CHUNK_SIZE = 375
WEBPAGE_OVERLAP = 65
SAFETY_CHUNK_SIZE = 200
SAFETY_OVERLAP = 50
MIN_SECTION_WORDS = 60

HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+")
MARKDOWN_DECORATION_PATTERN = re.compile(r"[*_`]+")
WHITESPACE_PATTERN = re.compile(r"\s+")
SAFETY_KEYWORDS = (
    "warning sign",
    "warning signs",
    "red flag",
    "red flags",
    "danger sign",
    "danger signs",
    "seek medical",
    "seek urgent",
    "seek emergency",
    "go to the emergency",
    "go to hospital",
    "call your doctor",
    "call the doctor",
    "call your healthcare",
    "contact your doctor",
    "contact your healthcare",
    "contact a healthcare professional",
    "urgent medical attention",
    "medical emergency",
    "emergency help",
    "when to seek",
    "when to call",
    "when should i call",
    "when should you call",
    "when to contact",
    "dangerous symptoms",
    "symptoms and signs of illness",
    "heavy bleeding",
    "postpartum psychosis",
    "chest pain",
    "shortness of breath",
    "thoughts of harming",
    "thought of harming",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chunk parsed markdown files into retrieval windows."
    )
    parser.add_argument(
        "source_id",
        nargs="?",
        help="Optional source ID, markdown filename, or markdown path to process.",
    )
    return parser.parse_args()


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_source_metadata(csv_path: Path) -> dict[str, dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        return {
            row["source_id"].strip(): normalize_metadata_row(row)
            for row in reader
            if row.get("source_id")
        }


def normalize_metadata_row(row: dict[str, str]) -> dict[str, str]:
    return {key: (value or "").strip() for key, value in row.items()}


def list_markdown_files(parsed_dir: Path) -> list[Path]:
    return sorted(parsed_dir.glob("*.md"))


def resolve_markdown_path(source_arg: str, parsed_dir: Path) -> Path:
    candidate = Path(source_arg)

    if candidate.exists():
        return candidate.resolve()

    source_name = candidate.stem if candidate.suffix.lower() == ".md" else candidate.name
    parsed_candidate = parsed_dir / f"{source_name}.md"
    if parsed_candidate.exists():
        return parsed_candidate.resolve()

    raise FileNotFoundError(f"Markdown source not found: {source_arg}")


def select_markdown_files(source_arg: str | None, parsed_dir: Path) -> list[Path]:
    if source_arg:
        return [resolve_markdown_path(source_arg, parsed_dir)]

    return list_markdown_files(parsed_dir)


def read_markdown(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def clean_markdown_text(text: str) -> str:
    cleaned_lines: list[str] = []

    for line in text.splitlines():
        stripped_line = line.strip()
        if not stripped_line:
            cleaned_lines.append("")
            continue

        if "intentionally omitted" in stripped_line.lower():
            continue

        cleaned_lines.append(stripped_line)

    return "\n".join(cleaned_lines).strip()


def split_markdown_sections(markdown_text: str) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in markdown_text.splitlines():
        if is_heading_line(line):
            next_heading = clean_heading_text(line)

            if current_heading and not current_lines:
                current_heading = f"{current_heading}\n{next_heading}".strip()
                continue

            if current_heading or current_lines:
                sections.append(
                    build_section_record(current_heading, "\n".join(current_lines))
                )
            current_heading = next_heading
            current_lines = []
            continue

        current_lines.append(line)

    if current_heading or current_lines:
        sections.append(build_section_record(current_heading, "\n".join(current_lines)))

    non_empty_sections = [section for section in sections if section["text"]]
    return merge_small_sections(non_empty_sections, MIN_SECTION_WORDS)


def is_heading_line(line: str) -> bool:
    return bool(HEADING_PATTERN.match(line))


def build_section_record(heading: str, body: str) -> dict[str, str]:
    normalized_heading = normalize_text_block(heading)
    normalized_body = normalize_text_block(body)
    section_text = build_section_text(normalized_heading, normalized_body)

    return {
        "heading": normalized_heading,
        "text": section_text,
    }


def clean_heading_text(line: str) -> str:
    without_hashes = HEADING_PATTERN.sub("", line.strip())
    return MARKDOWN_DECORATION_PATTERN.sub("", without_hashes).strip()


def normalize_text_block(text: str) -> str:
    lines = [WHITESPACE_PATTERN.sub(" ", line).strip() for line in text.splitlines()]
    non_empty_lines = [line for line in lines if line]
    return "\n".join(non_empty_lines)


def build_section_text(heading: str, body: str) -> str:
    if heading and body:
        return f"{heading}\n{body}"
    return heading or body


def merge_small_sections(
    sections: list[dict[str, str]],
    min_words: int,
) -> list[dict[str, str]]:
    if not sections:
        return []

    merged_sections: list[dict[str, str]] = []
    pending_section = sections[0]

    for section in sections[1:]:
        if count_words(pending_section["text"]) < min_words:
            pending_section = combine_sections(pending_section, section)
            continue

        merged_sections.append(pending_section)
        pending_section = section

    merged_sections.append(pending_section)
    return merged_sections


def combine_sections(
    first_section: dict[str, str],
    second_section: dict[str, str],
) -> dict[str, str]:
    heading = "\n".join(
        value for value in [first_section["heading"], second_section["heading"]] if value
    )
    text = "\n".join(
        value for value in [first_section["text"], second_section["text"]] if value
    )
    return {
        "heading": heading,
        "text": text,
    }


def count_words(text: str) -> int:
    return len(text.split())


def get_base_chunk_config(format_value: str) -> tuple[int, int]:
    normalized_format = format_value.lower()

    if "guideline pdf" in normalized_format:
        return GUIDELINE_CHUNK_SIZE, GUIDELINE_OVERLAP

    if normalized_format == "patient education pdf":
        return PATIENT_EDUCATION_CHUNK_SIZE, PATIENT_EDUCATION_OVERLAP

    return WEBPAGE_CHUNK_SIZE, WEBPAGE_OVERLAP


def is_safety_section(section: dict[str, str]) -> bool:
    search_text = f"{section['heading']}\n{section['text']}".lower()
    return any(keyword in search_text for keyword in SAFETY_KEYWORDS)


def get_chunk_config(format_value: str, section: dict[str, str]) -> tuple[int, int]:
    if is_safety_section(section):
        return SAFETY_CHUNK_SIZE, SAFETY_OVERLAP

    return get_base_chunk_config(format_value)


def chunk_text(text: str, chunk_size: int, overlap_size: int) -> list[str]:
    words = text.split()
    if not words:
        return []

    if overlap_size >= chunk_size:
        raise ValueError("Overlap size must be smaller than chunk size.")

    if len(words) <= chunk_size:
        return [" ".join(words)]

    step = chunk_size - overlap_size
    chunks: list[str] = []

    for start_index in range(0, len(words), step):
        end_index = start_index + chunk_size
        chunk_words = words[start_index:end_index]
        if not chunk_words:
            continue
        chunks.append(" ".join(chunk_words))
        if end_index >= len(words):
            break

    return chunks


def build_chunk_id(source_id: str, chunk_number: int) -> str:
    return f"{source_id}_CHUNK_{chunk_number:03d}"


def chunk_source_document(
    markdown_path: Path,
    metadata_row: dict[str, str],
) -> tuple[dict[str, str], list[dict[str, str]]]:
    source_id = markdown_path.stem
    markdown_text = clean_markdown_text(read_markdown(markdown_path))
    sections = split_markdown_sections(markdown_text)
    windows: dict[str, str] = {}
    metadata_rows: list[dict[str, str]] = []
    chunk_number = 1

    for section in sections:
        chunk_size, overlap_size = get_chunk_config(metadata_row["format"], section)
        chunks = chunk_text(section["text"], chunk_size, overlap_size)

        for chunk_text_value in chunks:
            chunk_id = build_chunk_id(source_id, chunk_number)
            windows[chunk_id] = chunk_text_value
            metadata_rows.append(
                build_chunk_metadata_row(
                    chunk_id=chunk_id,
                    metadata_row=metadata_row,
                    chunk_size=chunk_size,
                    overlap_size=overlap_size,
                )
            )
            chunk_number += 1

    return windows, metadata_rows


def build_chunk_metadata_row(
    chunk_id: str,
    metadata_row: dict[str, str],
    chunk_size: int,
    overlap_size: int,
) -> dict[str, str]:
    return {
        "chunk_id": chunk_id,
        "source_id": metadata_row["source_id"],
        "source_title": metadata_row["source_title"],
        "organization": metadata_row["organization"],
        "format": metadata_row["format"],
        "year": metadata_row["year"],
        "url": metadata_row["url"],
        "section": metadata_row["section"],
        "chunk_size": str(chunk_size),
        "overlap_size": str(overlap_size),
    }


def combine_chunk_outputs(
    markdown_paths: list[Path],
    metadata_by_source: dict[str, dict[str, str]],
) -> tuple[dict[str, str], list[dict[str, str]]]:
    windows: dict[str, str] = {}
    metadata_rows: list[dict[str, str]] = []

    for markdown_path in markdown_paths:
        source_id = markdown_path.stem
        if source_id not in metadata_by_source:
            raise KeyError(f"Metadata not found for source: {source_id}")

        source_windows, source_metadata_rows = chunk_source_document(
            markdown_path,
            metadata_by_source[source_id],
        )
        windows.update(source_windows)
        metadata_rows.extend(source_metadata_rows)
        print(f"DONE  {markdown_path.name} -> {len(source_windows)} chunks")

    return windows, metadata_rows


def write_windows_json(output_path: Path, windows: dict[str, str]) -> None:
    with output_path.open("w", encoding="utf-8") as json_file:
        json.dump(windows, json_file, ensure_ascii=False, indent=2)


def write_metadata_csv(
    output_path: Path,
    metadata_rows: list[dict[str, str]],
) -> None:
    fieldnames = [
        "chunk_id",
        "source_id",
        "source_title",
        "organization",
        "format",
        "year",
        "url",
        "section",
        "chunk_size",
        "overlap_size",
    ]

    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(metadata_rows)


def validate_inputs(parsed_dir: Path, metadata_path: Path) -> None:
    if not parsed_dir.exists():
        raise FileNotFoundError(f"Parsed PDF directory not found: {parsed_dir}")

    if not metadata_path.exists():
        raise FileNotFoundError(f"Source metadata CSV not found: {metadata_path}")


def main() -> None:
    args = parse_args()
    validate_inputs(PARSED_PDF_DIR, SOURCE_METADATA_PATH)
    ensure_directory(CHUNKS_DIR)

    metadata_by_source = load_source_metadata(SOURCE_METADATA_PATH)
    markdown_paths = select_markdown_files(args.source_id, PARSED_PDF_DIR)
    windows, metadata_rows = combine_chunk_outputs(markdown_paths, metadata_by_source)

    write_windows_json(WINDOWS_JSON_PATH, windows)
    write_metadata_csv(WINDOWS_METADATA_PATH, metadata_rows)
    print(
        f"Finished. Chunked {len(markdown_paths)} source files into {len(windows)} windows."
    )


if __name__ == "__main__":
    main()
