# autoPDFtagger

## Overview

autoPDFtagger is a small CLI that makes plain old folders work like a searchable archive. It is not a document management system. The tool uses AI to extract and index text from scanned PDFs and to propose clean, consistent filenames and standard PDF metadata. With good indexing and naming, you can find files via any file browser or OS search — no proprietary database, no lock‑in. Because it writes standard PDF metadata and exports JSON, it stays compatible with any DMS you already use or may adopt later. Ideal for personal archives and small offices that want longevity and minimal maintenance.

## Key Concepts

- **AI-Powered Tagging**: Uses LLMs to automatically enrich PDFs (text + images), including complex drawings and low-quality scans.
- **Multi‑provider + Local LLMs**: Works with OpenAI out of the box and, via LiteLLM, also supports Gemini and local models through Ollama.
- **Focus**: Engineered for paperless home-office setups, prioritizing precise data analysis over complex UI.
- **No DMS/Vendor Lock‑in**: Works directly on the filesystem with plain files and standard PDF metadata; AI improves indexing and naming so files are discoverable via any file browser/OS search and remain compatible with any DMS.
- **Requirements**: Python environment and either a provider API key (e.g., OpenAI) or a local Ollama setup.
- **Functionalities**:
  - Robust text analysis powered by GPT.
  - Advanced image analysis utilizing GPT-Vision.
  - Operates on the filesystem using existing folder structures, filenames, and standard PDF metadata (no proprietary archive).
  - Exports JSON for piping/integration and writes standard PDF metadata; no proprietary database.
  - Standardizes file naming (YY-mm-dd-{TITLE}.pdf) and updates PDF metadata for efficient indexing.
  - Configurable to integrate other AI agents.
  - Future enhancements to refine folder organization.

## Cost Optimization

autoPDFtagger is designed to reduce AI costs by extracting as much information as possible without calling an LLM, and by minimizing the amount of data sent when an LLM call is necessary.

- Pre‑AI extraction (no cost):
  - File name and folder path analysis to detect creation date, title and tags. See `PDFDocument.analyze_file()` and helpers like `extract_date_from_filename()`, `extract_title_from_filename()`, and `extract_tags_from_relative_path()` in `autoPDFtagger/PDFDocument.py`.
  - Existing PDF metadata is read and reused when present. See `extract_metadata()` in `autoPDFtagger/PDFDocument.py`.

- Targeted analysis (only when requested):
  - The CLI only performs text/image/tag analysis if you pass `-t`, `-i`, or `-c` respectively. If a model key is left empty under `[AI]`, that analysis is skipped entirely.
  - You can pre‑filter which documents are analyzed using `--keep-above/--keep-below` to focus on items that need improvement.

- Model selection for cost/quality trade‑off:
  - Text analysis uses explicit short/long models and a configurable threshold (`[AI] text_model_short`, `text_model_long`, `text_threshold_words`) to route short texts to higher‑quality models and longer texts to lower‑cost models. See `analyze_text()` in `autoPDFtagger/ai_tasks.py`.
  - Tag analysis can use a lighter model (e.g., `openai/gpt-4o-mini`).

- Minimal image usage for vision:
  - Non‑scanned PDFs: only the largest images are selected (up to three) across the document, prioritizing content‑rich images. Scanned PDFs: only the largest image per page from the first pages is used. See `_select_images_for_analysis()` and `analyze_images()` in `autoPDFtagger/ai_tasks.py`.
  - This limits tokens and images sent to the model while still capturing the most informative visual context.

- Skips and safeguards:
  - If a model is not configured for a task, the task is skipped with a clear log line (no accidental spending). See `ai_tasks.analyze_text/images/tags`.
  - Cost is tracked from API usage and summed per phase; see logs after each analysis. Or use `--calc-stats` to estimate costs up front.

- Local models (zero cloud cost):
  - You can route to local Ollama models (e.g., `ollama/llava`) via LiteLLM to avoid cloud costs entirely. See the example config.

