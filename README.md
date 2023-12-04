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

## Future Development

- **Graphical User Interface**: Developing a more user-friendly interface.
- **HTML Viewer App**: A proposed app to visualize the JSON database and integrate it with the file archive.
- **Cost Control**: Implementing features for monitoring and managing API usage costs.
- **Integration and Compatibility**:
  - Expanding to other AI APIs and exploring local AI model integration.
  - Ensuring compatibility with applications like paperless-ngx.

## Caution and Considerations

- **Data Privacy**: PDF content is transmitted to OpenAI servers for analysis. While OpenAI claims non-use of API inputs for training, sensitivity in handling private documents is advised.
- **Cost Control**: Be aware of the costs associated with OpenAI API usage, which is based on request volume.
- **Accuracy and Reliability**: This initial version is a proof-of-concept and may have limitations. It's designed to create copies rather than alter original files.
- **Metadata Editing**: Altering metadata could potentially invalidate certain documents.

## Getting Started

1. **Download and Installation**:
   - Download the software.
   - Install using PIP.
   - Configure using the example configuration file.

## Installation
 ```js
pip install git+https://github.com/Uli-Z/autoPDFtagger
```

Create configuration file and save it to *~/.autoPDFtagger.conf*: 
```ini
; Configuration for autoPDFtagger

[DEFAULT]
language = {YOUR LANGUAGE}

[OPENAI-API]
API-Key = {INSERT YOUR API-KEY}
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

## License

GPL-3

