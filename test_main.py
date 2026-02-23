"""
Pytest tests for OpenWebUI Document Loader API.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from main import app


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_azure_client():
    """Mock Azure Document Intelligence client."""
    with patch('main.get_azure_client') as mock:
        yield mock


def create_test_pdf_bytes():
    """Create a simple test PDF in bytes."""
    # Simple PDF structure
    pdf_content = b"""%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj
2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj
3 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
/Contents 4 0 R
/Resources <<
/Font <<
/F1 <<
/Type /Font
/Subtype /Type1
/BaseFont /Helvetica
>>
>>
>>
>>
endobj
4 0 obj
<<
/Length 44
>>
stream
BT
/F1 12 Tf
100 700 Td
(Test PDF) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000317 00000 n 
trailer
<<
/Size 5
/Root 1 0 R
>>
startxref
410
%%EOF"""
    return pdf_content


class TestHealthEndpoints:
    """Test health check endpoints."""
    
    def test_root_endpoint(self, client):
        """Test root endpoint returns health status."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "OpenWebUI Document Loader"
        assert "azure_configured" in data
    
    def test_health_endpoint(self, client):
        """Test health endpoint returns status."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "azure_configured" in data


class TestProcessEndpoint:
    """Test document processing endpoint."""
    
    def test_process_endpoint_without_credentials(self, client):
        """Test that endpoint returns error when Azure credentials not configured."""
        pdf_data = create_test_pdf_bytes()
        
        response = client.put(
            "/process",
            content=pdf_data,
            headers={
                "Content-Type": "application/pdf",
                "X-Filename": "test.pdf"
            }
        )
        
        # Should fail due to missing credentials
        assert response.status_code == 500
        assert "credentials" in response.json()["detail"].lower()
    
    def test_process_endpoint_with_mock_azure(self, client, mock_azure_client):
        """Test successful document processing with mocked Azure client."""
        # Mock Azure response
        mock_result = Mock()
        mock_page = Mock()
        mock_page.page_number = 1
        mock_line1 = Mock()
        mock_line1.content = "Test line 1"
        mock_line2 = Mock()
        mock_line2.content = "Test line 2"
        mock_page.lines = [mock_line1, mock_line2]
        mock_result.pages = [mock_page]
        
        mock_poller = Mock()
        mock_poller.result.return_value = mock_result
        
        mock_client_instance = Mock()
        mock_client_instance.begin_analyze_document.return_value = mock_poller
        mock_azure_client.return_value = mock_client_instance
        
        # Make request
        pdf_data = create_test_pdf_bytes()
        response = client.put(
            "/process",
            content=pdf_data,
            headers={
                "Content-Type": "application/pdf",
                "X-Filename": "test.pdf"
            }
        )
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert "page_content" in data
        assert "metadata" in data
        assert "Test line 1" in data["page_content"]
        assert "Test line 2" in data["page_content"]
        assert data["metadata"]["filename"] == "test.pdf"
        assert data["metadata"]["engine"] == "azure-document-intelligence"
    
    def test_process_endpoint_non_pdf(self, client):
        """Test that endpoint rejects non-PDF files."""
        text_data = b"This is not a PDF"
        
        response = client.put(
            "/process",
            content=text_data,
            headers={
                "Content-Type": "text/plain",
                "X-Filename": "test.txt"
            }
        )
        
        assert response.status_code == 400
        assert "Only PDF files are supported" in response.json()["detail"]
    
    def test_process_endpoint_no_filename(self, client, mock_azure_client):
        """Test processing without X-Filename header uses default."""
        # Mock Azure response
        mock_result = Mock()
        mock_page = Mock()
        mock_page.page_number = 1
        mock_line = Mock()
        mock_line.content = "Test content"
        mock_page.lines = [mock_line]
        mock_result.pages = [mock_page]
        
        mock_poller = Mock()
        mock_poller.result.return_value = mock_result
        
        mock_client_instance = Mock()
        mock_client_instance.begin_analyze_document.return_value = mock_poller
        mock_azure_client.return_value = mock_client_instance
        
        # Make request without X-Filename
        pdf_data = create_test_pdf_bytes()
        response = client.put(
            "/process",
            content=pdf_data,
            headers={"Content-Type": "application/pdf"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["metadata"]["filename"] == "document.pdf"
    
    def test_process_endpoint_empty_body(self, client):
        """Test that endpoint rejects empty body."""
        response = client.put(
            "/process",
            content=b"",
            headers={
                "Content-Type": "application/pdf",
                "X-Filename": "test.pdf"
            }
        )
        
        assert response.status_code == 400
        assert "No file data provided" in response.json()["detail"]
    
    def test_process_endpoint_with_authorization(self, client, mock_azure_client):
        """Test that endpoint accepts Authorization header."""
        # Mock Azure response
        mock_result = Mock()
        mock_page = Mock()
        mock_page.page_number = 1
        mock_line = Mock()
        mock_line.content = "Test"
        mock_page.lines = [mock_line]
        mock_result.pages = [mock_page]
        
        mock_poller = Mock()
        mock_poller.result.return_value = mock_result
        
        mock_client_instance = Mock()
        mock_client_instance.begin_analyze_document.return_value = mock_poller
        mock_azure_client.return_value = mock_client_instance
        
        # Make request with Authorization header
        pdf_data = create_test_pdf_bytes()
        response = client.put(
            "/process",
            content=pdf_data,
            headers={
                "Content-Type": "application/pdf",
                "X-Filename": "test.pdf",
                "Authorization": "Bearer test-token"
            }
        )
        
        assert response.status_code == 200


class TestMultiPageProcessing:
    """Test multi-page document processing."""
    
    def test_multiple_pages(self, client, mock_azure_client):
        """Test processing document with multiple pages."""
        # Mock Azure response with multiple pages
        mock_result = Mock()
        
        mock_page1 = Mock()
        mock_page1.page_number = 1
        mock_line1 = Mock()
        mock_line1.content = "Page 1 content"
        mock_page1.lines = [mock_line1]
        
        mock_page2 = Mock()
        mock_page2.page_number = 2
        mock_line2 = Mock()
        mock_line2.content = "Page 2 content"
        mock_page2.lines = [mock_line2]
        
        mock_page3 = Mock()
        mock_page3.page_number = 3
        mock_line3 = Mock()
        mock_line3.content = "Page 3 content"
        mock_page3.lines = [mock_line3]
        
        mock_result.pages = [mock_page1, mock_page2, mock_page3]
        
        mock_poller = Mock()
        mock_poller.result.return_value = mock_result
        
        mock_client_instance = Mock()
        mock_client_instance.begin_analyze_document.return_value = mock_poller
        mock_azure_client.return_value = mock_client_instance
        
        # Make request
        pdf_data = create_test_pdf_bytes()
        response = client.put(
            "/process",
            content=pdf_data,
            headers={
                "Content-Type": "application/pdf",
                "X-Filename": "multi-page.pdf"
            }
        )
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert "Page 1 content" in data["page_content"]
        assert "Page 2 content" in data["page_content"]
        assert "Page 3 content" in data["page_content"]
        assert "Page 1" in data["page_content"]
        assert "Page 2" in data["page_content"]
        assert "Page 3" in data["page_content"]
