import argparse
import logging
from textwrap import indent
import os
import sys

from autoPDFtagger.config import config

def main():
     # ArgumentParser-Setup für CLI-Optionen
    parser = argparse.ArgumentParser(description="Smart PDF-analyzing Tool")
    parser.add_argument("input_items", nargs="*", help="List of input PDFs and folders, alternativly you can use a JSON-file")
    parser.add_argument("--config-file", help="Specify path to configuration file. Defaults to ~/.autoPDFtagger.conf", default=os.path.expanduser("~/.autoPDFtagger.conf"))
    parser.add_argument("-b", "--base-directory", help="Set base directory", nargs='?', default=None, const="./")
    parser.add_argument("-j", "--json", nargs="?", const=None, default=argparse.SUPPRESS, help="Output JSON-Database to stdout. If filename provided, save it to file")
    parser.add_argument("-d", "--debug", help="Debug level (0: no debug, 1: basic debug, 2: detailed debug)", type=int, choices=[0, 1, 2], default=1)
    parser.add_argument("-f", "--file-analysis", help="Try to conventionally extract metadata from file, file name and folder structure", action="store_true")   
    parser.add_argument("-t", "--ai-text-analysis", help="Do an AI text analysis", action="store_true")     
    parser.add_argument("-i", "--ai-image-analysis", help="Do an AI image analysis", action="store_true")
    parser.add_argument("-c", "--ai-tag-analysis", help="Do an AI tag analysis", action="store_true")
    parser.add_argument("-e", "--export", help="Copy Documents to a target folder", nargs='?', default=None, const=None)
    parser.add_argument("-l", "--list", help="List documents stored in database", action="store_true")
    parser.add_argument("--keep-above", nargs="?", type=int, const=7, default=None, help="Before applying actions, filter out and retain only the documents with a confidence index greater than or equal to a specific value (default: 7).")
    parser.add_argument("--keep-below", nargs="?", type=int, const=7, default=None, help="Analogous to --keep-above. Retain only document with an index less than specified.")
    parser.add_argument("--calc-stats", help="Calculate statistics and (roughly!) estimate costs for different analyses", action="store_true")

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

    # Read JSON from StdIn
    def stdin_has_data():
        return not os.isatty(sys.stdin.fileno())
    
    if stdin_has_data():
        input_data = sys.stdin.read()
        try:
            archive.file_list.import_from_json(input_data)
        except: 
            logging.error("No valid JSON in stdin")

    # Iterate over input items (PDFs and JSON-files)
    if hasattr(args, "input_items"):
        for input_item in args.input_items:
            archive.add_file(input_item, args.base_directory) # includes JSON-files!

        logging.debug("Following files were added: " + str(archive.file_list.get_sorted_pdf_filenames()))

    if args.keep_above:
        logging.info("Deleting entries with insufficient metadata from database")
        archive.keep_incomplete_documents(args.keep_above)

    if args.keep_below:
        logging.info("Deleting entries with sufficient metadata from database")
        archive.keep_complete_documents(args.keep_below)

    if len(archive.file_list.pdf_documents)==0:
        logging.info("No documents in list.")
        return

    if args.file_analysis:
        logging.info("Doing basic file-analysis")
        archive.file_analysis()

    def is_output_option_set():
        return args.export is not None or hasattr(args, "json")

    if args.ai_text_analysis:
        if is_output_option_set():
            archive.ai_text_analysis()
        else:
            logging.error("No output option is set. Skipping text analysis. Did you want to use --json?")

    if args.ai_image_analysis:
        if is_output_option_set():
            archive.ai_image_analysis()
        else:
            logging.error("No output option is set. Skipping image analysis. Did you want to use --json?")

    if args.ai_tag_analysis:
        if is_output_option_set():
            archive.ai_tag_analysis()
        else:
            logging.error("No output option is set. Skipping tag analysis. Did you want to use --json?")
    
    if args.calc_stats:
        # Print status information and ask for proceeding
        stats = archive.get_stats().items()
        print("\n".join([f"{key}: {value}" for key, value in stats]))


    if args.export is not None:
        archive.file_list.create_new_filenames()
        logging.info("Exporting files to {args.export}")
        archive.file_list.export_to_folder(args.export)

    if args.list:
        logging.info("File stored in database:")
        archive.print_file_list()

    # Save results to JSON-file if set
    if hasattr(args, 'json'):
        if not args.json == None:
            output_json = archive.file_list.export_to_json_file(args.json)
            logging.info(f"Database saved to {args.json}")
        else: # print to stdout
            output_json = archive.file_list.export_to_json()
            print(output_json)


if __name__ == "__main__":
    main()
