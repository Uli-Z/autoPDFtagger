# autoPDFtagger

## What's New in 0.2 (2025)

- OCR integration via Tesseract to reliably handle low‑text/scan PDFs.
- LiteLLM integration to open up multiple APIs and local models (OpenAI tested).
- Parallelized job execution (OCR and AI) with a live status board and correct dependencies (images before text when both are enabled).
- Simplified image‑analysis prioritization: early pages first, prefer larger images/scans, group tiny icons, and cap analyses per PDF (configurable).
- 24h caching for OCR and AI calls with optional `--no-cache` and spent vs saved cost reporting.
- Systematic test integration: expanded unit and integration tests across OCR, LLM client, image selection, CLI, and pipeline.


## What It Is

autoPDFtagger is a CLI for semi‑automatic classification, sorting, and tagging of PDF documents. It enriches PDFs with standard metadata using OCR + AI (text and images) and is explicitly built to handle difficult inputs like low‑quality scans and image‑heavy files (e.g., presentations). Your archive remains plain files and folders (no lock‑in), with optional JSON export for review and integration.

## Key Features

- OCR (via Tesseract) + AI text analysis
- Vision analysis for embedded images and scans with page‑local context
- Smart image prioritization with a per‑PDF cap for predictable runtime/costs
- Writes standard PDF metadata and exports JSON/CSV (no proprietary DB)
- Detects title, summary, tags, creation date, and author/creator; can rename files based on detected metadata
- AI‑assisted tag normalization/unification across the database
- Multi‑provider via LiteLLM (tested with OpenAI; local LLMs are supported in principle, but current vision quality may vary)
- 24h on‑disk cache with cost spent/saved reporting
- Parallel job execution for OCR and AI with sensible dependencies (e.g., image → text when both are enabled)

## Quick Start

```bash
# 1) Install dependencies and the tool (editable)
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 2) Install Tesseract OCR (required for OCR)
#   Debian/Ubuntu:   sudo apt-get install tesseract-ocr tesseract-ocr-eng
#   macOS (brew):    brew install tesseract
#   Windows:         https://github.com/UB-Mannheim/tesseract/wiki

# 3) Create a config from the example
cp autoPDFtagger_example_config.conf ~/.autoPDFtagger.conf
#   Defaults use OpenAI models: short text = openai/gpt-5-mini, long text = openai/gpt-5-nano, images = openai/gpt-5-nano
#   Set OPENAI_API_KEY in your environment (or put a key into the config's OPENAI-API section)

# 4) Run on a folder and export
autoPDFtagger ./pdf_archive -ftic -e ./out --json all.json
```

## Requirements
- Python 3.9+
- Tesseract OCR installed (for OCR features)
- For cloud models: provider API key (e.g., `OPENAI_API_KEY`)

## Installation
```shell
pip install git+https://github.com/Uli-Z/autoPDFtagger
```

## Configuration
Place your config at `~/.autoPDFtagger.conf`. Use `autoPDFtagger_example_config.conf` as a starting point and adjust:
- `[AI]` models for text/image/tag tasks and `text_threshold_words`
- `[OCR]` language codes (e.g., `eng`, `deu+eng`) or disable
- `[CACHE]` settings (enabled, ttl, directory)

Default models (if values are missing) are:
- Short text: `openai/gpt-5-mini`
- Long text: `openai/gpt-5-nano`
- Images: `openai/gpt-5-nano`

### Image Analysis Strategy

- Not all images are analyzed to control time and cost; a configurable N limits analyses per PDF.
- First pages have higher priority. Afterwards, images on pages with little (OCR) text are favored.
- If a page has little text, OCR runs first so the vision model gets page‑local wording. Small icon clusters can be replaced by a page render; full‑page scans remain standalone.

### Caching & Costs

- 24h on‑disk cache for OCR and AI calls; default directory is `~/.autoPDFtagger/cache`.
- Disable per run with `--no-cache`.
- The tool reports both spent and saved (cache) costs to keep runs predictable.
### Confidence Logic

Results include per‑field confidences (0–10). An overall confidence index guides updates and filtering. By default, updates apply only when new results improve confidence; the index aggregates fields with extra weight on title and date.

### Tag Analysis

Suggests replacements to normalize and unify tags (synonyms, case, duplicates). You can export/import the database as CSV for quick, manual edits alongside JSON.

 

## CLI Examples

Analyze a folder, write JSON, and export PDFs with updated metadata:
```shell
autoPDFtagger ./pdf_archive -ftic -e ./new_archive --json allfiles.json
```

