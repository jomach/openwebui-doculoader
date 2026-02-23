import os
import tempfile
import logging
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, File, UploadFile, HTTPException, Request, Header
from fastapi.responses import JSONResponse
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError
from pypdf import PdfReader, PdfWriter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="OpenWebUI Document Loader",
    description="External document OCR service using Azure Document Intelligence",
    version="1.0.0"
)

# Azure Document Intelligence configuration
AZURE_ENDPOINT = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
AZURE_KEY = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY")
TEMP_DIR = os.getenv("TEMP_WORK_DIR", "/tmp/doculoader")

# Validate environment variables
if not AZURE_ENDPOINT:
    logger.warning("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT not set")
if not AZURE_KEY:
    logger.warning("AZURE_DOCUMENT_INTELLIGENCE_KEY not set")

# Ensure temp directory exists
Path(TEMP_DIR).mkdir(parents=True, exist_ok=True)


def get_azure_client() -> DocumentIntelligenceClient:
    """Create and return Azure Document Intelligence client."""
    if not AZURE_ENDPOINT or not AZURE_KEY:
        raise HTTPException(
            status_code=500,
            detail="Azure Document Intelligence credentials not configured"
        )
    
    return DocumentIntelligenceClient(
        endpoint=AZURE_ENDPOINT,
        credential=AzureKeyCredential(AZURE_KEY)
    )


def _is_page_empty(page) -> bool:
    """Return True if the page has no visible content (no text, no image/form XObjects)."""
    try:
        text = page.extract_text()
        if text and text.strip():
            return False
    except Exception:
        pass

    try:
        resources = page.get('/Resources')
        if resources:
            xobjects = resources.get('/XObject')
            if xobjects:
                return False
    except Exception:
        pass

    return True


def _is_landscape_page(page) -> bool:
    """Return True if the page renders in landscape orientation (effective width > height)."""
    width = float(page.mediabox.width)
    height = float(page.mediabox.height)
    rotation = page.rotation  # 0, 90, 180, or 270

    # A 90° or 270° /Rotate swaps the effective display dimensions
    if rotation in (90, 270):
        width, height = height, width

    return width > height


def split_pdf_by_pages(input_pdf_path: str, output_dir: str) -> List[str]:
    """
    Split a PDF into separate files, one per page.
    Empty pages are skipped. Landscape pages are rotated 90° to portrait
    so that OCR reads horizontal text correctly.

    Args:
        input_pdf_path: Path to the input PDF file
        output_dir: Directory to save the split pages

    Returns:
        List of paths to the split PDF files
    """
    page_files = []

    try:
        reader: PdfReader = PdfReader(input_pdf_path)
        total_pages = len(reader.pages)
        logger.info(f"Splitting PDF into {total_pages} pages")

        for page_num, page in enumerate(reader.pages, start=1):
            # Skip blank pages
            if _is_page_empty(page):
                logger.info(f"Skipping empty page {page_num}")
                continue

            # Create a new PDF with just this page
            writer = PdfWriter()
            writer.add_page(page)

            # Rotate landscape pages to portrait for correct OCR orientation
            if _is_landscape_page(page):
                w = float(page.mediabox.width)
                h = float(page.mediabox.height)
                logger.info(
                    f"Page {page_num} is landscape ({w:.0f}×{h:.0f}), rotating 90° to portrait"
                )
                writer.pages[0].rotate(90)

            # Save the page as a separate PDF
            page_file_path = os.path.join(output_dir, f"page_{page_num}.pdf")
            with open(page_file_path, "wb") as output_file:
                writer.write(output_file)

            page_files.append(page_file_path)
            logger.info(f"Created page file: {page_file_path}")

        return page_files

    except Exception as e:
        logger.error(f"Error splitting PDF: {e}")
        raise Exception(f"Error splitting PDF: {str(e)}")


