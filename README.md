# Postpartum RAG

This project builds a retrieval corpus for postpartum patients.

## Data Ingestion

Source documents are listed in [data/raw_pdfs/postpartum_rag_sources_master_for_chunking.csv](/abs/path/c:/Users/Joy Anne/Desktop/Postpartum_RAG/data/raw_pdfs/postpartum_rag_sources_master_for_chunking.csv). Some sources are PDFs and some are webpages.

- PDFs are ingested with [src/pdf_ingestion_docling.py](/abs/path/c:/Users/Joy Anne/Desktop/Postpartum_RAG/src/pdf_ingestion_docling.py) into `data/parsed_pdf_docling/`.
- Their heading hierarchy is then corrected with [src/pdf_ingestion_llm_header.py](/abs/path/c:/Users/Joy Anne/Desktop/Postpartum_RAG/src/pdf_ingestion_llm_header.py) into `data/parsed_pdf_docling_llm/`.
- Webpages are ingested with [src/web_ingestion.py](/abs/path/c:/Users/Joy Anne/Desktop/Postpartum_RAG/src/web_ingestion.py) into `data/parsed_web/`.

After ingestion, the markdown files are manually reviewed for cleanup, such as removing references, acknowledgements, publication details, and other title-page or accessory content that does not help the knowledge base.

## Chunking

Once the markdown corpus is ready, [src/chunking_headers.py](/abs/path/c:/Users/Joy Anne/Desktop/Postpartum_RAG/src/chunking_headers.py) chunks the combined markdown set from:

- `data/parsed_pdf_docling_llm/`
- `data/parsed_web/`

Each chunk starts at a markdown heading and ends before the next heading. A breadcrumb prefix is added to each chunk to preserve header hierarchy context.

Outputs:

- Chunk text JSON: [data/chunks/chunks.json](/abs/path/c:/Users/Joy Anne/Desktop/Postpartum_RAG/data/chunks/chunks.json)
- Chunk metadata CSV: [data/chunks/header_metadata.csv](/abs/path/c:/Users/Joy Anne/Desktop/Postpartum_RAG/data/chunks/header_metadata.csv)

The metadata stores the chunk ID, source metadata, chunk length, and breadcrumb prefix.

## Environment

Copy values into `.env` using [.env.example](/abs/path/c:/Users/Joy Anne/Desktop/Postpartum_RAG/.env.example).