Run only AI text analysis on an existing JSON:
```shell
autoPDFtagger allfiles.json --ai-text-analysis --json textanalysis.json
```

Run AI image analysis for low‑quality entries and merge:
```shell
autoPDFtagger textanalysis.json --keep-below --ai-image-analysis --json imageanalysis.json
```

Normalize tags across the database with AI:
```shell
autoPDFtagger textanalysis.json imageanalysis.json --ai-tag-analysis --json final.json
```

## Export & Metadata

- The tool reads existing PDF metadata during analysis (title, subject/summary, author, keywords, creation date) and combines it with AI‑derived results.
- When metadata is missing, it attempts to infer creation date and author/creator from content and context (OCR/AI).
- Originals are never modified in place. Changes are applied only when exporting:
  - Files are copied to the chosen target folder (`-e/--export`).
  - Copies can be renamed using detected metadata (e.g., `YYYY‑MM‑DD_short-title.pdf`).
  - Standard PDF metadata is written into the copy: Title, Summary (Subject), Author/Creator, and Tags (Keywords). Creation date is set when known.
- You can still export JSON/CSV to audit or edit data before exporting PDFs.


## Usage
```shell
$ autoPDFtagger --help
usage: autoPDFtagger [-h] [--config-file CONFIG_FILE] [-b [BASE_DIRECTORY]] [-j [JSON]] [-s [CSV]] [-d {0,1,2}] [-f] [-t] [-i] [-c] [-e [EXPORT]] [-l]
                     [--keep-above [KEEP_ABOVE]] [--keep-below [KEEP_BELOW]] [--calc-stats]
                     [input_items ...]

Smart PDF-analyzing Tool

positional arguments:
  input_items           List of input PDFs and folders, alternativly you can use a JSON- or CSV-file

options:
  -h, --help            show this help message and exit
  --config-file CONFIG_FILE
                        Specify path to configuration file. Defaults to ~/.autoPDFtagger.conf
  -b [BASE_DIRECTORY], --base-directory [BASE_DIRECTORY]
                        Set base directory
  -j [JSON], --json [JSON]
                        Output JSON-Database to stdout. If filename provided, save it to file
  -s [CSV], --csv [CSV]
                        Output CSV-Database to specified file
  -d {0,1,2}, --debug {0,1,2}
                        Debug level (0: no debug, 1: basic debug, 2: detailed debug)
  -f, --file-analysis   Try to conventionally extract metadata from file, file name and folder structure
  -t, --ai-text-analysis
                        Do an AI text analysis
  -i, --ai-image-analysis
                        Do an AI image analysis
  -c, --ai-tag-analysis
                        Do an AI tag analysis
  -e [EXPORT], --export [EXPORT]
                        Copy Documents to a target folder
  -l, --list            List documents stored in database
  --keep-above [KEEP_ABOVE]
                        Before applying actions, filter out and retain only the documents with a confidence index greater than or equal to a specific       
                        value (default: 7).
  --keep-below [KEEP_BELOW]
                        Analogous to --keep-above. Retain only document with an index less than specified.
  --calc-stats          Calculate statistics and (roughly!) estimate costs for different analyses
  --ocr                 Enable OCR before AI text analysis (requires Tesseract)
  --no-ocr              Force-disable OCR regardless of configuration
  --ocr-languages OCR_LANGUAGES
                        Override Tesseract language codes (e.g. 'deu+eng')
```

## Privacy & Limits

- Data privacy: Cloud providers receive content for analysis. Use local models to keep data on your machine.
- Accuracy: Results are AI‑assisted; review before applying changes. Originals remain untouched unless exporting.
- Metadata: Changing metadata may affect digitally signed PDFs.

## Code Structure

- `main.py`: CLI entry point
- `autoPDFtagger.py`: Orchestrates analyses across the file list
- `ai_tasks.py`: Text/image/tag tasks and prompts
- `llm_client.py`: LiteLLM wrapper (chat/vision) + cost calculation
- `PDFDocument.py`: PDF operations + metadata
- `PDFList.py`: Collection/database with JSON/CSV import/export
- `config.py`: Configuration loader
- `autoPDFtagger_example_config.conf`: Example config

## Project Status
Functional CLI with solid results; ongoing improvements in testing, prompt optimization, error handling, and docs.

## Contributing
Contributions welcome — issues and PRs appreciated.

## License

GPL-3