def extract_text_from_pdf(file_path: str) -> str:
    """
    Extract text from a single-page PDF using Azure Document Intelligence.
    
    Args:
        file_path: Path to the PDF file (should be a single page)
        
    Returns:
        Extracted text from the page
    """
    client = get_azure_client()
    
    try:
        # Read the PDF file as bytes
        with open(file_path, "rb") as f:
            pdf_bytes = f.read()
        # Use prebuilt-read model for OCR
        poller = client.begin_analyze_document(
            "prebuilt-read",
            body=pdf_bytes,
            content_type="application/pdf"
        )
        result = poller.result()
        
        # Extract text from the page
        page_text = []
        
        if result.pages:
            for page in result.pages:
                # Extract text from lines on this page
                if page.lines:
                    for line in page.lines:
                        page_text.append(line.content)
        
        return "\n".join(page_text)
        
    except HttpResponseError as e:
        logger.error(f"Azure API error: {e}")
        raise HTTPException(status_code=500, detail=f"Azure API error: {str(e)}")
    except Exception as e:
        logger.error(f"Error processing PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {str(e)}")


def process_pdf_pages(input_pdf_path: str) -> str:
    """
    Process a multi-page PDF by splitting it into individual pages,
    sending each page to Azure Document Intelligence, and aggregating results.
    
    Args:
        input_pdf_path: Path to the input PDF file
        
    Returns:
        Aggregated text from all pages
    """
    # Create temporary directory for page files
    temp_page_dir = tempfile.mkdtemp(dir=TEMP_DIR, prefix="pages_")
    page_files = []
    
    try:
        # Split PDF into individual page files
        page_files = split_pdf_by_pages(input_pdf_path, temp_page_dir)
        
        # Process each page file separately
        accumulated_text = []
        
        for i, page_file in enumerate(page_files, start=1):
            logger.info(f"Processing page {i} of {len(page_files)}")
            
            # Extract text from this single page
            page_text = extract_text_from_pdf(page_file)
            
            # Add page separator and content
            accumulated_text.append(f"\n--- Page {i} ---\n")
            accumulated_text.append(page_text)
        
        # Join all page texts
        final_text = "\n".join(accumulated_text)
        
        logger.info(f"Successfully processed {len(page_files)} pages, extracted {len(final_text)} characters")
        return final_text
        
    finally:
        # Clean up all page files
        for page_file in page_files:
            try:
                if os.path.exists(page_file):
                    os.unlink(page_file)
            except Exception as e:
                logger.warning(f"Failed to clean up page file {page_file}: {e}")
        
        # Remove temporary page directory
        try:
            if os.path.exists(temp_page_dir):
                os.rmdir(temp_page_dir)
        except Exception as e:
            logger.warning(f"Failed to remove temp page directory {temp_page_dir}: {e}")


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "OpenWebUI Document Loader",
        "azure_configured": bool(AZURE_ENDPOINT and AZURE_KEY)
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "azure_configured": bool(AZURE_ENDPOINT and AZURE_KEY)
    }


@app.put("/process")
async def process_document(
    request: Request,
    content_type: Optional[str] = Header(None),
    x_filename: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
):
    """
    Process uploaded document using Azure Document Intelligence.
    Compatible with Open Web UI external document extraction format.
    
    This endpoint expects raw PDF data in the request body (not multipart form).
    
    Args:
        request: FastAPI request object with PDF data in body
        content_type: Content-Type header
        x_filename: X-Filename header with the original filename
        authorization: Authorization header (Bearer token)
        
    Returns:
        JSON response with page_content and metadata
    """
    # Read raw body data
    pdf_data = await request.body()
    
    if not pdf_data:
        raise HTTPException(
            status_code=400,
            detail="No file data provided"
        )
    
    # Extract filename from header or use default
    filename = x_filename or "document.pdf"
    
    # Validate it's a PDF (basic check)
    if not filename.lower().endswith('.pdf'):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are supported"
        )
    
    # Create temporary file for processing
    temp_file_path = None
    try:
        # Save uploaded file to temporary location
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix='.pdf',
            dir=TEMP_DIR
        ) as temp_file:
            temp_file.write(pdf_data)
            temp_file_path = temp_file.name
            logger.info(f"Saved uploaded file to {temp_file_path} ({len(pdf_data)} bytes)")
        
        # Process PDF by splitting into pages and processing each page
        extracted_text = process_pdf_pages(temp_file_path)
        
        # Return in format compatible with Open Web UI
        # Client expects: {"page_content": "...", "metadata": {...}}
        return JSONResponse(
            content={
                "page_content": extracted_text,
                "metadata": {
                    "filename": filename,
                    "content_type": content_type or "application/pdf",
                    "engine": "azure-document-intelligence"
                }
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up temporary file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
                logger.info(f"Cleaned up temporary file {temp_file_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temporary file: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
