import os
import json
import logging
import re
from datetime import datetime
import pprint
import traceback
import csv

from autoPDFtagger.PDFDocument import PDFDocument

class PDFList:
    def __init__(self, folder=""):
        self.pdf_documents = {}
        if folder:
            self.add_pdf_documents_from_folder(folder)

    def add_pdf_document(self, pdf_document: PDFDocument):
        abs_path = pdf_document.get_absolute_path()
        if abs_path in self.pdf_documents:
            # If document already exists, data will be updated corresponding
            # to confidence-data (more actual data will be preserved)
            logging.info(f"File {abs_path} already in database. Updating meta data.")
            self.pdf_documents[abs_path].set_from_dict(pdf_document.to_dict())
        else:
            self.pdf_documents[abs_path] = pdf_document
            logging.info(f"File added: {pdf_document.file_name}")

    def export_to_json(self):
        pdf_list = [pdf_doc.to_dict() for pdf_doc in self.pdf_documents.values()]
        for pdf_doc_dict in pdf_list:
            pdf_doc_dict.pop("ocr_text", None)

        return json.dumps(pdf_list, indent=4)

    def create_thumbnail_for_documents(self, thumbnail_folder):
        for pdf_document in self.pdf_documents.values():
            pdf_document.create_thumbnail(thumbnail_folder)

    # Add single file (pdf, csv, json)
    def add_file(self, file_path, base_dir):
        if file_path.endswith(".pdf"):
            pdf_document = PDFDocument(file_path, base_dir)
            self.add_pdf_document(pdf_document)
        elif file_path.endswith(".json"):
            self.import_from_json_file(file_path)
        elif file_path.endswith(".csv"):
            self.import_from_csv_file(file_path)
        else: 
            logging.error(f"Invalid file type (skipped): {file_path}")

    # Scan a folder for files
    def add_pdf_documents_from_folder(self, folder_or_file, base_dir):
        if not os.path.exists(folder_or_file) or not os.path.exists(base_dir):
            logging.error(str([folder_or_file, base_dir] )+ " does not exist")
            return False
        
        if os.path.isdir(folder_or_file):
            # Folder? 
            logging.info("Scanning folder " +folder_or_file )
            for root, _, files in os.walk(folder_or_file):
                for file in files:
                    file_path = os.path.join(root, file)
                    self.add_file(file_path, base_dir)
                    
        else: # existing file, no directory
            self.add_file(folder_or_file, base_dir)

    def get_sorted_pdf_filenames(self):
        # Create list of filenames
        sorted_pdf_filenames = sorted(self.pdf_documents.keys())
        return sorted_pdf_filenames

    def get_unique_tags(self):
        # Create a set to store unique tags
        unique_tags = set()

        # Iterate over each PDFDocument in the list
        for pdf_document in self.pdf_documents.values():
            # Add tags of each document to the set
            unique_tags.update(pdf_document.tags)

        # Convert the set back to a list before returning
        return list(unique_tags)
    
    def apply_tag_replacements_to_all(self, replacements):
        """
        Apply a tag replacement list to all documents
        """
        for pdf_document in self.pdf_documents.values():
            pdf_document.apply_tag_replacements(replacements)


    def export_to_json_file(self, filename):
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump([doc.to_dict() for doc in self.pdf_documents.values()], f, indent=4)
    
    def export_to_csv_file(self, filename):
        try:
            if not self.pdf_documents:
                logging.warning("No documents to export.")
                return

            first_document = next(iter(self.pdf_documents.values()))
            fieldnames = list(first_document.to_dict().keys())

            with open(filename, 'w', newline='', encoding='utf-8-sig') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=';')
                writer.writeheader()

                for pdf_document in self.pdf_documents.values():
                    # Convert the document to a dictionary
                    pdf_dict = pdf_document.to_dict()

                    # Convert lists to JSON strings
                    for key, value in pdf_dict.items():
                        if isinstance(value, list):
                            pdf_dict[key] = json.dumps(value)
                        else:
                            pdf_dict[key] = str(value)

                    writer.writerow(pdf_dict)

            logging.info(f"Database exported to CSV: {filename}")
        except Exception as e:
            logging.error(f"Exporting to CSV-File failed: {e}\n" + traceback.format_exc())


    def clean_csv_row(self, row):
        data_types = {
            "folder_path_abs": str,
            "relative_path": str,
            "base_directory_abs": str,
            "file_name": str,
            "summary": str,
            "summary_confidence": float,
            "title": str,
            "title_confidence": float,
            "creation_date": str,
            "creation_date_confidence": float,
            "tags": str,
            "tags_confidence": str,
            "importance": float,
            "importance_confidence": float
        }
        
        for key, value in row.items():
            if key in ['tags', 'tags_confidence'] and value.startswith('[') and value.endswith(']'):
                try:
                    # Convert JSON string back to list
                    row[key] = json.loads(value)
                except json.JSONDecodeError:
                    raise ValueError(f"JSON decoding error for {key}: {value}")
            else:
                try:
                    # Convert to appropriate data type
                    row[key] = data_types[key](value)
                except ValueError:
                    raise ValueError(f"Value conversion error for {key}: {value}")

        return row


    def import_from_csv_file(self, filename):
        try:
            logging.info(f"Importing files from CSV-file: {filename}")
            with open(filename, 'r', encoding='utf-8-sig') as csvfile:
                reader = csv.DictReader(csvfile, delimiter=';')

                # Process each row and create PDFDocument objects
                for row in reader:
                    try:
                        row = self.clean_csv_row(row)
                        pdf_document = self.create_PDFDocument_from_dict(row)
                        if pdf_document:
                            self.add_pdf_document(pdf_document)
                    except:
                        continue

            logging.info("CSV-file processing completed")
        except Exception as e:
            logging.error(f"Importing from CSV-File failed: {e}\n" + traceback.format_exc())

    def import_from_json(self, json_text):
        data = json.loads(json_text) 
        for d in data:
            try:
                pdf_document = self.create_PDFDocument_from_dict(d)
                self.add_pdf_document(pdf_document)
            except Exception as e:
                logging.error(e)
                traceback.print_exc


    def import_from_json_file(self, filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                logging.info(f"Adding files from JSON-file: {filename}")
                self.import_from_json(f.read())
                logging.info("JSON-file processing completed")
        except Exception as e:
            logging.error(f"Error loading JSON-File: {e}")
            logging.error(traceback.format_exc())
            return []


    def create_PDFDocument_from_dict(self,data):
        try:
            file_path = os.path.join(data['folder_path_abs'], data['file_name'])
            pdf_document = PDFDocument(file_path, data['base_directory_abs'])
            pdf_document.set_from_dict(data)
            return pdf_document
        except Exception as e: 
            logging.error(f"Could not import file from JSON-File. Error-message: {e}. Data: {pprint.pformat(data)}")
            traceback.print_exc()
            return None
        
    def update_from_json(self, filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for doc_data in data:
                abs_path = doc_data['absolute_path']
                existing_doc = self.pdf_documents.get(abs_path)

                if existing_doc:
                    existing_doc.set_from_dict(doc_data)
                else:
                    new_doc = self.create_PDFDocument_from_dict(doc_data)

                    self.add_pdf_document(new_doc)

        except Exception as e:
            logging.error(f"Error updating PDF list from JSON: {e}")

    def export_to_folder(self, path):
        logging.info("Exporting files to folder " + path)
        for pdf in self.pdf_documents.values():
            # Determine the new relative path and create the folder if it doesn't exist
            new_relative_path = pdf.new_relative_path if hasattr(pdf, 'new_relative_path') else re.sub(r'^(\.\./)+|^\.$', '', pdf.relative_path)
            target_directory = os.path.join(path, new_relative_path)
            os.makedirs(target_directory, exist_ok=True)

            # Determine the filename for the target
            target_filename = pdf.new_file_name if hasattr(pdf, 'new_file_name') else pdf.file_name
            target_file_path = os.path.join(target_directory, target_filename)
            print(pdf.new_file_name)
            # Copy the file to the target folder
            pdf.save_to_file(target_file_path)

    def create_new_filenames(self):
        for doc in self.pdf_documents.values(): 
            doc = doc.create_new_filename()