Future optimizations (ideas): caching previous results to skip re‑analysis of unchanged documents, chunked text processing for very large PDFs, and optional iterative vision passes that stop as soon as confidence is sufficient.

## OCR Integration

- autoPDFtagger checks for a local Tesseract binary on startup. If found (or explicitly enabled with `--ocr`), pages without a text layer are OCR'd before the AI text analysis runs.
- Configure defaults in `[OCR]` within `~/.autoPDFtagger.conf` (`enabled = auto|true|false`, `languages = deu+eng`, etc.). CLI flags `--ocr`, `--no-ocr`, and `--ocr-languages` override these settings per invocation.
- When OCR is disabled (config/CLI or missing binary), the existing behaviour remains unchanged; PDFs that already contain text skip the OCR step automatically.

## Concept and Context

- Problem: Many documents arrive as scans or mixed‑quality PDFs. Plain OCR often misses context (drawings, photos), and ad‑hoc filenames make long‑term search difficult.
- Philosophy: Archives must remain usable for decades. That means simple folders, human‑readable filenames, and backups anyone can understand — independent of specific apps or platforms.
- Approach: "Old‑school, AI‑assisted." autoPDFtagger analyzes text and images (GPT‑based) to build a searchable index and suggest consistent filenames. It writes standard PDF metadata and can output JSON for piping and review.
- Safety & control: Leaves originals untouched unless you export; uses a confidence logic to only update when results improve quality.
- Outcome: Faster, more reliable search in your existing filesystem. No DMS required — yet fully compatible with any DMS.

## Current Status
At the moment, there exists a functional prototype in the form of a terminal program with a Python module, which demonstrates its functionality and has already achieved impressive results for me. For a broader application, many detailed improvements are certainly necessary, especially in testing, promt-optimization, error handling and documentation.

## Caution and Considerations / Disclaimer

- **Data Privacy**: PDF content is transmitted to OpenAI servers for analysis. While OpenAI claims non-use of API inputs for training, sensitivity in handling private documents is advised.
- **Cost Control**: Be aware of the costs associated with OpenAI API usage, which is based on request volume. Analysis of a single page costs around 0.05 $.
- **Accuracy and Reliability**: This initial version is a proof-of-concept and may have limitations. It's designed to create copies rather than alter original files.
- **Metadata Editing**: Altering metadata could potentially invalidate certain documents. Be careful with digital signed documents.

## Contribute ##

If you find this tool helpful and have ideas to improve it, feel free to contribute. While I'm not a full-time programmer and i'm not feeling professional at all, any suggestions or enhancements are welcome. Submit bug reports, feature requests, or any other feedback. Thanks for stopping by!

## Requirements to run this program
- Python
- For cloud models: a provider API key (e.g., `OPENAI_API_KEY`)
- For local models: a running Ollama with the chosen model pulled (e.g., `ollama pull llava`)

## Installation
 ```shell
$ pip install git+https://github.com/Uli-Z/autoPDFtagger
```

Create configuration file and save it to *~/.autoPDFtagger.conf*: 
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

## Program Structure

The program is fundamentally structured as follows:

### 1. Read Database (Input)
- By specifying PDF files
- By specifying a JSON file
- By entering JSON via standard input

### 2. Modify Database (Processing)
- Filtering files based on quality criteria
- Analysis of existing metadata, file name, folder structure (`file analysis`)
- Analysis of the contained text (`text analysis`)
- Analysis of the contained images (`image analysis`)
- Analysis and sorting of tags (`tag analysis`)

### 3. Output Database (Output)
- As JSON via standard output
- As JSON in a file
- In the form of PDF files with updated metadata included
- As statistics

**Note:** Principally, (almost) all options are combinable. The order of the individual steps is fixed, however; they are processed in the order mentioned above. Instead, the use of piping in the terminal is explicitly considered, allowing to pass the state of the database to another instance of the program. This makes it possitble to check and modify each step (e.g., first text analysis, then filtering by quality, followed by image analysis, then re-filtering, and finally exporting the PDF files). Using JSON-Output, the results of the program can be piped directly to another instance of the program. 


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

