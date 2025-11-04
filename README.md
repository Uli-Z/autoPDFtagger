# autoPDFtagger

## What It Is

autoPDFtagger is a CLI for semi‑automatic classification, sorting, and tagging of PDF documents. It enriches PDFs with standard metadata using OCR + AI (text and images) and is explicitly built to handle difficult inputs like low‑quality scans and image‑heavy files (e.g., presentations). Your archive remains plain files and folders (no lock‑in), with optional JSON export for review and integration.

## Key Features

- OCR (via Tesseract) + AI text analysis
- Vision analysis for embedded images and scans with page‑local context
- Smart image prioritization with a per‑PDF cap for predictable runtime/costs
- Writes standard PDF metadata and exports JSON/CSV (no proprietary DB)
- Multi‑provider via LiteLLM (tested with OpenAI; local LLMs are supported in principle, but current vision quality may vary)
- 24h on‑disk cache with cost spent/saved reporting

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
#   Edit models/API keys inside if you use cloud providers

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

### Image Analysis Strategy

- Not all images are analyzed to control time and cost; a configurable N limits analyses per PDF.
- First pages have higher priority. Afterwards, images on pages with little (OCR) text are favored.
- If a page has little text, OCR runs first so the vision model gets page‑local wording. Small icon clusters can be replaced by a page render; full‑page scans remain standalone.

### Caching & Costs

- 24h on‑disk cache for OCR and AI calls; default directory is `~/.autoPDFtagger/config`.
- Disable per run with `--no-cache`.
- The tool reports both spent and saved (cache) costs to keep runs predictable.

Note: We’re considering switching the default cache directory to `~/.autoPDFtagger/cache`. If you prefer that, you can already point `[CACHE].dir` there in your config.

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

## Future Development

- Cost control and monitoring improvements
- Optional UI and lightweight viewer app
- Expanded provider support and compatibility with tools like paperless‑ngx
- Tag organization and clustering on embeddings

## License

GPL-3
