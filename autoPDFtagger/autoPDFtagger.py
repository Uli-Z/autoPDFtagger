

from PDFList import PDFList

import os
import logging
from config import config

import AIAgents_OpenAI_pdf

class autoPDFtagger:
    def __init__(self):
        self.ai = None
        self.debug_level = 1
        self.override = "confidence"
        self.file_list = PDFList()

    def inport_database(self, json_file):
        self.file_list.update_from_json(json_file)

    # Add file to database
    def add_file(self, path: str, base_dir = None):
        # if a json-file is given, we import it
        if path.endswith(".json"):
            self.file_list.import_from_json(path)
            return
        if base_dir and not os.path.exists(base_dir):
            logging.error(f"Basedir {base_dir} does not exist")
            base_dir = None
        if not base_dir:
            base_dir = os.path.dirname(path)
        
        # Read folder oder PDF-file
        self.file_list.add_pdf_documents_from_folder(path, base_dir)

    def ai_text_analysis(self, arguments):
        logging.info("Asking AI to analyze PDF-Text")

        ai = AIAgents_OpenAI_pdf.AIAgent_OpenAI_pdf_text_analysis()

        for document in self.file_list.pdf_documents.values():
            logging.info("... " + document.file_name) 
            try:
                response = ai.analyze_text(document)
                document.set_from_json(response)
            except Exception as e: 
                logging.error(document.file_name)
                logging.error(f"Text analysis failed. Error message: {e}")


    def ai_image_analysis(self, minimum_image_size=300*300, confidence_treshold=7):
        logging.info("Asking AI to analyze Images")
        
        ai = AIAgents_OpenAI_pdf.AIAgent_OpenAI_pdf_image_analysis()
        
        for document in self.file_list.pdf_documents.values(): 
            logging.info("... " + document.file_name)
            response = ai.analyze_images(document)
            document.set_from_json(response)
    

    def ai_tag_analysis(self):
        logging.info("Asking AI to optimize tags")
        unique_tags = self.file_list.get_unique_tags()
        logging.info("Unique tags: " + str(unique_tags))

        ai = AIAgents_OpenAI_pdf.AIAgent_OpenAI_pdf_tag_analysis()
        replacements = ai.send_request(unique_tags)

        logging.info("Applying replacements")
        # Ersetzungen und Spezifitätsinformationen anwenden
        self.file_list.apply_tag_replacements_to_all(replacements)
        unique_tags = self.file_list.get_unique_tags()
        logging.info("New list of tags: " + str(unique_tags))
       

    def filter_incomplete_documents(self):
        new_list = {}
        for doc in [d for d in self.file_list.pdf_documents.values() if not d.has_sufficient_information()]:
            print(os.path.join(doc.relative_path, doc.file_name))
            new_list[doc.get_absolute_path()] = doc
        self.file_list.pdf_documents = new_list

    def show_incomplete_documents(self):
        for doc in [d for d in self.file_list.pdf_documents.values() if not d.has_sufficient_information()]:
            print(os.path.join(doc.relative_path, doc.file_name))

    def set_override(self, override="confidence"):
        self.override = override
        pass

    def change_filenames(self):
        # Implementieren der Logik zum Ändern der Dateinamen
        pass

    def reset_folder_structure(self):
        # Logik zum Zurücksetzen der Ordnerstruktur
        pass

    def ai_organize_folder_structure(self):
        # Logik zur Optimierung der Ordnerstruktur
        pass

    def export_to_folder(self, folder_name):
        # Implementieren der Logik zum Kopieren von Dateien in einen neuen Ordner
        pass

    def export_database_to_json(self, file_name):
        self.file_list.export_to_json_complete(file_name)

    # Hinzufügen weiterer notwendiger Hilfsfunktionen und Logik