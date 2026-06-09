from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from chunking_headers import (
    build_metadata_rows,
    build_transformed_markdown,
    chunk_by_headers,
    transform_markdown,
)


SAMPLE_MARKDOWN = """# Intro
Intro body.
## Setup
Setup body.
### Install
Install body.
#### Linux
Linux body.
##### Ubuntu
Ubuntu body.
###### Apt
Apt body.
## Troubleshooting
Troubleshooting body.
"""


def test_transform_markdown_preserves_original_heading_levels() -> None:
    records = transform_markdown(SAMPLE_MARKDOWN)

    assert build_transformed_markdown(records) == "\n".join(
        [
            "# Intro",
            "Intro body.",
            "## Setup",
            "Setup body.",
            "### Install",
            "Install body.",
            "#### Linux",
            "Linux body.",
            "##### Ubuntu",
            "Ubuntu body.",
            "###### Apt",
            "Apt body.",
            "## Troubleshooting",
            "Troubleshooting body.",
        ]
    )


def test_chunk_by_headers_uses_breadcrumb_prefixes_and_stops_before_next_header() -> None:
    records = transform_markdown(SAMPLE_MARKDOWN)
    chunks = chunk_by_headers("SRC001", records)

    assert chunks["SRC001_CHUNK_1_0_0_0_0_0"] == "\n".join(
        [
            "Intro",
            "# Intro",
            "Intro body.",
        ]
    )

    assert chunks["SRC001_CHUNK_1_1_0_0_0_0"] == "\n".join(
        [
            "Intro > Setup",
            "## Setup",
            "Setup body.",
        ]
    )

    assert chunks["SRC001_CHUNK_1_1_1_1_1_1"] == "\n".join(
        [
            "Intro > Setup > Install > Linux > Ubuntu > Apt",
            "###### Apt",
            "Apt body.",
        ]
    )

    assert chunks["SRC001_CHUNK_1_2_0_0_0_0"] == "\n".join(
        [
            "Intro > Troubleshooting",
            "## Troubleshooting",
            "Troubleshooting body.",
        ]
    )

    assert "## Setup" not in chunks["SRC001_CHUNK_1_0_0_0_0_0"]
    assert "###### Apt" not in chunks["SRC001_CHUNK_1_1_1_1_1_0"]


def test_chunk_by_headers_separates_immediate_child_headers_into_their_own_chunks() -> None:
    markdown = """# Parent
## Child
Child body.
"""
    records = transform_markdown(markdown)
    chunks = chunk_by_headers("SRC777", records)

    assert chunks["SRC777_CHUNK_1_0_0_0_0_0"] == "\n".join(
        [
            "Parent",
            "# Parent",
        ]
    )

    assert chunks["SRC777_CHUNK_1_1_0_0_0_0"] == "\n".join(
        [
            "Parent > Child",
            "## Child",
            "Child body.",
        ]
    )


def test_header_metadata_uses_chunk_length_and_breadcrumb() -> None:
    records = transform_markdown(SAMPLE_MARKDOWN)
    chunks = chunk_by_headers("SRC001", records)
    metadata_rows = build_metadata_rows(
        chunks,
        {
            "source_id": "SRC001",
            "source_title": "Sample Title",
            "organization": "Sample Org",
            "format": "guideline pdf",
            "year": "2024",
            "url": "https://example.com",
            "section": "Sample Section",
        },
    )

    first_row = metadata_rows[0]
    first_chunk = chunks["SRC001_CHUNK_1_0_0_0_0_0"]

    assert "chunk_size" not in first_row
    assert "overlap_size" not in first_row
    assert first_row["breadcrumb"] == "Intro"
    assert first_row["chunk_length"] == str(len(first_chunk))
