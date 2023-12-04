# autoPDFtagger

## Overview

autoPDFtagger is a Python tool designed for efficient home-office organization, focusing on digitizing and organizing both digital and paper-based documents. By automating the tagging of PDF files, including image-rich documents and scans of varying quality, it aims to streamline the organization of digital archives.

## Key Concepts

- **AI-Powered Tagging**: Leverages GPT-4 and GPT-Vision for fully automated tagging of PDFs, including intricate drawings and low-quality scans.
- **Focus**: Engineered for paperless home-office setups, prioritizing precise data analysis over complex UI.
- **Requirements**: Python environment and an OpenAI API key.
- **Functionalities**:
  - Robust text analysis powered by GPT.
  - Advanced image analysis utilizing GPT-Vision.
  - Utilizes existing metadata, file names, and folder structures.
  - Compiles information into a JSON database for easy access.
  - Standardizes file naming (YY-mm-dd-{TITLE}.pdf) and updates PDF metadata for efficient indexing.
  - Configurable to integrate other AI agents.
  - Future enhancements to refine folder organization.

## Concept and Context

In the advancing digital age, many documents are now delivered digitally, yet significant documents often still arrive in paper form. Looking towards a digital future, the consolidation of these documents into a unified digital archive becomes increasingly valuable. Simple scanning using smartphone cameras has made this practical. However, the reliability of existing OCR technologies and their limited ability to effectively index non-textual content like drawings or photos hampers the searchability of these documents. autoPDFtagger aims to bridge this gap by offering AI-assisted analysis and organization of PDF files, enhancing their searchability and organization with a level of precision comparable to human effort.

## Caution and Considerations / Disclaimer

- **Data Privacy**: PDF content is transmitted to OpenAI servers for analysis. While OpenAI claims non-use of API inputs for training, sensitivity in handling private documents is advised.
- **Cost Control**: Be aware of the costs associated with OpenAI API usage, which is based on request volume. Analysis of a single page costs around 0.05 $.
- **Accuracy and Reliability**: This initial version is a proof-of-concept and may have limitations. It's designed to create copies rather than alter original files.
- **Metadata Editing**: Altering metadata could potentially invalidate certain documents.

## What you need to run this program
- Python
- An OpenAI-API-Key
- Calculate Costs about 0.05 $ per processed PDF-Page

## Installation
 ```shell
$ pip install git+https://github.com/Uli-Z/autoPDFtagger
```

Create configuration file and save it to *~/.autoPDFtagger.conf*: 
```ini
; Configuration for autoPDFtagger

[DEFAULT]
language = {YOUR LANGUAGE}

[OPENAI-API]
API-Key = {INSERT YOUR API-KEY}
```
## Usage
 ```shell
$ autoPDFtagger --help
usage: autoPDFtagger [-h] [--config-file CONFIG_FILE] [-b [BASE_DIRECTORY]] [-j JSON] [-d {0,1,2}] [-t] [-i] [-c] [-e EXPORT [EXPORT ...]] [-l] [-x] input_items [input_items ...]

Smart PDF-analyzing Tool

positional arguments:
  input_items           List of input PDFs and folders, alternativly you can use a JSON-file

options:
  -h, --help            show this help message and exit
  --config-file CONFIG_FILE
                        Specify path to configuration file. Defaults to ~/.autoPDFtagger.conf
  -b [BASE_DIRECTORY], --base-directory [BASE_DIRECTORY]
                        Set base directory
  -j JSON, --json JSON  Path to output JSON file
  -d {0,1,2}, --debug {0,1,2}
                        Debug level (0: no debug, 1: basic debug, 2: detailed debug)
  -t, --ai-text-analysis
                        Do an AI text analysis
  -i, --ai-image-analysis
                        Do an AI image analysis
  -c, --ai-tag-analysis
                        Do an AI tag analysis
  -e EXPORT, --export EXPORT
                        Copy Documents to a target folder
  -l, --list-incomplete
                        List incomplete documents
  -x, --filter-incomplete
                        Only apply action to incomplete documents
```

## Examples
Read all pdf files from a folder *pdf_archive* and store information in a JSON-database *files.json*:
```shell
$ autoPDFtagger pdf_archive -j files.json
```

Read a previous created JSON-database an do an AI-text-analysis, storing the results in a new JSON-file
```shell
$ autoPDFtagger files.json -t -j files2.json
```

Do an AI-image-analysis and tag-analyis on these files
```shell
$ autoPDFtagger files2.json -i -c -j files3.json
```

Copy the file to a new folder *new_archive* setting new metadata and assigning new filenames. The original folder structure remains unchanged.
```shell
$ autoPDFtagger files3.json -e new_archive
```

Do all the above steps in one command: 
```shell
$ autoPDFtagger pdf_archive -tic -e new_archive
```

## Code Structure

- `main.py`: The terminal interface for the application.
- `autoPDFtagger.py`: Manages the core functionalities of the tool.
- `AIAgents.py`: Base classes for AI agent management, including OpenAI API communication.
- `AIAgents_OPENAI_pdf.py`: Specific AI agents dedicated to text, image, and tag analysis.
- `PDFDocument.py`: Handles individual PDF documents, managing metadata reading and writing.
- `PDFList.py`: Oversees a database of PDF documents, their metadata, and provides export functions.
- `config.py`: Manages configuration files.
- `autoPDFtagger_example_config.conf`: An example configuration file outlining API key setup and other settings.

## Future Development

- **Graphical User Interface**: Developing a more user-friendly interface.
- **HTML Viewer App**: A proposed app to visualize the JSON database and integrate it with the file archive.
- **Cost Control**: Implementing features for monitoring and managing API usage costs.
- **Integration and Compatibility**:
  - Expanding to other AI APIs and exploring local AI model integration.
  - Ensuring compatibility with applications like paperless-ngx.

## License

GPL-3

