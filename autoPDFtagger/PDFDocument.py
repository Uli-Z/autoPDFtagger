"""
PDFDocument: A backend class for PDF file manipulation, 
focusing on metadata handling and basic data quality control 
for AI API integration. It specializes in extracting and 
managing metadata from various sources, allowing for incremental 
improvement of metadata accuracy. This includes assessing 
data quality through a 'confidence' metric. Core operations, 
such as text and image extraction, are facilitated by 
PyMuPDF (fitz). The class supports reading PDF content, 
analyzing images, and modifying document metadata. It is 
designed for AI processes that benefit from progressively 
enhanced metadata, extracted from multiple data points, to 
ensure a reliable and accurate representation of document information.
"""

import os
import json
import fitz 
import logging
import re
import base64
from datetime import datetime
import pytz
import traceback


date_formats = {
    r'\d{4}-\d{2}-\d{2}': "%Y-%m-%d",  # YYYY-MM-DD
    r'\d{4}_\d{2}_\d{2}': "%Y_%m_%d",  # YYYY_MM_DD
    r'\d{4} \d{2} \d{2}': "%Y %m %d",  # YYYY MM DD
    r'\d{4}\d{2}\d{2}':    "%Y%m%d",   # YYYYMMDD
    r'\d{4}-[a-zA-Z]{3}-\d{2}': "%Y-%b-%d",  # YYYY-Mon-DD
    r'\d{4}_[a-zA-Z]{3}_\d{2}': "%Y_%b_%d",  # YYYY_Mon_DD
    r'\d{4} [a-zA-Z]{3} \d{2}': "%Y %b %d",  # YYYY Mon DD
    r'\d{2}-[a-zA-Z]{3}-\d{4}': "%d-%b-%Y",  # DD-Mon-YYYY
    r'\d{2}_[a-zA-Z]{3}_\d{4}': "%d_%b_%Y",  # DD_Mon_YYYY
    r'\d{2} [a-zA-Z]{3} \d{4}': "%d %b %Y"   # DD Mon YYYY
}

