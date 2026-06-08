from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from bs4 import NavigableString
from bs4 import Tag

from pdf_ingestion import ensure_directory, write_markdown

r'''
python src\web_ingestion.py OR python src\web_ingestion.py SRC014

scans data\raw_pdfs\postpartum_rag_sources_master_for_chunking.csv for rows
with access_type exactly "Official page", fetches each page, and writes parsed
markdown to data\parsed_web\{source_id}.md. skips any row that already has a
matching `.md`
'''


ROOT_DIR = Path(__file__).resolve().parents[1]
SOURCES_CSV_PATH = (
    ROOT_DIR / "data" / "raw_pdfs" / "postpartum_rag_sources_master_for_chunking.csv"
)
PARSED_WEB_DIR = ROOT_DIR / "data" / "parsed_web"
OFFICIAL_PAGE_ACCESS_TYPE = "Official page"
REQUEST_TIMEOUT_SECONDS = 30
MIN_MARKDOWN_LENGTH = 500
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)
REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
HEADING_LEVELS = {
    "h1": "#",
    "h2": "##",
    "h3": "###",
    "h4": "####",
    "h5": "#####",
    "h6": "######",
}
BLOCK_TAGS = {
    "article",
    "blockquote",
    "div",
    "main",
    "p",
    "section",
}
LIST_TAGS = {"ul", "ol"}
IGNORED_TAGS = {
    "aside",
    "button",
    "figure",
    "figcaption",
    "footer",
    "header",
    "iframe",
    "input",
    "label",
    "nav",
    "noscript",
    "script",
    "style",
    "svg",
}
NOISE_HINTS = (
    "alert",
    "breadcrumb",
    "cookie",
    "consent",
    "dialog",
    "drawer",
    "modal",
    "newsletter",
    "overlay",
    "popup",
    "promo",
    "search",
    "share",
    "signup",
    "social",
    "subscribe",
    "toolbar",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse official webpage sources into Markdown files."
    )
    parser.add_argument(
        "source_id",
        nargs="?",
        help="Optional source_id for a single webpage to process.",
    )
    return parser.parse_args()


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def get_tag_hints(tag: Tag) -> str:
    attrs = getattr(tag, "attrs", None)
    if not isinstance(attrs, dict):
        return ""

    values: list[str] = []

    tag_id = attrs.get("id")
    if isinstance(tag_id, str):
        values.append(tag_id)

    class_names = attrs.get("class", [])
    if isinstance(class_names, list):
        values.extend(name for name in class_names if isinstance(name, str))

    role_value = attrs.get("role")
    if isinstance(role_value, str):
        values.append(role_value)

    aria_label = attrs.get("aria-label")
    if isinstance(aria_label, str):
        values.append(aria_label)

    return " ".join(values).lower()


def get_tag_hint_tokens(tag: Tag) -> set[str]:
    hints = get_tag_hints(tag)
    return {
        token
        for token in re.split(r"[^a-z0-9]+", hints)
        if token
    }


def is_noise_tag(tag: Tag) -> bool:
    if tag.name is None:
        return False

    if tag.name in IGNORED_TAGS:
        return True

    hint_tokens = get_tag_hint_tokens(tag)
    return any(hint in hint_tokens for hint in NOISE_HINTS)


def remove_noise_tags(soup: BeautifulSoup) -> None:
    tags_to_remove = [tag for tag in soup.find_all(True) if is_noise_tag(tag)]

    for tag in tags_to_remove:
        if getattr(tag, "attrs", None) is not None:
            tag.decompose()


def select_main_content_container(soup: BeautifulSoup) -> Tag:
    preferred_candidates = [
        soup.find("main"),
        soup.find("article"),
        soup.find(attrs={"role": "main"}),
    ]
    valid_preferred = [
        candidate
        for candidate in preferred_candidates
        if isinstance(candidate, Tag)
    ]
    if valid_preferred:
        return max(valid_preferred, key=score_content_container)

    if not isinstance(soup.body, Tag):
        raise ValueError("No HTML body content found.")

    scored_candidates = [soup.body]
    scored_candidates.extend(
        tag
        for tag in soup.body.find_all(["div", "section", "article", "main"])
        if isinstance(tag, Tag)
    )

    scored_entries = [
        (
            score_content_container(tag),
            len(clean_text(tag.get_text(" ", strip=True))),
            get_tag_depth(tag),
            tag,
        )
        for tag in scored_candidates
    ]
    best_score = max(entry[0] for entry in scored_entries)
    close_candidates = [
        entry
        for entry in scored_entries
        if entry[0] >= best_score - 150
    ]
    close_candidates.sort(key=lambda entry: (entry[1], -entry[2]))
    return close_candidates[0][3]


def get_tag_depth(tag: Tag) -> int:
    depth = 0
    parent = tag.parent

    while isinstance(parent, Tag):
        depth += 1
        parent = parent.parent

    return depth


