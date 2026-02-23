import os
import tempfile
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Request, Header
from fastapi.responses import JSONResponse
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError

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


def extract_text_from_pdf(file_path: str) -> str:
    """
    Extract text from PDF using Azure Document Intelligence.
    Processes each page and accumulates the results.
    
    Args:
        file_path: Path to the PDF file
        
    Returns:
        Extracted text from all pages
    """
    client = get_azure_client()
    
    try:
        # Read the PDF file
        with open(file_path, "rb") as f:
            # Use prebuilt-read model for OCR
            poller = client.begin_analyze_document(
                "prebuilt-read",
                body=f,
                content_type="application/pdf"
            )
            result = poller.result()
        
        # Accumulate text from all pages
        accumulated_text = []
        
        if result.pages:
            logger.info(f"Processing {len(result.pages)} pages")
            
            for page in result.pages:
                page_text = []
                page_text.append(f"\n--- Page {page.page_number} ---\n")
                
                # Extract text from lines on this page
                if page.lines:
                    for line in page.lines:
                        page_text.append(line.content)
                
                accumulated_text.append("\n".join(page_text))
        
        # Join all page texts
        final_text = "\n".join(accumulated_text)
        
        logger.info(f"Successfully extracted {len(final_text)} characters from PDF")
        return final_text
        
    except HttpResponseError as e:
        logger.error(f"Azure API error: {e}")
        raise HTTPException(status_code=500, detail=f"Azure API error: {str(e)}")
    except Exception as e:
        logger.error(f"Error processing PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {str(e)}")


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
        
        # Extract text from PDF
        extracted_text = extract_text_from_pdf(temp_file_path)
        
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
