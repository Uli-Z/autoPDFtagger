import os
import json
import logging
import re
from datetime import datetime
import pprint
import traceback

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
            logging.debug(f"File {abs_path} already in database. Updating meta data.")
            self.pdf_documents[abs_path].set_from_dict(pdf_document.to_dict())
        else:
            self.pdf_documents[abs_path] = pdf_document


    def export_to_json_without_ocr(self):
        pdf_list = [pdf_doc.to_dict() for pdf_doc in self.pdf_documents.values()]
        for pdf_doc_dict in pdf_list:
            pdf_doc_dict.pop("ocr_text", None)

        return json.dumps(pdf_list, indent=4)

    def create_thumbnail_for_documents(self, thumbnail_folder):
        for pdf_document in self.pdf_documents.values():
            pdf_document.create_thumbnail(thumbnail_folder)

    def add_pdf_documents_from_folder(self, folder_or_file, base_dir):
        if not os.path.exists(folder_or_file) or not os.path.exists(base_dir):
            logging.error(str([folder_or_file, base_dir] )+ " does not exist")
            return False
        
        if os.path.isdir(folder_or_file):
            # Der angegebene Pfad ist ein Ordner
            logging.info("Scanning folder " +folder_or_file )
            for root, _, files in os.walk(folder_or_file):
                for file in files:
                    if file.endswith(".pdf"):
                        file_path = os.path.join(root, file)
                        pdf_document = PDFDocument(file_path, base_dir)
                        self.add_pdf_document(pdf_document)
        elif os.path.isfile(folder_or_file) and folder_or_file.endswith(".pdf"):
            # Der angegebene Pfad ist eine einzelne PDF-Datei
            pdf_document = PDFDocument(folder_or_file, base_dir)
            self.add_pdf_document(pdf_document)
        else:
            # Der Pfad ist ungültig oder keine PDF-Datei oder Ordner
            logging.error(f"Ungültiger Pfad oder keine PDF-Datei oder Ordner: {folder_or_file}")

    def get_sorted_pdf_filenames(self):
        # Extrahiere die Dateinamen aller PDF-Dokumente
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
        Wendet Tag-Ersetzungen auf alle PDF-Dokumente in der Liste an.
        :param replacements: Liste von Dicts mit Original- und Ersatz-Tags
        """
        for pdf_document in self.pdf_documents.values():
            pdf_document.apply_tag_replacements(replacements)

    def set_tags_specificity_to_all(self, specificity_info):
        """
        Setzt die Spezifität der Tags für alle PDF-Dokumente in der Liste.
        :param specificity_info: Liste von Dicts mit Tag-Namen und Spezifität
        """
        for pdf_document in self.pdf_documents.values():
            pdf_document.set_tags_specificity(specificity_info)


    def export_to_json_complete(self, filename):
        """
        Speichert die gesamte Liste von PDF-Dokumenten als JSON in einer Datei.
        """
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump([doc.to_dict() for doc in self.pdf_documents.values()], f, indent=4)
    

    def import_from_json(self, filename):
        """
        Lädt die Liste von PDF-Dokumenten aus einer JSON-Datei.
        """
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
        
        except Exception as e:
            logging.error(f"Error loading JSON-File: {e}")
            return []

        for d in data:
            try:
                pdf_document = self.create_PDFDocument_from_json(d)
                self.add_pdf_document(pdf_document)
                logging.debug(f"Added {pdf_document.get_absolute_path()} from JSON-file to database")
            except Exception as e:
                logging.error(f"Could not import file from JSON-File. Error-message: {e}. Data: {pprint.pformat(d)}")
                traceback.print_exc()

    def create_PDFDocument_from_json(self,data):
        file_path = os.path.join(data['folder_path_abs'], data['file_name'])
        pdf_document = PDFDocument(file_path, data['base_directory_abs'])
        pdf_document.set_from_dict(data)
        return pdf_document
        
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
                    new_doc = self.create_PDFDocument_from_json(doc_data)

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