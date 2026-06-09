from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from openai import AzureOpenAI


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_PATH = ROOT_DIR / "data" / "parsed_pdf_docling" / "SRC001.md"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "data" / "parsed_pdf_docling_llm" / "SRC001.md"
DEFAULT_INPUT_DIR = ROOT_DIR / "data" / "parsed_pdf"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "parsed_pdf_llm"
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")
BATCH_SIZE = 100
CONTEXT_SIZE = 12


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rewrite markdown heading levels with help from an Azure OpenAI model."
    )
    parser.add_argument(
        "--input",
        dest="input_path",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Source markdown file.",
    )
    parser.add_argument(
        "--output",
        dest="output_path",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Destination markdown file.",
    )
    parser.add_argument(
        "--input-dir",
        dest="input_dir",
        type=Path,
        help="Optional source directory of markdown files.",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        type=Path,
        help="Optional destination directory for processed markdown files.",
    )
    return parser.parse_args()


def build_client() -> tuple[AzureOpenAI, str]:
    load_dotenv()

    endpoint = os.getenv("GPT_ENDPOINT")
    deployment = os.getenv("GPT_DEPLOYMENT")
    api_key = os.getenv("GPT_KEY")
    api_version = os.getenv("GPT_VERSION")

    missing = [
        name
        for name, value in {
            "GPT_ENDPOINT": endpoint,
            "GPT_DEPLOYMENT": deployment,
            "GPT_KEY": api_key,
            "GPT_VERSION": api_version,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    client = AzureOpenAI(
        api_version=api_version,
        azure_endpoint=endpoint,
        api_key=api_key,
    )
    return client, deployment


def read_markdown(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def extract_headings(lines: list[str]) -> tuple[list[int], list[str]]:
    indexes: list[int] = []
    headings: list[str] = []

    for index, line in enumerate(lines):
        if HEADING_PATTERN.match(line):
            indexes.append(index)
            headings.append(line)

    if not headings:
        raise RuntimeError("No markdown headings were found in the input file.")

    return indexes, headings


def build_prompt(
    headings: list[str],
    prior_context: list[str],
    following_context: list[str],
) -> str:
    formatted_batch = []
    for index, heading in enumerate(headings, start=1):
        match = HEADING_PATTERN.match(heading)
        if match is None:
            raise RuntimeError(f"Invalid heading in batch: {heading}")
        current_level = len(match.group(1))
        text = match.group(2).strip()
        formatted_batch.append(f"{index}\t{current_level}\t{text}")

    sections = [
        "These lines are headers from a Markdown document. The heading hierarchy is wrong.",
        "Fix only the heading levels.",
        "For each current-batch line, return exactly one line formatted as: index<TAB>new_level.",
        "Use only levels 1 through 6.",
        "Return the same number of lines as the current batch.",
        "Return only the index and new level values, with no commentary or code fences.",
        (
            "Determine each new level by comparing it to the nearby headers around it. "
            "Pay close attention to local runs of neighboring headers, section transitions, "
            "and repeated or split titles that should sit at the same level."
        ),
        (
            "Use the surrounding context to infer relative nesting. "
            "Do not flatten everything to one level unless the nearby structure clearly supports that."
        ),
    ]

    if prior_context:
        sections.append(
            "Previous corrected headings are included below only as hierarchy context. "
            "Do not return them."
        )
        sections.append("Previous corrected headings as level<TAB>text:")
        sections.append("\n".join(prior_context))

    sections.append("Current batch as index<TAB>current_level<TAB>text:")
    sections.append("\n".join(formatted_batch))

    if following_context:
        sections.append(
            "Upcoming original headings are included below only as forward context. "
            "Use them to judge the nearby structure, but do not return them."
        )
        sections.append("Upcoming headings as current_level<TAB>text:")
        sections.append("\n".join(following_context))

    return "\n\n".join(sections)


def request_fixed_headings(
    client: AzureOpenAI,
    deployment: str,
    headings: list[str],
) -> list[str]:
    fixed_headings: list[str] = []

    for batch_start in range(0, len(headings), BATCH_SIZE):
        batch = headings[batch_start : batch_start + BATCH_SIZE]
        prior_context = format_prior_context(fixed_headings[-CONTEXT_SIZE:])
        following_context = format_prior_context(
            headings[batch_start + len(batch) : batch_start + len(batch) + CONTEXT_SIZE]
        )
        batch_result = request_fixed_heading_batch(
            client=client,
            deployment=deployment,
            headings=batch,
            prior_context=prior_context,
            following_context=following_context,
        )
        fixed_headings.extend(batch_result)
        print(
            f"Processed heading batch {batch_start + 1}-"
            f"{batch_start + len(batch_result)} of {len(headings)}"
        )

    return fixed_headings


def format_prior_context(headings: list[str]) -> list[str]:
    formatted: list[str] = []
    for heading in headings:
        match = HEADING_PATTERN.match(heading)
        if match is None:
            continue
        formatted.append(f"{len(match.group(1))}\t{match.group(2).strip()}")
    return formatted


def request_fixed_heading_batch(
    client: AzureOpenAI,
    deployment: str,
    headings: list[str],
    prior_context: list[str],
    following_context: list[str],
) -> list[str]:
    response = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": (
                    "You fix Markdown heading hierarchies. "
                    "You must preserve heading text exactly and change only heading levels."
                ),
            },
            {
                "role": "user",
                "content": build_prompt(headings, prior_context, following_context),
            },
        ],
        max_tokens=2500,
        temperature=0.0,
        top_p=1.0,
        model=deployment,
    )

    content = response.choices[0].message.content or ""
    fixed_headings = parse_level_response(headings, content)
    return fixed_headings


