# autoPDFtagger

## What It Is

autoPDFtagger is a CLI that enriches PDFs with standard metadata using OCR + AI (text and images). It keeps your archive as plain files and folders (no lock‑in) and can export JSON for easy review and integration.

## Key Features

- OCR + AI text analysis with per‑document model selection
- Vision analysis for embedded images and scans with page‑local context
- Smart image prioritization with a per‑PDF cap for predictable runtime/costs
- Writes standard PDF metadata and exports JSON (no proprietary DB)
- Multi‑provider via LiteLLM (OpenAI, Gemini, local Ollama)
- 24h on‑disk cache with cost spent/saved reporting

## Quick Start

```bash
# 1) Install (editable for local dev)
python -m venv .venv && source .venv/bin/activate && pip install -e .

# 2) Create a config from the example
cp autoPDFtagger_example_config.conf ~/.autoPDFtagger.conf
# Edit models/API keys inside if you use cloud providers

# 3) Run on a folder and export
autoPDFtagger ./pdf_archive -ftic -e ./out --json all.json
```

## Requirements
- Python 3.9+
- For cloud models: provider API key (e.g., `OPENAI_API_KEY`)
- For local models: Ollama with the chosen model pulled (e.g., `ollama pull llava`)

## Installation
```shell
pip install git+https://github.com/Uli-Z/autoPDFtagger
```

## Configuration
Minimal configuration lives at `~/.autoPDFtagger.conf` (see `autoPDFtagger_example_config.conf`).

Create the file and adjust models/keys as needed:
```ini
; Configuration for autoPDFtagger

[DEFAULT]
language = English

[AI]
; Choose explicit models per task (via LiteLLM routing)
text_model_short = openai/gpt-4o
text_model_long = openai/gpt-4o-mini
text_threshold_words = 100
image_model = openai/gpt-4o   ; or gemini/gemini-1.5-pro or ollama/llava
tag_model = openai/gpt-4o-mini
image_temperature = 0.8

[OCR]
enabled = auto
languages = eng

[OPENAI-API]
; Optional fallback if OPENAI_API_KEY is not set
; API-Key = sk-...
```

### Image Analysis Strategy

- If a page has little text, OCR runs first so the vision model sees page‑local wording.
- Embedded images and full‑page scans are prioritized; clusters of tiny icons can be replaced with a page render.
- Only the top‑N images per PDF are analyzed (configurable) to keep runtime and cost predictable.

### Caching & Costs

- 24h on‑disk cache for OCR and AI calls; default dir `~/.autoPDFtagger/config`.
- Disable per run with `--no-cache`.
- Logs show per‑call usage, and cache hits include `saved_cost`; totals for spent/saved are aggregated per run.

### Local Models (Ollama)

You can run fully local without any cloud keys by using Ollama through LiteLLM.

- Install Ollama and pull models:
  - `curl -fsSL https://ollama.com/install.sh | sh`
  - Vision (images): `ollama pull llava`
  - Text: `ollama pull llama3:8b` (or another text model)
- Ensure the Ollama service is running (`ollama serve` on first start; then it runs as a daemon).
- Configure models in `~/.autoPDFtagger.conf`:
  ```ini
  [AI]
  text_model_short = ollama/llama3:8b
  text_model_long  = ollama/llama3:8b
  image_model      = ollama/llava
  tag_model        = ollama/llama3:8b
  ```
- No API keys required; data stays on your machine. Default Ollama endpoint is `http://localhost:11434`.
- Quick test: `autoPDFtagger ./pdf_archive -ftic -e ./out --json all.json`

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
