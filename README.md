# Postpartum RAG

This project builds a retrieval corpus for postpartum patients.

## Data Ingestion

Source documents are listed in [data/raw_pdfs/postpartum_rag_sources_master_for_chunking.csv](data/raw_pdfs/postpartum_rag_sources_master_for_chunking.csv). Some sources are PDFs and some are webpages. The goal of the ingestion pipeline is to turn those sources into clean markdown that can be reviewed, chunked, and later used in retrieval for postpartum support content.

### PDF Sources

- PDFs are ingested with [src/pdf_ingestion_docling.py](src/pdf_ingestion_docling.py) into `data/parsed_pdf_docling/`.
- Docling is used as the main PDF parser because it is the active PDF ingestion path in this repo and works well for structured documents such as guidelines and table-heavy content.
- Docling also saves extracted images into `data/parsed_pdf_docling/images/{source_id}/`, and the generated markdown references those saved images in order.

### Header Correction

- After PDF ingestion, the heading hierarchy is corrected with [src/pdf_ingestion_llm_header.py](src/pdf_ingestion_llm_header.py).
- This step reads markdown from `data/parsed_pdf_docling/` and writes corrected markdown to `data/parsed_pdf_docling_llm/`.
- The purpose of this step is to enforce a better heading structure so downstream chunks have more reliable document hierarchy.

### Web Sources

- Webpages are ingested with [src/web_ingestion.py](src/web_ingestion.py) into `data/parsed_web/`.
- These sources are converted directly into markdown so they can join the same review and chunking flow as the PDF-derived content.

After ingestion, the markdown files are manually reviewed for cleanup, such as removing references, acknowledgements, publication details, and other title-page or accessory content that does not help the knowledge base.

This manual review step is intentional. The project keeps the parser output, but it also expects editorial cleanup when a source includes noise that would weaken retrieval quality.

## Chunking

Once the markdown corpus is ready, [src/chunking_headers.py](src/chunking_headers.py) chunks the combined markdown set from:

- `data/parsed_pdf_docling_llm/`
- `data/parsed_web/`

Each chunk starts at a markdown heading and ends before the next heading. The chunker does not flatten the document into arbitrary windows first. Instead, it uses the markdown hierarchy directly so that each chunk remains aligned to a meaningful section boundary.

A breadcrumb prefix is added to each chunk to preserve header hierarchy context. In practice, that means a chunk begins with a text prefix derived from the active header path, followed by the actual markdown header for that section and the section body. This makes it easier to preserve document context during retrieval without having to reconstruct hierarchy later.

The chunker also writes metadata per chunk, including the original source information, the breadcrumb prefix, and the chunk length in characters.

Outputs:

- Chunk text JSON: [data/chunks/chunks.json](data/chunks/chunks.json)
- Chunk metadata CSV: [data/chunks/header_metadata.csv](data/chunks/header_metadata.csv)

The metadata stores the chunk ID, source metadata, chunk length, and breadcrumb prefix.

## Active Scripts

The active pipeline scripts in `src/` are:

- [src/pdf_ingestion_docling.py](src/pdf_ingestion_docling.py)
- [src/pdf_ingestion_llm_header.py](src/pdf_ingestion_llm_header.py)
- [src/pdf_ingestion_marker.py](src/pdf_ingestion_marker.py)
- [src/web_ingestion.py](src/web_ingestion.py)
- [src/chunking_headers.py](src/chunking_headers.py)

Some older helper modules were removed and their needed logic was folded into the active scripts so the current pipeline is easier to follow and maintain.

## Environment

Copy values into `.env` using [.env.example](.env.example).

The LLM header-correction step expects Azure OpenAI configuration in `.env`. The example file shows the required keys used by the script.