def parse_level_response(original_headings: list[str], content: str) -> list[str]:
    response_lines = [line.strip() for line in content.splitlines() if line.strip()]

    if len(response_lines) != len(original_headings):
        raise RuntimeError(
            f"LLM returned {len(response_lines)} headings, expected {len(original_headings)}."
        )

    fixed_headings: list[str] = []
    for expected_index, (original, response_line) in enumerate(zip(original_headings, response_lines), start=1):
        parts = response_line.split("\t")
        if len(parts) != 2:
            raise RuntimeError(f"Invalid response line format: {response_line}")

        returned_index, level_text = parts
        if returned_index.strip() != str(expected_index):
            raise RuntimeError(
                f"Unexpected heading index {returned_index}; expected {expected_index}."
            )

        try:
            level = int(level_text)
        except ValueError as exc:
            raise RuntimeError(f"Invalid heading level: {level_text}") from exc

        if level < 1 or level > 6:
            raise RuntimeError(f"Heading level out of range: {level}")

        original_match = HEADING_PATTERN.match(original)
        if original_match is None:
            raise RuntimeError(f"Invalid original heading: {original}")

        fixed_headings.append(f"{'#' * level} {original_match.group(2).strip()}")

    return fixed_headings


def replace_headings(lines: list[str], heading_indexes: list[int], fixed_headings: list[str]) -> list[str]:
    updated_lines = list(lines)
    for index, heading in zip(heading_indexes, fixed_headings):
        updated_lines[index] = heading
    return updated_lines


def write_output(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def process_markdown_file(
    client: AzureOpenAI,
    deployment: str,
    input_path: Path,
    output_path: Path,
) -> None:
    lines = read_markdown(input_path)
    heading_indexes, headings = extract_headings(lines)
    fixed_headings = request_fixed_headings(client, deployment, headings)
    updated_lines = replace_headings(lines, heading_indexes, fixed_headings)
    write_output(output_path, updated_lines)
    print(
        f"Wrote {len(fixed_headings)} corrected headings from {input_path.name} "
        f"to {output_path}"
    )


def select_markdown_files(input_dir: Path) -> list[Path]:
    markdown_paths = sorted(input_dir.glob("*.md"))
    if not markdown_paths:
        raise RuntimeError(f"No markdown files found in {input_dir}")
    return markdown_paths


def main() -> None:
    args = parse_args()
    client, deployment = build_client()

    if args.input_dir or args.output_dir:
        input_dir = args.input_dir or DEFAULT_INPUT_DIR
        output_dir = args.output_dir or DEFAULT_OUTPUT_DIR
        markdown_paths = select_markdown_files(input_dir)

        for input_path in markdown_paths:
            output_path = output_dir / input_path.name
            process_markdown_file(client, deployment, input_path, output_path)

        print(
            f"Finished. Processed {len(markdown_paths)} markdown files from "
            f"{input_dir} to {output_dir}."
        )
        return

    process_markdown_file(
        client=client,
        deployment=deployment,
        input_path=args.input_path,
        output_path=args.output_path,
    )


if __name__ == "__main__":
    main()
