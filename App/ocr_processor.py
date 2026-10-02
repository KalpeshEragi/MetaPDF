"""
OCR Processor Module for MetaPDF
Handles scanned PDF detection and text extraction using EasyOCR
Novel contribution for research paper - supports hybrid text/scanned PDFs
"""

import os
import io
import re
from typing import List, Tuple, Optional
from PyPDF2 import PdfReader

# Lazy imports for OCR (loaded only when needed)
_ocr_reader = None

def _get_ocr_reader():
    """Lazy load EasyOCR reader for GPU efficiency"""
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        # Use GPU if available, English language
        _ocr_reader = easyocr.Reader(['en'], gpu=True)
    return _ocr_reader


def detect_pdf_type(pdf_path: str) -> str:
    """
    Detect if PDF is text-based, scanned, or mixed.
    
    Returns:
        "text" - PDF has extractable text
        "scanned" - PDF is image-based (needs OCR)
        "mixed" - PDF has both text and scanned pages
    """
    try:
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        text_pages = 0
        scanned_pages = 0
        
        for page in reader.pages:
            text = page.extract_text() or ""
            # Clean whitespace and check character count
            clean_text = re.sub(r'\s+', '', text)
            
            # If page has more than 50 non-whitespace characters, consider it text
            if len(clean_text) > 50:
                text_pages += 1
            else:
                scanned_pages += 1
        
        if scanned_pages == 0:
            return "text"
        elif text_pages == 0:
            return "scanned"
        else:
            return "mixed"
            
    except Exception as e:
        print(f"Error detecting PDF type: {e}")
        return "text"  # Default to text extraction


def extract_text_from_image(image) -> str:
    """Extract text from a single image using EasyOCR"""
    try:
        reader = _get_ocr_reader()
        # Run OCR on image
        results = reader.readtext(image)
        # Combine all detected text
        text = " ".join([result[1] for result in results])
        return text
    except Exception as e:
        print(f"OCR error: {e}")
        return ""


def extract_text_with_ocr(pdf_path: str, pages: Optional[List[int]] = None) -> List[str]:
    """
    Extract text from PDF using OCR.
    
    Args:
        pdf_path: Path to PDF file
        pages: Optional list of page numbers (1-indexed). If None, all pages.
    
    Returns:
        List of extracted text, one per page
    """
    try:
        from pdf2image import convert_from_path
        from PIL import Image
        import numpy as np
        
        # Convert PDF pages to images
        # Use poppler_path if on Windows and poppler not in PATH
        images = convert_from_path(pdf_path, dpi=200)
        
        extracted_text = []
        
        for i, image in enumerate(images):
            page_num = i + 1  # 1-indexed
            
            # Skip pages not in selection
            if pages is not None and page_num not in pages:
                continue
            
            # Convert PIL image to numpy array for EasyOCR
            image_np = np.array(image)
            
            # Extract text using OCR
            text = extract_text_from_image(image_np)
            extracted_text.append(text)
            
            print(f"OCR completed for page {page_num}")
        
        return extracted_text
        
    except Exception as e:
        print(f"Error in OCR extraction: {e}")
        return []


def extract_text_with_ocr_from_bytes(pdf_bytes: bytes) -> List[str]:
    """
    Extract text from PDF bytes using OCR.
    For use with file uploads (Flask file objects).
    
    Args:
        pdf_bytes: PDF file content as bytes
    
    Returns:
        List of extracted text, one per page
    """
    try:
        from pdf2image import convert_from_bytes
        import numpy as np
        
        # Convert PDF bytes to images
        images = convert_from_bytes(pdf_bytes, dpi=200)
        
        extracted_text = []
        
        for i, image in enumerate(images):
            # Convert PIL image to numpy array for EasyOCR
            image_np = np.array(image)
            
            # Extract text using OCR
            text = extract_text_from_image(image_np)
            extracted_text.append(text)
            
            print(f"OCR completed for page {i + 1}")
        
        return extracted_text
        
    except Exception as e:
        print(f"Error in OCR extraction from bytes: {e}")
        return []