## Examples
Read all pdf files from a folder *pdf_archive*, do a basic file analysis (-f) and store information in a JSON-database *files.json* (-j [filename]):
```shell
$ autoPDFtagger ./pdf_archive --file-analysis --json allfiles.json
```

Read a previous created JSON-database an do an AI-text-analysis, storing the results in a new JSON-file
```shell
$ autoPDFtagger allfiles.json --ai-text-analysis --json textanalysis.json
```

Do an AI-image-analysis for all files with estimated low-quality metadata.
```shell
$ autoPDFtagger textanalysis.json --keep-below --ai-image-analysis --json imageanalysis.json
```

Recollect all together, analyse and organize tags
```shell
$ autoPDFtagger textanalysis.json imageanalysis.json --ai-tag-analysis --json final.json
```

Copy the files to a new folder *new_archive* setting new metadata and assigning new filenames. The original folder structure remains unchanged.
```shell
$ autoPDFtagger final.json -e ./new_archive
```

Do everything at once: 
```shell
$ autoPDFtagger pdf_archive -ftic -e new_archive
```

## Random Technical Aspects / Dive Deeper If You Want

- In addition to the terminal program, a Python module autoPDFtagger is available for integration with other software. Check the code for the interface details.
- The analysis of files includes not just the filename but also the local file path relative to a base directory (Base-Directory). By default, when folders are specified, the respective folder is set as the base directory for all files down to the subfolders. In some cases, it may be sensible to manually set a different base directory.
- Metadata management uses a "confidence logic". This means data is only updated if the (estimated) certainty/confidence is higher than the existing data. This aims for incremental improvement of information but can sometimes lead to inconsistent results.
- Keyword **confidence-index**: Within the program, it's possible to filter the database by this value. What's the rationale behind it? Primarily, it's a quickly improvised solution to enable sorting of database entries by the quality of their metadata. The AI itself assesses how well it can answer the given questions based on the available information and sets a confidence level. There are individual confidence values for the title, summary, and creation date. To consolidate these into a single value, the average is initially calculated. However, since the title and creation date are particularly critical, the minimum value out of the average, title, and creation date is used
- The **text analysis** of documents in the current configuration is carried out with the help of gpt-3.5-turbo-1106. With a context window of 16k, even larger documents can be analyzed at an affordable price of under $0.01. In my tests, the quality has proven to be sufficient. Only for very short documents does gpt-4 seem to bring a significant benefit. Therefore, the program automatically uses gpt-4 for short texts (~100 words).
- **Image analysis** is the most time-consuming and expensive process, which is why the algorithm is also adjusted here. At the time of creation, only the gpt-4-vision-preview model exists. The current approach is to analyze only the first page for scanned documents. Subsequent pages are only analyzed if the relevant metadata could not be determined with sufficient confidence. A similar logic exists for digitally created PDFs, where contained images are only analyzed until the information quality is sufficient.


## Code Structure

- `main.py`: CLI entry point.
- `autoPDFtagger.py`: Orchestrates analyses across the file list.
- `ai_tasks.py`: High-level task functions (text/images/tags) with prompts and JSON handling.
- `llm_client.py`: Thin LiteLLM wrapper for chat/vision and usage-based cost calculation.
- `PDFDocument.py`: PDF operations + metadata handling.
- `PDFList.py`: Collection/database for documents with JSON/CSV import/export.
- `config.py`: Configuration loader.
- `autoPDFtagger_example_config.conf`: Example config with `[AI]` options and optional key fallback.



## Future Development

- **Implementing an AI-API-Cache to save cost and time for testing**
- **Cost Control**: Implementing features for monitoring and managing API usage costs.
- **Graphical User Interface**: Developing a more user-friendly interface.
- **HTML Viewer App**: A proposed app to visualize the JSON database and integrate it with the file archive.
- **Integration and Compatibility**:
  - Expanding to other AI APIs and exploring local AI model integration.
  - Ensuring compatibility with applications like paperless-ngx.
- Enhancing tag organization and developing hierarchical information through the application of clustering algorithms on a vector database

## License

GPL-3
