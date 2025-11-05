import json
import logging
import os
import threading
import time
import traceback
from autoPDFtagger.config import config
from autoPDFtagger.PDFList import PDFList
from autoPDFtagger import ai_tasks, mock_provider
from autoPDFtagger.PDFDocument import PDFDocument
from autoPDFtagger.job_manager import JobManager, Job

class autoPDFtagger:
    def __init__(self, ocr_runner=None, ai_log_path=None, visual_debug_path=None):
        self.ai = None
        self.file_list = PDFList()
        PDFDocument.configure_ocr(ocr_runner)
        mock_provider.reset()
        self._ai_response_log_path = ai_log_path
        self._visual_debug_path = visual_debug_path

    # Add file to database
    def add_file(self, path: str, base_dir = None):
        if base_dir and not os.path.exists(base_dir):
            logging.error(f"Basedir {base_dir} does not exist")
            base_dir = None
        if not base_dir:
            # Derive base directory from the provided path.
            # If the path has no directory component (e.g., "file.pdf"),
            # use the current working directory to avoid empty base paths.
            derived = os.path.dirname(path)
            base_dir = derived if derived else os.getcwd()
        
        # Read folder oder PDF-file
        self.file_list.add_pdf_documents_from_folder(path, base_dir)

    def file_analysis(self):
        for document in self.file_list.pdf_documents.values():
            logging.info(f"... {document.file_name}")
            document.analyze_file()

    def _log_ai_response(self, task, document, response_payload, usage):
        if not self._ai_response_log_path:
            return
        entry = {
            "timestamp": time.time(),
            "task": task,
            "document": document.get_absolute_path() if document else None,
            "response": response_payload,
            "usage": usage,
        }
        try:
            log_dir = os.path.dirname(self._ai_response_log_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            with open(self._ai_response_log_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False))
                handle.write("\n")
        except Exception as exc:
            logging.warning("Failed to write AI response log '%s': %s", self._ai_response_log_path, exc)

    def ai_text_analysis(self):
        logging.info("Asking AI to analyze PDF-Text")
        cost = 0.0  # real cost for this run
        saved = 0.0  # cost avoided via cache

        # Read AI config for text analysis
        ms = config.get('AI', 'text_model_short', fallback='openai/gpt-5-mini')
        ml = config.get('AI', 'text_model_long', fallback='openai/gpt-5-nano')
        thr = int(config.get('AI', 'text_threshold_words', fallback='100'))

        for document in self.file_list.pdf_documents.values():
            logging.info("... " + document.file_name)
            try:
                response, usage = ai_tasks.analyze_text(document, ms, ml, thr)
                self._log_ai_response("text", document, response, usage)
                if response:
                    document.set_from_json(response)
                c = float((usage or {}).get('cost', 0.0) or 0.0)
                s = float((usage or {}).get('saved_cost', 0.0) or 0.0)
                cost += c
                saved += s
                if c or s:
                    logging.info("[AI text cost] %s :: spent=%.4f $, saved=%.4f $", document.file_name, c, s)
            except Exception as e:
                logging.error(document.file_name)
                logging.error(f"Text analysis failed. Error message: {e}")
                logging.error(traceback.format_exc())
        logging.info(f"Spent {cost:.4f} $ for text analysis (saved {saved:.4f} $ via cache)")


    def ai_image_analysis(self):
        logging.info("Asking AI to analyze Images")
        costs = 0.0
        saved = 0.0
        model = config.get('AI', 'image_model', fallback='openai/gpt-5-nano')
        for document in self.file_list.pdf_documents.values():
            logging.info("... " + document.file_name)
            # Use the combined (text+images) algorithm for image analysis
            response, usage = ai_tasks.analyze_combined(document, model, visual_debug_path=self._visual_debug_path)
            self._log_ai_response("image", document, response, usage)
            # Only set metadata if response is a single JSON object
            try:
                parsed = json.loads(response) if response else None
                if isinstance(parsed, dict):
                    document.set_from_json(response)
            except Exception:
                pass
            c = float((usage or {}).get('cost', 0.0) or 0.0)
            s = float((usage or {}).get('saved_cost', 0.0) or 0.0)
            costs += c
            saved += s
            if c or s:
                logging.info("[AI image cost] %s :: spent=%.4f $, saved=%.4f $", document.file_name, c, s)
        logging.info("Spent %.4f $ for image analysis (saved %.4f $ via cache)" % (costs, saved))

    def run_jobs_parallel(
        self,
        do_text: bool,
        do_image: bool,
        enable_ocr: bool,
    ) -> None:
        """Run requested jobs with configurable concurrency and dependencies.

        - OCR jobs run on the local machine (Tesseract) and are limited by CPU cores (configurable).
        - AI jobs (text + image) share a single pool limited by a global max (configurable).
        - Text jobs depend on OCR job for the same document when OCR is enabled.
        - Periodically logs a status overview (pending/running/done/failed per kind).
        """
        if not (do_text or do_image):
            return

        # Read concurrency settings
        try:
            ocr_workers = int(config.get('JOBS', 'ocr_max_workers', fallback=str(os.cpu_count() or 2)))
        except Exception:
            ocr_workers = os.cpu_count() or 2
        try:
            ai_workers = int(config.get('JOBS', 'ai_max_workers', fallback='4'))
        except Exception:
            ai_workers = 4
        try:
            status_interval = float(config.get('JOBS', 'status_interval_sec', fallback='2.0'))
        except Exception:
            status_interval = 2.0

        jm = JobManager(
            ocr_workers=ocr_workers,
            ai_workers=ai_workers,
            status_interval_sec=status_interval,
        )

        # Shared cost accumulators
        lock = threading.Lock()
        totals = {"text_spent": 0.0, "text_saved": 0.0, "image_spent": 0.0, "image_saved": 0.0}

        # Read AI config once
        ms = config.get('AI', 'text_model_short', fallback='openai/gpt-5-mini')
        ml = config.get('AI', 'text_model_long', fallback='openai/gpt-5-nano')
        thr = int(config.get('AI', 'text_threshold_words', fallback='100'))
        image_model = config.get('AI', 'image_model', fallback='openai/gpt-5-nano')
        # Combined mode removed; image analysis uses the combined (text+images) algorithm

        for document in self.file_list.pdf_documents.values():
            abs_path = document.get_absolute_path()
            ocr_id = f"ocr:{abs_path}"

            if enable_ocr:
                def _make_ocr(doc=document):
                    def _run():
                        logging.info("[OCR] %s", doc.file_name)
                        # Trigger text extraction (this will OCR when needed)
                        _ = doc.get_pdf_text()
                        logging.info("[OCR done] %s", doc.file_name)
                    return _run
                jm.add_job(Job(id=ocr_id, kind="ocr", run=_make_ocr()))

            # Add image job; it now uses the combined (text+images) algorithm
            if do_image:
                def _make_img(doc=document):
                    def _run():
                        try:
                            logging.info("[AI image] %s", doc.file_name)
                            response, usage = ai_tasks.analyze_combined(doc, image_model, visual_debug_path=self._visual_debug_path)
                            self._log_ai_response("image", doc, response, usage)
                            # Backward-compatibility: update only if response is a single object
                            try:
                                parsed = json.loads(response) if response else None
                                if isinstance(parsed, dict):
                                    doc.set_from_json(response)
                            except Exception:
                                pass
                            with lock:
                                totals["image_spent"] += float((usage or {}).get('cost', 0.0) or 0.0)
                                totals["image_saved"] += float((usage or {}).get('saved_cost', 0.0) or 0.0)
                            c = float((usage or {}).get('cost', 0.0) or 0.0)
                            s = float((usage or {}).get('saved_cost', 0.0) or 0.0)
                            if c or s:
                                logging.info("[AI image cost] %s :: spent=%.4f $, saved=%.4f $", doc.file_name, c, s)
                            logging.info("[AI image done] %s", doc.file_name)
                        except Exception as exc:
                            logging.error("Image analysis failed for %s: %s", doc.file_name, exc)
                            raise
                    return _run
                # If OCR is enabled, let image analysis depend on OCR to warm caches and keep logs tidy
                deps = [ocr_id] if enable_ocr else []
                jm.add_job(Job(id=f"image:{abs_path}", kind="image", run=_make_img(), deps=deps))

            if do_text:
                def _make_text(doc=document):
                    def _run():
                        try:
                            logging.info("[AI text] %s", doc.file_name)
                            response, usage = ai_tasks.analyze_text(doc, ms, ml, thr)
                            self._log_ai_response("text", doc, response, usage)
                            if response:
                                doc.set_from_json(response)
                            with lock:
                                totals["text_spent"] += float((usage or {}).get('cost', 0.0) or 0.0)
                                totals["text_saved"] += float((usage or {}).get('saved_cost', 0.0) or 0.0)
                            c = float((usage or {}).get('cost', 0.0) or 0.0)
                            s = float((usage or {}).get('saved_cost', 0.0) or 0.0)
                            if c or s:
                                logging.info("[AI text cost] %s :: spent=%.4f $, saved=%.4f $", doc.file_name, c, s)
                            logging.info("[AI text done] %s", doc.file_name)
                        except Exception as exc:
                            logging.error("Text analysis failed for %s: %s", doc.file_name, exc)
                            raise
                    return _run
                deps = [ocr_id] if enable_ocr else []
                if do_image:
                    # Ensure text runs after image for the same document so that alt-texts are available
                    deps.append(f"image:{abs_path}")
                jm.add_job(Job(id=f"text:{abs_path}", kind="text", run=_make_text(), deps=deps))

        # Run and summarize
        pending, running, done, failed = jm.run()
        if failed:
            logging.warning("Some jobs failed: %d failed, %d completed", failed, done)
        if do_text:
            logging.info(
                "Spent %.4f $ for text analysis (saved %.4f $ via cache)",
                totals["text_spent"], totals["text_saved"],
            )
        if do_image:
            logging.info(
                "Spent %.4f $ for image analysis (saved %.4f $ via cache)",
                totals["image_spent"], totals["image_saved"],
            )

    # Simplify and unify tags over all documents in the database
    def ai_tag_analysis(self):
        logging.info("Asking AI to optimize tags")
        unique_tags = self.file_list.get_unique_tags()
        logging.info("Unique tags: " + str(unique_tags))
        model = config.get('AI', 'tag_model', fallback='')
        replacements, usage = ai_tasks.analyze_tags(unique_tags, model=model)
        self._log_ai_response("tag", None, replacements, usage)

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
