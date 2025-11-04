import argparse
import logging
from textwrap import indent
import os
import sys

from autoPDFtagger.config import config
from autoPDFtagger import cache
from autoPDFtagger import ocr
from autoPDFtagger.logging_utils import configure_logging

def main():
     # ArgumentParser-Setup für CLI-Optionen
    parser = argparse.ArgumentParser(description="Smart PDF-analyzing Tool")
    parser.add_argument("input_items", nargs="*", help="List of input PDFs and folders, alternativly you can use a JSON- or CSV-file")
    parser.add_argument("--config-file", help="Specify path to configuration file. Defaults to ~/.autoPDFtagger.conf", default=os.path.expanduser("~/.autoPDFtagger.conf"))
    parser.add_argument("-b", "--base-directory", help="Set base directory", nargs='?', default=None, const="./")
    parser.add_argument("-j", "--json", nargs="?", const=None, default=argparse.SUPPRESS, help="Output JSON-Database to stdout. If filename provided, save it to file")
    parser.add_argument("-s", "--csv", nargs="?", const=None, help="Output CSV-Database to specified file")
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
    parser.add_argument("--ocr", dest="ocr", action="store_true", help="Enable OCR before AI text analysis (requires Tesseract)")
    parser.add_argument("--no-ocr", dest="ocr", action="store_false", help="Force-disable OCR regardless of configuration")
    parser.add_argument("--ocr-languages", help="Override Tesseract language codes (e.g. 'deu+eng')")
    parser.add_argument("--debug-ai-log", help="Append raw AI JSON responses to the given log file", default=None)
    parser.add_argument("--no-cache", action="store_true", help="Disable on-disk cache for OCR and AI calls")
    parser.set_defaults(ocr=None)

    args = parser.parse_args()

    # Map debug-Level to logging-level
    debug_levels = {0: logging.CRITICAL, 1: logging.INFO, 2: logging.DEBUG}

    # Load configuration (required to exist); API keys are loaded from environment
    if not config.read(args.config_file):
        raise FileNotFoundError(f"Config file not found: '{args.config_file}'")

    # After loading configuration:
    from autoPDFtagger.autoPDFtagger import autoPDFtagger
    ocr_setup = ocr.prepare_ocr_setup(
        config,
        cli_enabled=args.ocr,
        cli_languages=args.ocr_languages,
    )

    # Ensure logs are visible and integrate with status board rendering
    configure_logging(
        level=debug_levels[args.debug],
        fmt='%(asctime)s - %(levelname)s ::: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    # Configure cache from config with CLI override
    try:
        cfg_enabled = config.get("CACHE", "enabled", fallback="true").strip().lower()
        enabled = cfg_enabled in {"1", "true", "yes", "on"}
    except Exception:
        enabled = True
    try:
        ttl_seconds = int(config.get("CACHE", "ttl_seconds", fallback=str(24 * 60 * 60)))
    except Exception:
        ttl_seconds = 24 * 60 * 60
    try:
        cache_dir = config.get("CACHE", "dir", fallback="").strip() or None
    except Exception:
        cache_dir = None
    # CLI --no-cache disables regardless of config
    cache.configure(enabled=(enabled and not args.no_cache), ttl_seconds=ttl_seconds, base_dir=cache_dir)
    logging.debug("Cache configured: enabled=%s, ttl=%ss, dir=%s", str(enabled and not args.no_cache), ttl_seconds, cache_dir or "~/.autoPDFtagger/cache")

    archive = autoPDFtagger(ocr_runner=ocr_setup.runner, ai_log_path=args.debug_ai_log)

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
        return args.export is not None or hasattr(args, "json") or args.csv is not None

    # Parallel job execution for AI + OCR based on configuration
    if args.ai_text_analysis or args.ai_image_analysis:
        if is_output_option_set():
            # If image analysis is requested, follow up with text analysis automatically
            do_image = bool(args.ai_image_analysis)
            do_text = bool(args.ai_text_analysis or args.ai_image_analysis)
            # Enable OCR when any text analysis is planned and an OCR runner is available
            enable_ocr = bool(ocr_setup.runner) and do_text
            archive.run_jobs_parallel(
                do_text=do_text,
                do_image=do_image,
                enable_ocr=enable_ocr,
            )
        else:
            logging.error("No output option is set. Skipping AI analyses. Did you want to use --json?")

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
        # Optional filename format from config (strftime + {TITLE}/{CREATOR})
        try:
            filename_format = config.get("EXPORT", "filename_format", fallback=None)
            filename_format = filename_format.strip() if filename_format else None
        except Exception:
            filename_format = None
        archive.file_list.create_new_filenames(filename_format)
        logging.info(f"Exporting files to {args.export}")
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
    # Save results to CSV-file if set
    if args.csv is not None:
        archive.file_list.export_to_csv_file(args.csv)



if __name__ == "__main__":
    main()
