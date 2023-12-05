import argparse
import logging
from textwrap import indent
import os

from autoPDFtagger.config import config

def main():
     # ArgumentParser-Setup für CLI-Optionen
    parser = argparse.ArgumentParser(description="Smart PDF-analyzing Tool")
    parser.add_argument("input_items", nargs="+", help="List of input PDFs and folders, alternativly you can use a JSON-file")
    parser.add_argument("--config-file", help="Specify path to configuration file. Defaults to ~/.autoPDFtagger.conf", default=os.path.expanduser("~/.autoPDFtagger.conf"))
    parser.add_argument("-b", "--base-directory", help="Set base directory", nargs='?', default=None, const="./")
    parser.add_argument("-j", "--json", help="Path to output JSON file")
    parser.add_argument("-d", "--debug", help="Debug level (0: no debug, 1: basic debug, 2: detailed debug)", type=int, choices=[0, 1, 2], default=2)
    parser.add_argument("-t", "--ai-text-analysis", help="Do an AI text analysis", action="store_true")
    parser.add_argument("-i", "--ai-image-analysis", help="Do an AI image analysis", action="store_true")
    parser.add_argument("-c", "--ai-tag-analysis", help="Do an AI tag analysis", action="store_true")
    parser.add_argument("-e", "--export", help="Copy Documents to a target folder", nargs='?', default=None, const=None)
    parser.add_argument("-l", "--list-incomplete", help="List incomplete documents", action="store_true")
    parser.add_argument("-x", "--filter-incomplete", help="Only apply action to incomplete documents", action="store_true")

    args = parser.parse_args()

    # Map debug-Level to logging-level
    debug_levels = {0: logging.CRITICAL, 1: logging.INFO, 2: logging.DEBUG}

    try:
        if not config.read(args.config_file):
            raise FileNotFoundError(f"Config file not found: '{args.config_file}'")

        config['OPENAI-API'].get('API-Key')
    except Exception as e:
        raise e

    # After loading configuration:
    from autoPDFtagger.autoPDFtagger import autoPDFtagger

    logging.basicConfig(level=debug_levels[args.debug], format='%(asctime)s - %(levelname)s ::: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S')

    archive = autoPDFtagger()

    # Iterate over input items (PDFs and JSON-files)
    for input_item in args.input_items:
        archive.add_file(input_item, args.base_directory) # includes JSON-files!

    logging.debug("Following files were added: " + str(archive.file_list.get_sorted_pdf_filenames()))

    if args.filter_incomplete:
        logging.info("Deleting complete files from database")
        archive.filter_incomplete_documents()

    if len(archive.file_list.pdf_documents)==0:
        logging.info("No documents in list.")
        return

    if args.ai_text_analysis:
        logging.info("Doing AI-text-analysis")
        archive.ai_text_analysis()

    if args.ai_image_analysis:
        archive.ai_image_analysis()

    if args.ai_tag_analysis:
        archive.ai_tag_analysis()

    if args.export is not None:
        archive.file_list.create_new_filenames()
        logging.info("Exporting files to {args.export}")
        archive.file_list.export_to_folder(args.export)

    if args.list_incomplete:
        logging.info("Listing incomplete documents")
        archive.show_incomplete_documents()

    # Save results to JSON-file if set
    if args.json:
        output_json = archive.file_list.export_to_json_complete(args.json)
        logging.info(f"Database saved to {args.json}")
    else: # print to terminal
        output_json = archive.file_list.export_to_json_without_ocr()
        print(output_json)


if __name__ == "__main__":
    main()
