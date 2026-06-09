from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
WINDOWS_SCRIPT_PATH = CURRENT_DIR / "chunking_windows.py"


def load_windows_module():
    module_name = "chunking_windows"
    spec = importlib.util.spec_from_file_location(module_name, WINDOWS_SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load helper module from: {WINDOWS_SCRIPT_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


windows_module = load_windows_module()
CHUNKS_DIR = windows_module.CHUNKS_DIR
SOURCE_METADATA_PATH = windows_module.SOURCE_METADATA_PATH
clean_markdown_text = windows_module.clean_markdown_text
ensure_directory = windows_module.ensure_directory
get_base_chunk_config = windows_module.get_base_chunk_config
load_source_metadata = windows_module.load_source_metadata
read_markdown = windows_module.read_markdown
validate_inputs = windows_module.validate_inputs
write_metadata_csv = windows_module.write_metadata_csv
write_windows_json = windows_module.write_windows_json


ROOT_DIR = Path(__file__).resolve().parents[1]
PARSED_PDF_DOCLING_LLM_DIR = ROOT_DIR / "data" / "parsed_pdf_docling_llm"
PARSED_WEB_DIR = ROOT_DIR / "data" / "parsed_web"
INPUT_DIRS = [PARSED_PDF_DOCLING_LLM_DIR, PARSED_WEB_DIR]
HEADER_JSON_PATH = CHUNKS_DIR / "chunks.json"
HEADER_METADATA_PATH = CHUNKS_DIR / "header_metadata.csv"
TEMP_MARKDOWN_DIR = CHUNKS_DIR / ".temp"

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chunk parsed markdown files by transformed header hierarchy."
    )
    parser.add_argument(
        "source_id",
        nargs="?",
        help="Optional source ID, markdown filename, or markdown path to process.",
    )
    return parser.parse_args()


def parse_line_record(line: str) -> dict[str, str | int]:
    match = HEADING_PATTERN.match(line)
    if not match:
        return {"kind": "text", "text": line}

    hashes, text = match.groups()
    return {
        "kind": "header",
        "level": len(hashes),
        "text": text.strip(),
    }


def build_line_records(markdown_text: str) -> list[dict[str, str | int]]:
    lines = [line.strip() for line in markdown_text.splitlines() if line.strip()]
    return [parse_line_record(line) for line in lines]


def list_markdown_files(parsed_dir: Path) -> list[Path]:
    return sorted(parsed_dir.glob("*.md"))


def resolve_markdown_path(source_arg: str, parsed_dirs: list[Path]) -> Path:
    candidate = Path(source_arg)

    if candidate.exists():
        return candidate.resolve()

    source_name = candidate.stem if candidate.suffix.lower() == ".md" else candidate.name
    matches = [parsed_dir / f"{source_name}.md" for parsed_dir in parsed_dirs]
    existing_matches = [match.resolve() for match in matches if match.exists()]

    if len(existing_matches) == 1:
        return existing_matches[0]

    if len(existing_matches) > 1:
        raise FileExistsError(
            f"Multiple markdown sources found for {source_arg}: "
            + ", ".join(str(match) for match in existing_matches)
        )

    raise FileNotFoundError(f"Markdown source not found: {source_arg}")


def select_markdown_files(source_arg: str | None, parsed_dirs: list[Path]) -> list[Path]:
    if source_arg:
        return [resolve_markdown_path(source_arg, parsed_dirs)]

    markdown_paths: list[Path] = []
    seen_source_ids: set[str] = set()

    for parsed_dir in parsed_dirs:
        for markdown_path in list_markdown_files(parsed_dir):
            source_id = markdown_path.stem
            if source_id in seen_source_ids:
                raise ValueError(f"Duplicate source ID across input directories: {source_id}")
            seen_source_ids.add(source_id)
            markdown_paths.append(markdown_path)

    return sorted(markdown_paths)


def is_header_record(record: dict[str, str | int]) -> bool:
    return record["kind"] == "header"


def format_record_line(record: dict[str, str | int]) -> str:
    if record["kind"] == "text":
        return str(record["text"])

    return f"{'#' * int(record['level'])} {record['text']}"


def build_transformed_markdown(records: list[dict[str, str | int]]) -> str:
    return "\n".join(format_record_line(record) for record in records)


def write_temp_markdown(output_path: Path, markdown_text: str) -> None:
    output_path.write_text(markdown_text, encoding="utf-8")


def build_chunk_id(source_id: str, counters: dict[int, int]) -> str:
    return (
        f"{source_id}_CHUNK_"
        f"{counters[1]}_{counters[2]}_{counters[3]}_{counters[4]}_{counters[5]}_{counters[6]}"
    )


def find_next_header_index(
    records: list[dict[str, str | int]],
    start_index: int,
) -> int | None:
    for index in range(start_index + 1, len(records)):
        if is_header_record(records[index]):
            return index

    return None


def build_breadcrumb(
    active_headers: dict[int, str],
    level: int,
) -> str:
    breadcrumb_parts = [
        active_headers[candidate_level]
        for candidate_level in range(1, level + 1)
        if active_headers[candidate_level]
    ]
    return " > ".join(breadcrumb_parts)


def reset_deeper_levels(counters: dict[int, int], active_headers: dict[int, str], level: int) -> None:
    for candidate_level in range(level + 1, 7):
        counters[candidate_level] = 0
        active_headers[candidate_level] = ""


def update_hierarchy_state(
    counters: dict[int, int],
    active_headers: dict[int, str],
    level: int,
    header_text: str,
) -> None:
    counters[level] += 1
    reset_deeper_levels(counters, active_headers, level)
    active_headers[level] = header_text


def build_chunk_text(breadcrumb: str, current_header: str, body_lines: list[str]) -> str:
    parts = [breadcrumb, current_header]

    if body_lines:
        parts.append("\n".join(body_lines))

    return "\n".join(parts).strip()


def chunk_by_headers(
    source_id: str,
    records: list[dict[str, str | int]],
) -> dict[str, str]:
    header_chunks: dict[str, str] = {}
    counters = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
    active_headers = {1: "", 2: "", 3: "", 4: "", 5: "", 6: ""}

    for index, record in enumerate(records):
        if not is_header_record(record):
            continue

        level = int(record["level"])
        header_line = format_record_line(record)
        header_text = str(record["text"])
        update_hierarchy_state(counters, active_headers, level, header_text)
        breadcrumb = build_breadcrumb(active_headers, level)
        next_header_index = find_next_header_index(records, index)
        end_index = next_header_index if next_header_index is not None else len(records)
        body_lines = [
            format_record_line(body_record)
            for body_record in records[index + 1 : end_index]
        ]
        chunk_id = build_chunk_id(source_id, counters)
        header_chunks[chunk_id] = build_chunk_text(breadcrumb, header_line, body_lines)

    return header_chunks


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


def build_metadata_rows(
    chunk_ids: list[str],
    metadata_row: dict[str, str],
) -> list[dict[str, str]]:
    chunk_size, overlap_size = get_base_chunk_config(metadata_row["format"])

    return [
        build_chunk_metadata_row(
            chunk_id=chunk_id,
            metadata_row=metadata_row,
            chunk_size=chunk_size,
            overlap_size=overlap_size,
        )
        for chunk_id in chunk_ids
    ]


def transform_markdown(markdown_text: str) -> list[dict[str, str | int]]:
    cleaned_markdown = clean_markdown_text(markdown_text)
    records = build_line_records(cleaned_markdown)
    return records


def process_markdown_file(
    markdown_path: Path,
    metadata_row: dict[str, str],
) -> tuple[str, dict[str, str], list[dict[str, str]]]:
    transformed_records = transform_markdown(read_markdown(markdown_path))
    transformed_markdown = build_transformed_markdown(transformed_records)
    chunks = chunk_by_headers(markdown_path.stem, transformed_records)
    metadata_rows = build_metadata_rows(list(chunks.keys()), metadata_row)
    return transformed_markdown, chunks, metadata_rows


def combine_chunk_outputs(
    markdown_paths: list[Path],
    metadata_by_source: dict[str, dict[str, str]],
) -> tuple[dict[str, str], list[dict[str, str]]]:
    header_chunks: dict[str, str] = {}
    metadata_rows: list[dict[str, str]] = []

    for markdown_path in markdown_paths:
        source_id = markdown_path.stem
        if source_id not in metadata_by_source:
            raise KeyError(f"Metadata not found for source: {source_id}")

        transformed_markdown, source_chunks, source_metadata_rows = process_markdown_file(
            markdown_path,
            metadata_by_source[source_id],
        )
        temp_output_path = TEMP_MARKDOWN_DIR / markdown_path.name
        write_temp_markdown(temp_output_path, transformed_markdown)
        header_chunks.update(source_chunks)
        metadata_rows.extend(source_metadata_rows)
        print(f"DONE  {markdown_path.name} -> {len(source_chunks)} chunks")

    return header_chunks, metadata_rows


def main() -> None:
    args = parse_args()
    for input_dir in INPUT_DIRS:
        validate_inputs(input_dir, SOURCE_METADATA_PATH)
    ensure_directory(CHUNKS_DIR)
    ensure_directory(TEMP_MARKDOWN_DIR)

    metadata_by_source = load_source_metadata(SOURCE_METADATA_PATH)
    markdown_paths = select_markdown_files(args.source_id, INPUT_DIRS)
    header_chunks, metadata_rows = combine_chunk_outputs(markdown_paths, metadata_by_source)

    write_windows_json(HEADER_JSON_PATH, header_chunks)
    write_metadata_csv(HEADER_METADATA_PATH, metadata_rows)
    print(
        f"Finished. Chunked {len(markdown_paths)} source files into {len(header_chunks)} header chunks."
    )


if __name__ == "__main__":
    main()
