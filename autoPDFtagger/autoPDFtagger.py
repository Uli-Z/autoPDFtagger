import os
import logging
import traceback
from autoPDFtagger.config import config
from autoPDFtagger.PDFList import PDFList
from autoPDFtagger import ai_tasks

class autoPDFtagger:
    def __init__(self):
        self.ai = None
        self.file_list = PDFList()

    # Add file to database
    def add_file(self, path: str, base_dir = None):
        if base_dir and not os.path.exists(base_dir):
            logging.error(f"Basedir {base_dir} does not exist")
            base_dir = None
        if not base_dir:
            base_dir = os.path.dirname(path)
        
        # Read folder oder PDF-file
        self.file_list.add_pdf_documents_from_folder(path, base_dir)

    def file_analysis(self):
        for document in self.file_list.pdf_documents.values():
            logging.info(f"... {document.file_name}")
            document.analyze_file()

    def ai_text_analysis(self):
        logging.info("Asking AI to analyze PDF-Text")
        cost = 0.0  # for monitoring

        # Read AI config for text analysis
        ms = config.get('AI', 'text_model_short', fallback='')
        ml = config.get('AI', 'text_model_long', fallback='')
        thr = int(config.get('AI', 'text_threshold_words', fallback='100'))

        for document in self.file_list.pdf_documents.values():
            logging.info("... " + document.file_name)
            try:
                response, usage = ai_tasks.analyze_text(document, ms, ml, thr)
                if response:
                    document.set_from_json(response)
                cost += float(usage.get('cost', 0.0) or 0.0)
            except Exception as e:
                logging.error(document.file_name)
                logging.error(f"Text analysis failed. Error message: {e}")
                logging.error(traceback.format_exc())
        logging.info(f"Spent {cost:.4f} $ for text analysis")


    def ai_image_analysis(self):
        logging.info("Asking AI to analyze Images")
        costs = 0.0
        model = config.get('AI', 'image_model', fallback='')
        for document in self.file_list.pdf_documents.values():
            logging.info("... " + document.file_name)
            response, usage = ai_tasks.analyze_images(document, model)
            if response:
                document.set_from_json(response)
            costs += float(usage.get('cost', 0.0) or 0.0)
        logging.info("Spent " + str(costs) + " $ for image analysis")

    # Simplify and unify tags over all documents in the database
    def ai_tag_analysis(self):
        logging.info("Asking AI to optimize tags")
        unique_tags = self.file_list.get_unique_tags()
        logging.info("Unique tags: " + str(unique_tags))
        model = config.get('AI', 'tag_model', fallback='')
        replacements, usage = ai_tasks.analyze_tags(unique_tags, model=model)

        logging.info("Applying replacements")
        self.file_list.apply_tag_replacements_to_all(replacements)
        unique_tags = self.file_list.get_unique_tags()
        logging.info("New list of tags: " + str(unique_tags))
        logging.info("Spent " + str(usage.get('cost', 0.0)) + " $ for tag analysis")
       
    # Remove all documents from the database which until now could not be filled
    # with enough valuable information
    def keep_incomplete_documents(self, threshold=7):
        new_list = {}
        for doc in [d for d in self.file_list.pdf_documents.values() if d.has_sufficient_information(threshold)]:
            new_list[doc.get_absolute_path()] = doc
        self.file_list.pdf_documents = new_list

    # Remove all documents from the database
    # with enough valuable information
    def keep_complete_documents(self, threshold=7):
        new_list = {}
        for doc in [d for d in self.file_list.pdf_documents.values() if not d.has_sufficient_information(threshold)]:
            new_list[doc.get_absolute_path()] = doc
        self.file_list.pdf_documents = new_list

    def print_file_list(self):
        for doc in self.file_list.pdf_documents.values():
            print(os.path.join(doc.relative_path, doc.file_name))


    def export_database_to_json(self, file_name):
        self.file_list.export_to_json_file(file_name)

    # Get basic statistics about database
    def get_stats(self):

        total_documents = len(self.file_list.pdf_documents)
        total_pages = sum([len(doc.pages) for doc in self.file_list.pdf_documents.values()])
        total_images = sum([doc.get_image_number() for doc in self.file_list.pdf_documents.values()])
        def count_tokens_from_text(doc):
            text = doc.get_pdf_text() or ""
            return len(text.split()) // 3

        total_text_tokens = sum(count_tokens_from_text(doc) for doc in self.file_list.pdf_documents.values())

        # A very rough estimate for expected costs to do analysis over the actual data
        estimated_text_analysis_cost_lower = ((total_text_tokens + total_documents * 1000) / 1000) * 0.001
        estimated_text_analysis_cost_upper = estimated_text_analysis_cost_lower * 10 # in case of using gpt-4
        estimated_image_analysis_cost = [
            total_images * 0.03, # if every single image is analyzed
            total_pages * 0.03 # if only the first page is analyzed
            ]
        unique_tags = len(self.file_list.get_unique_tags())
        estimated_tag_analysis_cost = unique_tags * 0.01

        stats = {
            "Total Documents": total_documents,
            "Total Pages": total_pages,
            "Total Text Tokens (approx.)": total_text_tokens,
            "Total Images": total_images,
            "Unique Tags": unique_tags,
            "Estimated Text Analysis Cost ($)": f"{estimated_text_analysis_cost_lower:.2f} - {estimated_text_analysis_cost_upper:.2f}",
            "Estimated Image Analysis Cost ($)": f"{min(estimated_image_analysis_cost):.2f} - {max(estimated_image_analysis_cost):.2f}",
            "Estimated Tag Analysis Cost ($)": estimated_tag_analysis_cost,
            "Confidence-index Histogram": self.create_confidence_histogram(self.file_list)
        }

        return stats
    
    def create_confidence_histogram(self, pdf_list):
        # Step 1: Collect rounded confidence_index values
        confidence_counts = {}
        for pdf in pdf_list.pdf_documents.values():
            confidence = round(pdf.get_confidence_index())
            confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1

        if not confidence_counts:
            return "\n(no documents)\n"

        # Step 2: Determine the scale factor for histogram
        max_count = max(confidence_counts.values())
        max_resolution = 1
        scale_factor = min(max_resolution, 30 / max_count)

        # Step 3: Generate the histogram
        histogram = "\n"
        for i in range(min(confidence_counts.keys()), max(confidence_counts.keys()) + 1):
            count = confidence_counts.get(i, 0)
            bar_length = max(round(count * scale_factor), count > 0)  # Ensure at least one character for non-zero counts
            histogram += f"{i}: {'#' * bar_length} ({count})\n"

        return histogram