def score_content_container(tag: Tag) -> int:
    text = clean_text(tag.get_text(" ", strip=True))
    text_length = len(text)
    heading_count = len(tag.find_all(list(HEADING_LEVELS)))
    paragraph_count = len(tag.find_all("p"))
    list_item_count = len(tag.find_all("li"))
    table_count = len(tag.find_all("table"))
    links = tag.find_all("a")
    link_count = len(links)
    link_text_length = sum(
        len(clean_text(link.get_text(" ", strip=True)))
        for link in links
    )
    form_count = len(tag.find_all("form"))
    hints = get_tag_hints(tag)

    score = text_length
    score += heading_count * 150
    score += paragraph_count * 220
    score += list_item_count * 25
    score += table_count * 80
    score -= link_count * 40
    score -= link_text_length * 2
    score -= form_count * 100

    if text_length > 0 and link_count >= 12:
        link_text_ratio = link_text_length / text_length
        if link_text_ratio >= 0.30:
            score -= 1200

    if any(hint in hints for hint in ("nav", "menu", "breadcrumb", "share", "social")):
        score -= 1000

    if "content" in hints or "article" in hints or "main" in hints:
        score += 300

    if "side" in hints:
        score -= 500

    return score


def clean_text(text: str) -> str:
    text = normalize_whitespace(text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text


def markdown_escape(text: str) -> str:
    return text.replace("\\", "\\\\")


def convert_link(tag: Tag) -> str:
    text = clean_text(tag.get_text(" ", strip=True))
    href = tag.get("href")

    if not text:
        return ""

    if not isinstance(href, str) or not href.strip():
        return markdown_escape(text)

    absolute_href = urljoin(tag.base_url or "", href.strip())
    return f"[{markdown_escape(text)}]({absolute_href})"


def render_inline(node) -> str:
    if isinstance(node, NavigableString):
        return clean_text(str(node))

    if not isinstance(node, Tag):
        return ""

    if node.name == "a":
        return convert_link(node)

    if node.name == "br":
        return "\n"

    text_parts = [render_inline(child) for child in node.children]
    text = " ".join(part for part in text_parts if part)
    return clean_text(text)


def render_table_cell(cell: Tag) -> str:
    return clean_text(render_inline(cell))


def render_table(table: Tag) -> str:
    rows: list[list[str]] = []

    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        row = [render_table_cell(cell) for cell in cells]
        if any(row):
            rows.append(row)

    if not rows:
        return ""

    column_count = max(len(row) for row in rows)
    normalized_rows = [
        row + [""] * (column_count - len(row))
        for row in rows
    ]

    header = normalized_rows[0]
    separator = ["---"] * column_count
    body_rows = normalized_rows[1:]

    markdown_lines = [
        f"| {' | '.join(header)} |",
        f"| {' | '.join(separator)} |",
    ]

    for row in body_rows:
        markdown_lines.append(f"| {' | '.join(row)} |")

    return "\n".join(markdown_lines)


def render_list(list_tag: Tag, depth: int = 0) -> list[str]:
    lines: list[str] = []

    for index, item in enumerate(list_tag.find_all("li", recursive=False), start=1):
        marker = f"{index}." if list_tag.name == "ol" else "-"
        indent = "  " * depth
        item_parts: list[str] = []

        for child in item.contents:
            if isinstance(child, Tag) and child.name in LIST_TAGS:
                continue

            rendered = render_inline(child)
            if rendered:
                item_parts.append(rendered)

        item_text = clean_text(" ".join(item_parts))
        if item_text:
            lines.append(f"{indent}{marker} {item_text}")

        for nested_list in item.find_all(LIST_TAGS, recursive=False):
            lines.extend(render_list(nested_list, depth + 1))

    return lines


def render_block(tag: Tag) -> str:
    if tag.name in HEADING_LEVELS:
        text = clean_text(tag.get_text(" ", strip=True))
        if text:
            return f"{HEADING_LEVELS[tag.name]} {text}"
        return ""

    if tag.name == "table":
        return render_table(tag)

    if tag.name in LIST_TAGS:
        return "\n".join(render_list(tag))

    if tag.name == "blockquote":
        text = clean_text(tag.get_text(" ", strip=True))
        if text:
            return f"> {text}"
        return ""

    if tag.name == "p":
        return render_inline(tag)

    if tag.name in BLOCK_TAGS:
        text = clean_text(tag.get_text(" ", strip=True))
        return text

    return ""


def tag_has_meaningful_text(tag: Tag) -> bool:
    return bool(clean_text(tag.get_text(" ", strip=True)))


def extract_markdown_from_container(container: Tag) -> str:
    blocks: list[str] = []
    seen_block_ids: set[int] = set()

    for tag in container.find_all(
        list(HEADING_LEVELS) + ["table", "ul", "ol", "blockquote", "p"]
    ):
        parent = tag.parent
        while isinstance(parent, Tag) and parent is not container:
            if parent.name in LIST_TAGS and tag.name == "li":
                break
            if parent.name in {"table", "blockquote", "p"}:
                parent = None
                break
            parent = parent.parent

        if parent is None:
            continue

        tag_id = id(tag)
        if tag_id in seen_block_ids:
            continue

        if not tag_has_meaningful_text(tag):
            continue

        block = render_block(tag)
        if block:
            blocks.append(block)
            seen_block_ids.add(tag_id)

    if not blocks:
        fallback_text = clean_text(container.get_text("\n", strip=True))
        if fallback_text:
            blocks.append(fallback_text)

    deduped_blocks: list[str] = []
    for block in blocks:
        if not deduped_blocks or deduped_blocks[-1] != block:
            deduped_blocks.append(block)

    return "\n\n".join(deduped_blocks).strip()


def fetch_html(url: str) -> str:
    response = requests.get(
        url,
        headers=REQUEST_HEADERS,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def convert_html_to_markdown(html: str, url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    remove_noise_tags(soup)

    for tag in soup.find_all("a"):
        tag.base_url = url

    container = select_main_content_container(soup)
    page_title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    content_markdown = extract_markdown_from_container(container)

    if not content_markdown:
        raise ValueError("No readable content extracted from page.")

    if page_title:
        return f"# {page_title}\n\n{content_markdown}".strip()

    return content_markdown


def load_official_page_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        rows = [
            row
            for row in reader
            if row.get("access_type") == OFFICIAL_PAGE_ACCESS_TYPE
        ]

    return sorted(rows, key=lambda row: row["source_id"])


def select_source_rows(
    source_id_arg: str | None,
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    if source_id_arg is None:
        return rows

    normalized_source_id = source_id_arg.strip().upper()
    matching_rows = [
        row
        for row in rows
        if row["source_id"].strip().upper() == normalized_source_id
    ]

    if not matching_rows:
        raise FileNotFoundError(f"Official page source_id not found: {source_id_arg}")

    return matching_rows


def build_output_path_from_source_id(source_id: str, parsed_dir: Path) -> Path:
    return parsed_dir / f"{source_id}.md"


def has_usable_markdown(output_path: Path) -> bool:
    if not output_path.exists():
        return False

    markdown = output_path.read_text(encoding="utf-8")
    return len(markdown.strip()) >= MIN_MARKDOWN_LENGTH


def split_processed_rows(
    rows: list[dict[str, str]],
    parsed_dir: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    pending_rows: list[dict[str, str]] = []
    skipped_rows: list[dict[str, str]] = []

    for row in rows:
        output_path = build_output_path_from_source_id(row["source_id"], parsed_dir)
        if has_usable_markdown(output_path):
            skipped_rows.append(row)
        else:
            pending_rows.append(row)

    return pending_rows, skipped_rows


def process_row(row: dict[str, str], parsed_dir: Path) -> str:
    source_id = row["source_id"]
    output_path = build_output_path_from_source_id(source_id, parsed_dir)

    if has_usable_markdown(output_path):
        return f"SKIP  {source_id} -> {output_path.name}"

    try:
        html = fetch_html(row["url"])
        markdown = convert_html_to_markdown(html, row["url"])
    except Exception as exc:
        return f"FAIL  {source_id} -> {exc}"

    if len(markdown.strip()) < MIN_MARKDOWN_LENGTH:
        return f"FAIL  {source_id} -> Extracted markdown too short"

    write_markdown(output_path, markdown)
    return f"DONE  {source_id} -> {output_path.name}"


def process_rows(
    rows: list[dict[str, str]],
    parsed_dir: Path,
) -> tuple[int, int, int]:
    processed_count = 0
    skipped_count = 0
    failed_count = 0

    for row in rows:
        status = process_row(row, parsed_dir)
        print(status)

        if status.startswith("DONE"):
            processed_count += 1
        elif status.startswith("SKIP"):
            skipped_count += 1
        else:
            failed_count += 1

    return processed_count, skipped_count, failed_count


def validate_inputs(csv_path: Path) -> None:
    if not csv_path.exists():
        raise FileNotFoundError(f"Sources CSV not found: {csv_path}")


def main() -> None:
    args = parse_args()
    validate_inputs(SOURCES_CSV_PATH)
    ensure_directory(PARSED_WEB_DIR)

    all_rows = load_official_page_rows(SOURCES_CSV_PATH)
    selected_rows = select_source_rows(args.source_id, all_rows)
    pending_rows, skipped_rows = split_processed_rows(
        selected_rows,
        PARSED_WEB_DIR,
    )

    for row in skipped_rows:
        output_path = build_output_path_from_source_id(
            row["source_id"],
            PARSED_WEB_DIR,
        )
        print(f"SKIP  {row['source_id']} -> {output_path.name}")

    if not pending_rows:
        print(f"Finished. Processed: 0. Skipped: {len(skipped_rows)}. Failed: 0.")
        return

    processed_count, pending_skipped_count, failed_count = process_rows(
        pending_rows,
        PARSED_WEB_DIR,
    )

    print(
        "Finished. "
        f"Processed: {processed_count}. "
        f"Skipped: {len(skipped_rows) + pending_skipped_count}. "
        f"Failed: {failed_count}."
    )


if __name__ == "__main__":
    main()
