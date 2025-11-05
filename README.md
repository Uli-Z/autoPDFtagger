# autoPDFtagger

## What's New in 0.3 (2025)

 - Simpler usage: `-i` now also analyzes the relevant page text. Using `-t` together with `-i` is no longer necessary. Existing `-ti` calls still work (redundant).
 - Faster and cheaper runs: fewer model requests and a smoother live status board.
- Predictable per‑file token limit via `[AI].token_limit` (default 1,000,000). If the limit is reached, the tool trims lower‑value context first and may skip low‑signal images; INFO logs indicate when this happens.
- No config changes required: current setups continue to work. Tip: adjust `[AI].token_limit` to trade quality vs. speed/cost.

Includes improvements from 0.2:
- OCR (Tesseract) for scan/low‑text PDFs.
- LiteLLM multi‑provider support (OpenAI tested).
- Parallel job execution with a live status board.
- 24h caching with optional `--no-cache` and cost reporting.

## What It Is

autoPDFtagger is a CLI for semi‑automatic classification, sorting, and tagging of PDF documents. It enriches PDFs with standard metadata using OCR + AI (text and images) and is explicitly built to handle difficult inputs like low‑quality scans and image‑heavy files (e.g., presentations). Your archive remains plain files and folders (no lock‑in), with optional JSON export for review and integration.

## Inputs & Outputs at a Glance

autoPDFtagger is a file database transformer. It accepts inputs either from stdin or as command‑line arguments, and it produces outputs in the same formats. This symmetry makes it easy to chain runs and keep your archive reproducible.

- Inputs
  - PDFs or folders of PDFs: the tool scans files and interprets their existing metadata and content (with OCR when needed).
  - JSON or CSV database: an existing description of your PDF collection (as exported by this tool). You can mix PDFs and database files in one invocation.
- Outputs
  - JSON or CSV database: a structured view of your archive with enriched metadata (title, summary, creator, creation date, tags, confidences).
  - Files: optional export to a target directory (e.g., renamed by detected title/creator).
- Behavior selection
  - CLI options control which analyses and actions run (e.g., `-t` for text, `-i` for image, `-c` for tags, `-e` for export). Image analysis already includes page text; `-ti` is redundant.

### Confidence protects good metadata

To avoid overwriting high‑quality metadata with worse guesses, the tool uses per‑field confidences (0–10). Updates apply only when the new confidence is not lower than the existing one.

- If you want to lock a field permanently, set its confidence to 10. The tool will not overwrite it.
- The overall confidence index (shown in summaries) reflects multiple fields, with extra weight on title and date, and can be used to filter items before exporting.

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

- pipx (empfohlen, systemweit ohne venv-Gefrickel):
  - `python3 -m pip install --user pipx && python3 -m pipx ensurepath`
  - `pipx install git+https://github.com/Uli-Z/autoPDFtagger`
  - Aktualisieren: `pipx reinstall git+https://github.com/Uli-Z/autoPDFtagger`

- Benutzerweit mit pip (ohne Admin-Rechte):
  - `python3 -m pip install --user git+https://github.com/Uli-Z/autoPDFtagger`
  - Stelle sicher, dass `~/.local/bin` im `PATH` ist (Bash/Zsh):
    - `echo 'export PATH=$HOME/.local/bin:$PATH' >> ~/.bashrc && source ~/.bashrc`

- Systemweit (Admin):
  - `sudo -H python3 -m pip install git+https://github.com/Uli-Z/autoPDFtagger`

- Verifikation nach Installation:
  - `autoPDFtagger --help`
  - Optional: `which autoPDFtagger`

## Configuration
Place your config at `~/.autoPDFtagger.conf`. Use `autoPDFtagger_example_config.conf` as a starting point and adjust:
- `[AI]` models for text/image/tag tasks and `text_threshold_words`
- `[OCR]` language codes (e.g., `eng`, `deu+eng`) or disable
- `[CACHE]` settings (enabled, ttl, directory)
- `[EXPORT]` filename format using strftime + `{TITLE}`/`{CREATOR}` placeholders

Default models (if values are missing) are:
- Short text: `openai/gpt-5-mini`
- Long text: `openai/gpt-5-nano`
- Images: `openai/gpt-5-nano`

### Token Limit Per File

Both text and image analysis share a single per-file input token limit:
- Configure `[AI].token_limit` (default 1,000,000).
- If a text prompt would exceed the limit, only the user content is trimmed proportionally; the system instructions stay intact. An INFO log is emitted when trimming occurs or when the intro alone exceeds the limit (request aborted).
- For image analysis, see below for how trimming/skipping works with page texts and images under the same limit.

### Image Analysis Strategy

Image analysis (`-i`) interleaves page text and images in a single request to the vision model. You do not need `-t` together with `-i` — `-i` already includes page texts.

- Reading order preserved: for each page, the prompt includes the page’s text followed by selected images from that page.
- Token budget aware: uses the shared `[AI].token_limit` (default 1,000,000 input tokens). If the page texts exceed the limit, the tool proportionally trims page texts (intro/system stays intact) and logs an INFO when trimming occurs. Images are then added until the remaining budget is exhausted. INFO logs also appear when some images are skipped due to the budget.
- Image selection priorities:
  - First pages first (`image_priority_first_pages`, default 3)
  - Then by size (larger area first)
  - Ignore tiny icons below a minimum edge (`image_small_image_min_edge_cm`, default 3.0 cm)
  - If a page has many small images (≥ `image_page_group_threshold`), render the full page instead of each region.
- Adaptive fallback: if no image fits the budget, the tool downscales the best candidate (page or region) to fit at least one 512×512 tile (≈255 tokens). INFO logs explain the decision.
- Visual debug: `--visual-debug out.pdf` writes a PDF illustrating the exact sequence of parts (text/image) and performs a dry‑run (no API request). Useful to verify ordering and selected images.

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
# Note: -i already includes text; -ti is redundant.
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
  - Copies can be renamed using detected metadata. The filename pattern is configurable via `[EXPORT].filename_format` (e.g., `%Y-%m-%d-{TITLE}.pdf` or `%Y%m%d-{CREATOR}-{TITLE}.pdf`).
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