def hybrid_extract(pdf_file) -> Tuple[str, bool]:
    """
    Smart extraction that combines PyPDF2 and OCR.
    Uses PyPDF2 for text pages, OCR for scanned pages.
    
    Args:
        pdf_file: File object or path to PDF
    
    Returns:
        Tuple of (extracted_text, ocr_was_used)
    """
    ocr_used = False
    combined_text = ""
    
    try:
        # Read PDF with PyPDF2 first
        if hasattr(pdf_file, 'read'):
            # It's a file object - read content
            content = pdf_file.read()
            pdf_file.seek(0)  # Reset for potential later use
            reader = PdfReader(io.BytesIO(content))
        else:
            # It's a path
            reader = PdfReader(pdf_file)
            content = None
        
        pages_text = []
        sparse_pages = []  # Pages that need OCR
        
        # First pass: try PyPDF2
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            clean_text = re.sub(r'\s+', ' ', text).strip()
            
            # Check if text is sufficient
            if len(clean_text) > 50:
                pages_text.append((i, clean_text, "pypdf"))
            else:
                sparse_pages.append(i)
                pages_text.append((i, "", "pending"))
        
        # Second pass: OCR for sparse pages
        if sparse_pages:
            ocr_used = True
            print(f"Using OCR for {len(sparse_pages)} pages: {[p+1 for p in sparse_pages]}")
            
            try:
                from pdf2image import convert_from_bytes, convert_from_path
                import numpy as np
                
                if content:
                    images = convert_from_bytes(content, dpi=200)
                else:
                    images = convert_from_path(pdf_file, dpi=200)
                
                for page_idx in sparse_pages:
                    if page_idx < len(images):
                        image_np = np.array(images[page_idx])
                        ocr_text = extract_text_from_image(image_np)
                        
                        # Update the page text
                        for j, (idx, _, source) in enumerate(pages_text):
                            if idx == page_idx:
                                pages_text[j] = (idx, ocr_text, "ocr")
                                break
                                
            except Exception as e:
                print(f"OCR fallback failed: {e}")
        
        # Combine all text
        combined_text = "\n\n".join([text for _, text, _ in pages_text if text])
        
        return combined_text, ocr_used
        
    except Exception as e:
        print(f"Hybrid extraction error: {e}")
        return "", False


def hybrid_extract_pages(pdf_file) -> Tuple[List[str], bool]:
    """
    Smart page-by-page extraction that combines PyPDF2 and OCR.
    Returns list of text per page.
    
    Args:
        pdf_file: File object or path to PDF
    
    Returns:
        Tuple of (list_of_page_texts, ocr_was_used)
    """
    ocr_used = False
    
    try:
        # Read PDF with PyPDF2 first
        if hasattr(pdf_file, 'read'):
            content = pdf_file.read()
            pdf_file.seek(0)
            reader = PdfReader(io.BytesIO(content))
        else:
            reader = PdfReader(pdf_file)
            content = None
        
        pages_text = []
        sparse_page_indices = []
        
        # First pass: try PyPDF2
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            clean_text = re.sub(r'\s+', ' ', text).strip()
            
            if len(clean_text) > 50:
                pages_text.append(clean_text)
            else:
                sparse_page_indices.append(i)
                pages_text.append("")  # Placeholder
        
        # Second pass: OCR for sparse pages
        if sparse_page_indices:
            ocr_used = True
            print(f"Using OCR for pages: {[p+1 for p in sparse_page_indices]}")
            
            try:
                from pdf2image import convert_from_bytes, convert_from_path
                import numpy as np
                
                if content:
                    images = convert_from_bytes(content, dpi=200)
                else:
                    images = convert_from_path(pdf_file, dpi=200)
                
                for page_idx in sparse_page_indices:
                    if page_idx < len(images):
                        image_np = np.array(images[page_idx])
                        ocr_text = extract_text_from_image(image_np)
                        pages_text[page_idx] = ocr_text
                        
            except Exception as e:
                print(f"OCR fallback failed: {e}")
        
        return pages_text, ocr_used
        
    except Exception as e:
        print(f"Hybrid page extraction error: {e}")
        return [], False
