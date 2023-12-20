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
- An **OpenAI-API-Key with access to gpt-4-vision-preview model**
- Calculate Costs about 0.03 $ per image-processed PDF-Page

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

- `main.py`: The terminal interface for the application.
- `autoPDFtagger.py`: Manages the core functionalities of the tool.
- `AIAgents.py`: Base classes for AI agent management, including OpenAI API communication.
- `AIAgents_OPENAI_pdf.py`: Specific AI agents dedicated to text, image, and tag analysis.
- `PDFDocument.py`: Handles individual PDF documents, managing metadata reading and writing.
- `PDFList.py`: Oversees a database of PDF documents, their metadata, and provides export functions.
- `config.py`: Manages configuration files.
- `autoPDFtagger_example_config.conf`: An example configuration file outlining API key setup and other settings.



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