class PDFDocument:
    """
    Class for handling operations on PDF documents.
    Includes reading, analyzing, and extracting information from PDF files.
    """
    def __init__(self, path, base_directory):

        # Validate and initialize file paths
        if not os.path.exists(path):
            raise ValueError(f"File {path} does not exist")
        if not os.path.exists(base_directory):
            raise ValueError(f"Basedirectory {base_directory} does not exist")
        self.file_name = os.path.basename(path)
        self.folder_path_abs = os.path.dirname(os.path.abspath(path))
        self.base_directory_abs = os.path.abspath(base_directory)
        self.relative_path = os.path.relpath(self.folder_path_abs, self.base_directory_abs)

        # Initialize parameters for analysis
        self.summary = ""
        self.summary_confidence = 0
        self.title = ""
        self.title_confidence = 0
        self.creation_date = ""
        self.creation_date_confidence = 0
        self.creator = ""
        self.creator_confidence = 0
        self.tags = []
        self.tags_confidence = []
        self.importance = None
        self.importance_confidence = 0

        # Analyze document
        self.modification_date = self.get_modification_date()
        self.pages = []
        self.images = []
        self.images_already_analyzed = False
        self.image_coverage = None
        self.pdf_text = ""

    def get_absolute_path(self):
        return os.path.join(self.folder_path_abs, self.file_name)

    # Get text stored inside the document
    def get_pdf_text(self):
        if not self.pdf_text:
            self.pdf_text = self.read_ocr()
        return self.pdf_text
            

    def analyze_file(self):
        """
        Performs an analysis of the document. 
        It extracts the date, title, and tags from the document's filename and relative path.
        """
        # Extract the creation date from the file name
        self.extract_date_from_filename()

        # Extract the title from the file name
        self.extract_title_from_filename()

        # Extract tags from the relative path
        self.extract_tags_from_relative_path()

        # Extract useful information from Metadata
        self.extract_metadata()
 
    def save_to_file(self, new_file_path):
        """
        Saves the current state of the PDF document to a new file.
        This includes updating the metadata based on the current attributes of the object.
        """
        # Ensure the directory for the new file exists
        os.makedirs(os.path.dirname(new_file_path), exist_ok=True)

        # Open the existing PDF document
        pdf_document = fitz.open(self.get_absolute_path())

        # Update the metadata of the PDF document
        metadata = pdf_document.metadata
        metadata['title'] = self.title
        metadata['summary'] = self.summary
        metadata['author'] = self.creator
        metadata['keywords'] = ', '.join(self.tags)

        # Storing additional information about confidences in keyword-list
        tags_confidence_str = ','.join([str(conf) for conf in self.tags_confidence])
        metadata['keywords'] = f"{metadata['keywords']} - Metadata automatically updated by autoPDFtagger, title_confidence={self.title_confidence}, summary_confidence={self.summary_confidence}, creation_date_confidence={self.creation_date_confidence}, creator_confidence={self.creator_confidence}, tag_confidence={tags_confidence_str}"

        if self.creation_date:
            # Konvertiere das Datum in das PDF-Format
            # Annahme: Die Zeitzone ist UTC
            utc_creation_date = self.creation_date.astimezone(pytz.utc)
            metadata['creationDate'] = utc_creation_date.strftime("D:%Y%m%d%H%M%S+00'00'")

        pdf_document.set_metadata(metadata)
       
        # Save the updated document to the new file path
        pdf_document.save(new_file_path)
        pdf_document.close()
        logging.info(f"PDF saved: {new_file_path}")


    def to_dict(self):
        """
        Converts the PDF document's data into a dictionary format.
        This includes paths, text content, metadata, and analyzed information.
        """
        pdf_dict = {
            "folder_path_abs": os.path.dirname(self.get_absolute_path()),
            "relative_path": self.relative_path,
            "base_directory_abs": self.base_directory_abs,
            "file_name": self.file_name,
            "summary": self.summary,
            "summary_confidence": self.summary_confidence,
            "title": self.title,
            "title_confidence": self.title_confidence,
            "creation_date": self.get_creation_date_as_str(),
            "creation_date_confidence": self.creation_date_confidence,
            "creator": self.creator,
            "creator_confidence": self.creator_confidence,
            "tags": self.tags,
            "tags_confidence": self.tags_confidence,
            "importance": self.importance,
            "importance_confidence": self.importance_confidence
        }
        return pdf_dict


    def to_api_json(self):
        """
        Converts selected attributes of the PDF document into a JSON string.
        This JSON representation can be used for API interactions.
        """
        return json.dumps({
            "summary": self.summary,
            "summary_confidence": self.summary_confidence,
            "title": self.title,
            "title_confidence": self.title_confidence,
            "creation_date": self.get_creation_date_as_str(),
            "creation_date_confidence": self.creation_date_confidence,
            "creator": self.creator,
            "creator_confidence": self.creator_confidence,
            "tags": self.tags,
            "tags_confidence": self.tags_confidence,
            "importance": self.importance,
            "importance_confidence": self.importance_confidence
        })

    def read_ocr(self):
        """
        Reads and extracts text from all pages of the PDF document.
        Cleans the text by removing non-readable characters and replacing line breaks.
        """
        try:
            pdf_document = fitz.open(self.get_absolute_path())

            # Initialize text extraction
            pdf_text = ""
            for page_num in range(len(pdf_document)):
                page = pdf_document[page_num]
                page_text = page.get_text("text")
                pdf_text += page_text

            # Clean text by removing unwanted characters and line breaks
            pdf_text = pdf_text.replace('\n', ' ').replace('\r', ' ')
            pdf_text = re.sub(r'[^\w\s.,:;/+\-]', '', pdf_text, flags=re.UNICODE)
            pdf_text = re.sub(r'\s+', ' ', pdf_text, flags=re.UNICODE).strip()

            pdf_document.close()
            #logging.debug(f"Extracted text from {self.file_name}:\n{self.pdf_text}\n----------------\n")
            return pdf_text

        except Exception as e:
            logging.error(f"Failed to extract text from {self.file_name}:\nError Message: {e}")
            return None


    def create_thumbnail(self, thumbnail_filename, max_width=64):
        """
        Creates a thumbnail image of the first page of the PDF document.
        The thumbnail is saved as a PNG image.
        """
        try:
            pdf_path = self.get_absolute_path()
            pdf_document = fitz.open(pdf_path)
            
            # Select the first page for the thumbnail
            page = pdf_document[0]

            # Create a pixmap object from the page and save as a PNG image
            pix = page.get_pixmap(dpi=50)
            pix.save(thumbnail_filename)
            pdf_document.close()

            logging.info(f"Thumbnail created: {thumbnail_filename}")
            return
        except Exception as e:
            logging.error(f"Error creating thumbnail: {e}")
            return None

    
    def get_png_image_base64_by_xref(self, xref):
        """
        Extracts a PNG image from the PDF using its xref (cross-reference) and encodes it in base64.
        This method is useful for extracting and transmitting images in a format suitable for web use.
        """
        logging.debug(f"Extracting Image {xref} from Document {self.file_name}")
        try:
            pdf_path = self.get_absolute_path()
            pdf_fitz = fitz.open(pdf_path)

            # Create a pixmap (image) object from the PDF based on the provided xref
            pix = fitz.Pixmap(pdf_fitz, xref)

            # Convert the pixmap object to PNG bytes and then encode to base64
            img_bytes = pix.tobytes("png")
            encoded_image = base64.b64encode(img_bytes).decode()

            pdf_fitz.close()
            logging.debug("Returning " + str(len(encoded_image)) + " character base_64")
            return encoded_image

        except Exception as e:
            logging.error(f"Error extracting PNG image by xref: {e}")
            return None


    def get_modification_date(self):
        try:
            modification_date = os.path.getmtime(self.get_absolute_path())
            modification_date = datetime.fromtimestamp(modification_date)
            return modification_date
        except Exception as e:
            return None

    def extract_date_from_filename(self):
        """
        Extracts the creation date from the file name using predefined regular expressions.
        Sets the creation date of the document if a matching date format is found.
        """
        for regex, date_format in date_formats.items():
            date_match = re.search(regex, self.file_name)
            if date_match:
                date_string = date_match.group()
                try:
                    # Parse the date string according to the matched format
                    date_object = datetime.strptime(date_string, date_format)
                    # Set the creation date with a high confidence level
                    self.set_creation_date(date_object.strftime("%Y-%m-%d"), 8)
                    return
                except ValueError:
                    # Continue searching if the current format does not match
                    continue

        # Return None if no date format matches
        return None


    def extract_title_from_filename(self):
        """
        Extracts the title from the file name by removing date information and unwanted characters.
        Sets the title of the document with a moderate confidence level.
        """
        # Remove date from the file name
        file_name = self.file_name
        for regex in date_formats:
            file_name = re.sub(regex, '', file_name).strip()

        # Remove additional characters and use the rest as the title
        file_name = re.sub(r'[^\w\s.-]', '', file_name)
        file_name = re.sub(r'^-|\.pdf$', '', file_name)

        # Set the extracted file name as the title
        self.set_title(file_name, 2)


    def extract_tags_from_relative_path(self):
        """
        Extracts tags from the relative path of the PDF file. 
        Tags are derived from the directory names in the path.
        Sets the extracted tags with a moderate confidence level.
        """
        # Split the relative path by the directory separator and clean up tags
        tags = self.relative_path.split(os.path.sep)
        tags = [tag.strip() for tag in tags if tag.strip()]  # Remove empty entries
        tags = [tag.strip() for tag in tags if tag != "."]
        # Set extracted tags if any are found
        if tags:
            self.tags = tags
            self.tags_confidence = [6] * len(tags)  # Moderate confidence for each tag

    def extract_metadata(self):
        """
        Extracts metadata such as title, summary, and keywords from the PDF document.
        Updates the class attributes based on the extracted metadata.
        """
        try:
            pdf_document = fitz.open(self.get_absolute_path())
            metadata = pdf_document.metadata

            # Default confidence value
            default_confidence = 5

            def extract_confidence(pattern, text, default_confidence):
                """Extracts a confidence value using regex or returns the default value."""
                match = re.search(pattern, text)
                return float(match.group(1)) if match else default_confidence


            # Extract confidence values
            keywords_raw = metadata.get('keywords', '')
            title_conf = extract_confidence(r"title_confidence=(\d+\.?\d*)", keywords_raw, default_confidence)
            summary_conf = extract_confidence(r"summary_confidence=(\d+\.?\d*)", keywords_raw, default_confidence)
            creation_date_conf = extract_confidence(r"creation_date_confidence=(\d+\.?\d*)", keywords_raw, default_confidence)
            creator_conf = extract_confidence(r"creator_confidence=(\d+\.?\d*)", keywords_raw, default_confidence)
            tags_conf_match = re.search(r"tag_confidence=([\d,.]+)", keywords_raw)
            tags_conf_str = tags_conf_match.group(1) if tags_conf_match else None

            # Set metadata values if not empty
            if metadata.get('title'):
                self.set_title(metadata['title'], title_conf)
            if metadata.get('summary'):
                self.set_summary(metadata['summary'], summary_conf)
            if metadata.get('creationDate'):
                self.set_creation_date(metadata['creationDate'], creation_date_conf)
            if metadata.get('author'):
                self.set_creator(metadata['author'], creator_conf)

            # Process tag confidence values
            tag_section, _, _ = keywords_raw.partition(' - Metadata automatically updated')
            tag_candidates = [tag.strip() for tag in tag_section.split(',') if tag.strip()]

            if tag_candidates:
                if tags_conf_str:
                    tag_confidences = [float(conf) for conf in tags_conf_str.split(',') if conf]
                else:
                    tag_confidences = []

                if len(tag_confidences) < len(tag_candidates):
                    tag_confidences.extend([default_confidence] * (len(tag_candidates) - len(tag_confidences)))
                elif len(tag_confidences) > len(tag_candidates):
                    tag_confidences = tag_confidences[:len(tag_candidates)]

                if not tag_confidences:
                    tag_confidences = [default_confidence] * len(tag_candidates)

                self.set_tags(tag_candidates, tag_confidences)

            pdf_document.close()

        except Exception as e:
            logging.error(f"Error extracting metadata from {self.file_name}: {e}")
            traceback.print_exc()


    def analyze_document_images(self):
        """
        Analyzes images in the PDF document. It calculates the total image area and page area
        and counts the number of words on each page.
        """
        if self.images_already_analyzed:
            return
        
        pdf_path = self.get_absolute_path()
        pdf_document = fitz.open(pdf_path)

        self.images = []
        self.pages = []
        self.total_image_area = 0
        self.total_page_area = 0

        word_regex = re.compile(r'[a-zA-ZäöüÄÖÜß]{3,}')

        for page_num, page in enumerate(pdf_document):
            page_images, page_image_area, max_img_xref = self.analyze_page_images(page)
            page_data = self.analyze_page_data(page, page_num, max_img_xref)

            # Append image and page data to respective lists
            self.images.append(page_images)
            self.pages.append(page_data)

            # Accumulate total image and page areas
            self.total_image_area += page_image_area
            self.total_page_area += page_data['page_area']

            # Extract and count words on the page
            page_text = page.get_text("text")
            page_data['words_count'] = len(word_regex.findall(page_text))

        pdf_document.close()

        # Calculate the percentage of the document covered by images
        self.image_coverage = (self.total_image_area / self.total_page_area) * 100 if self.total_page_area > 0 else 0        
        self.images_already_analyzed = True


    def analyze_page_data(self, page, page_num, max_img_xref):
        """
        Analyzes basic data of a page such as dimensions and area.
        """
        page_area = page.rect.width * page.rect.height
        return {
            "page_number": page_num + 1,
            "width": page.rect.width,
            "height": page.rect.height,
            "page_area": page_area,
            "max_img_xref": max_img_xref
        }

    def analyze_page_images(self, page):
        """
        Analyzes images on a page, extracting details and calculating the total image area.
        """
        page_images = []
        page_image_area = 0
        images = page.get_images(full=True)
        max_img_area = 0
        max_img_xref = None

        for img in images:
            image_data = self.extract_image_data(page, img)
            page_images.append(image_data)
            page_image_area += image_data['area']

            # Überprüfe, ob dieses Bild die größte Flächenabdeckung hat
            if image_data['area'] > max_img_area:
                max_img_area = image_data['area']
                max_img_xref = image_data['xref']

        return page_images, page_image_area, max_img_xref

    def extract_image_data(self, page, img):
        """
        Extracts data of a single image, including dimensions, area, and coverage percentage.
        """
        xref, img_area, rect = img[0], 0, None
        img_rects = page.get_image_rects(xref)
        if img_rects:
            rect = img_rects[0]
            img_area = rect.width * rect.height

        pix = fitz.Pixmap(page.parent, xref)
        page_area = page.rect.width * page.rect.height
        return {
            "xref": xref,
            "width": rect.width if rect else 0,
            "height": rect.height if rect else 0,
            "original_width": pix.width,
            "original_height": pix.height,
            "area": img_area,
            "page_coverage_percent": (img_area / page_area) * 100 if rect and page_area else 0
        }
   


    def set_title(self, title, confidence):
        """
        Sets the title of the document with a given confidence level.
        The title is updated only if the new confidence level is equal to or higher than the current level.
        """
        if confidence >= self.title_confidence:
            self.title = title
            self.title_confidence = confidence
        else: logging.info("Title not set due to lower confidence-level")

    def set_creation_date(self, creation_date, confidence):
        """
        Sets the creation date of the document with a given confidence level.
        The date is validated against predefined formats and updated only if the new confidence is high enough.
        """
        if not creation_date:
            self.creation_date = None
            return
        
        date_obj = None

        if isinstance(creation_date, datetime):
            date_obj = creation_date
        elif isinstance(creation_date, str):
            creation_date = creation_date.strip()
            for regex, date_format in date_formats.items():
                if re.match(regex, creation_date):
                    try:
                        date_obj = datetime.strptime(creation_date, date_format)
                        break
                    except ValueError:
                        continue  # Try the next format if the current one does not match

            if date_obj is None and creation_date.startswith("D:"):
                date_obj = pdf_date_to_datetime(creation_date)

        if date_obj:
            if isinstance(date_obj, datetime) and date_obj.tzinfo:
                date_obj = date_obj.astimezone(pytz.utc).replace(tzinfo=None)
            if confidence >= self.creation_date_confidence:
                self.creation_date = date_obj
                self.creation_date_confidence = confidence
            else: logging.info("Creation date not set due to lower confidence-level")
        

        
    def set_summary(self, summary, confidence):
        """
        Sets the summary of the document with a given confidence level.
        The summary is updated only if the new confidence level is equal to or higher than the current level.
        """
        if confidence >= self.summary_confidence:
            self.summary = summary
            self.summary_confidence = confidence
        else: logging.info("Summary not set due to lower confidence-level")

    def set_creator(self, creator, confidence):
        """
        Sets the creator of the document with a given confidence level.
        The creator is updated only if the new confidence level is equal to or higher than the current level.
        """
        if confidence >= self.creator_confidence:
            self.creator = creator
            self.creator_confidence = confidence
        
        else: logging.info("Creator not set due to lower confidence-level")

    def set_importance(self, importance, confidence):
        """
        Sets the importance of the document with a given confidence level.
        The importance is updated only if the new confidence level is equal to or higher than the current level.
        """
        if confidence >= self.importance_confidence:
            self.importance = importance
            self.importance_confidence = confidence
        else: logging.info("Importance not set due to lower confidence-level")

    def set_tags(self, tag_list, confidence_list):
        """
        Sets tags for the document with corresponding confidence levels.
        Duplicates are merged by taking the highest confidence.
        """
        if len(tag_list) != len(confidence_list):
            raise ValueError("Length of tag_list and confidence_list must be equal.")

        # Start with existing tag state to preserve earlier entries
        tag_conf_map = {}
        for index, existing_tag in enumerate(self.tags):
            if not existing_tag:
                continue
            existing_conf = self.tags_confidence[index] if index < len(self.tags_confidence) else 0
            current_conf = tag_conf_map.get(existing_tag, existing_conf)
            tag_conf_map[existing_tag] = max(current_conf, existing_conf)

        # Merge incoming tags, keeping best confidence per tag
        for tag, confidence in zip(tag_list, confidence_list):
            if not tag:
                continue
            existing_conf = tag_conf_map.get(tag)
            if existing_conf is None or confidence >= existing_conf:
                tag_conf_map[tag] = confidence if existing_conf is None else max(existing_conf, confidence)

        self.tags = list(tag_conf_map.keys())
        self.tags_confidence = [tag_conf_map[tag] for tag in self.tags]

    def set_from_json(self, input_json):
        """
        Updates the PDFDocument object's attributes from a JSON string.
        The JSON string should represent a dictionary of attribute values.
        """
        try:
            # Convert the JSON string into a Python dictionary
            input_dict = json.loads(input_json)

            # Update values in the PDFDocument object using the dictionary
            self.set_from_dict(input_dict)
            return True
        except Exception as e:
            logging.error(f"Error while processing the JSON string: {e}")
            traceback.print_exc()
            return None


    def set_from_dict(self, input_dict):
        """
        Updates the attributes of the PDFDocument object from a given dictionary.
        The dictionary should contain key-value pairs corresponding to the attributes of the PDFDocument.
        """

        # Update the title if provided in the input dictionary
        if 'title' in input_dict and 'title_confidence' in input_dict:
            self.set_title(input_dict['title'], input_dict['title_confidence'])

        # Update the summary if provided in the input dictionary
        if 'summary' in input_dict and 'summary_confidence' in input_dict:
            self.set_summary(input_dict['summary'], input_dict['summary_confidence'])

        # Update the creation date if provided in the input dictionary
        if 'creation_date' in input_dict and 'creation_date_confidence' in input_dict:
            self.set_creation_date(input_dict['creation_date'], input_dict['creation_date_confidence'])

        # Update the creator if provided in the input dictionary
        if 'creator' in input_dict and 'creator_confidence' in input_dict:
            self.set_creator(input_dict['creator'], input_dict['creator_confidence'])


        # Update the importance if provided in the input dictionary
        if 'importance' in input_dict and 'importance_confidence' in input_dict:
            self.set_importance(input_dict['importance'], input_dict['importance_confidence'])

        # Update the tags if provided in the input dictionary
        if 'tags' in input_dict and 'tags_confidence' in input_dict:
            self.set_tags(input_dict['tags'], input_dict['tags_confidence'])



    def get_confidence_if_tag_exists(self, tag):
        """
        Returns the confidence level of a given tag if it exists in the tags list.
        Returns False if the tag is not present.
        """
        if tag in self.tags:
            index = self.tags.index(tag)
            return self.tags_confidence[index]
        return False

    # Calculate a single number to represent the overall confidence
    # of the documents metadata to be uses to sort and filter documents. 
    # In the future we need to find a more sophisticated method...
    def get_confidence_index(self):
        # Tage average of all confidences excluding tags
        average = (
            self.creation_date_confidence
            + self.title_confidence
            + self.summary_confidence
            + self.importance_confidence
            + self.creator_confidence
        ) / 5
        # Title and creation date are most relevant, they define the lower limit
        return min(average, self.title_confidence, self.creation_date_confidence)

    def add_parent_tags_recursive(self, tag_hierarchy: dict):
        """
        Recursively adds parent tags from a tag hierarchy.
        The hierarchy should be provided in a nested dictionary format.
        Returns the highest confidence level found in the hierarchy.
        """
        confidence = 0
        for tag in tag_hierarchy: 
            # Recursively process the child tags
            confidence_new = self.add_parent_tags_recursive(tag_hierarchy[tag])
            if confidence_new:
                self.set_tags([tag], [confidence_new])
            # Update the confidence level with the highest value
            confidence = max(confidence_new, confidence, self.get_confidence_if_tag_exists(tag))
        return confidence

    def apply_tag_replacements(self, replacements):
        """
        Applies tag replacements based on a given replacement mapping.
        The method updates tags, their confidence, and specificity values accordingly.
        """
        # Create a mapping from original to new tags, ignoring empty replacements
        replacement_dict = {rep['original']: rep['replacement'] for rep in replacements}

        # Structure to store the updated confidence and specificity for each tag
        tag_info = {}

        for i, tag in enumerate(self.tags):
            # Determine the new tag, default to the original tag if no replacement is found
            new_tag = replacement_dict.get(tag, tag)
            if new_tag != "": 
                # Access or default confidence and specificity values
                confidence = self.tags_confidence[i] if i < len(self.tags_confidence) else 0

                # Update with the latest values for confidence and specificity
                tag_info[new_tag] = {
                    'confidence': confidence
                }

        # Update the class attributes with the final lists
        self.tags = list(tag_info.keys())
        self.tags_confidence = [info['confidence'] for info in tag_info.values()]
        
    def get_short_description(self):
        return (
            "Filename: " + self.file_name + ", "
            + "Path: " + self.relative_path + "\n"
            + "Content: " + self.get_pdf_text()
        )

    def has_sufficient_information(self, threshold=7): 
        return self.get_confidence_index() >= threshold
    
    def get_creation_date_as_str(self):
        return self.creation_date.strftime("%Y-%m-%d") if self.creation_date else None
    
    def get_image_number(self): 
        self.analyze_document_images()
        return len(self.images)

    def create_new_filename(self, format_str="%Y-%m-%d-{CREATOR}-{TITLE}.pdf"):
        """
        Creates a new filename based on a specified format.
        The format can include date formatting strings and {TITLE} as a placeholder for the document title.
        If no format is provided, the default format "YY-MM-DD-{TITLE}.pdf" is used.
        """
        # Replace date parts in the format with the actual date
        if self.creation_date:
            date_str = self.creation_date.strftime(format_str)
        else:
            # If no creation date is available, use the modification date
            date_str = self.modification_date.strftime(format_str)

        # Replace {TITLE} with the document title
        new_filename = date_str.replace('{TITLE}', self.title)
        new_filename = new_filename.replace('{CREATOR}', self.creator)
        # Store the new filename
        self.new_file_name = new_filename
        return self

def pdf_date_to_datetime(pdf_date):
    """
    Converts a PDF date format to a Python datetime object.
    Example of a PDF date: "D:20150919085148Z00'00'"
    """
    # Remove the leading 'D:' and any apostrophes
    date_str = re.sub(r'D:|\'+', '', pdf_date)

    # Try to parse the date in the PDF format
    try:
        # Assume the date is in UTC if no timezone is specified
        if 'Z' in date_str:
            date_str = date_str.replace('Z', '+0000')
            return datetime.strptime(date_str, "%Y%m%d%H%M%S%z")
        else:
            return datetime.strptime(date_str, "%Y%m%d%H%M%S")
    except ValueError:
        print(f"Error parsing date: {pdf_date}")
        return None
