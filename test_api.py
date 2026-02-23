#!/usr/bin/env python3
"""
Simple test script for the OpenWebUI Document Loader API.
Tests basic functionality without requiring actual Azure credentials.
"""

import sys
import requests
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter


def create_test_pdf():
    """Create a simple test PDF in memory."""
    pdf_buffer = io.BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=letter)
    
    # Page 1
    c.drawString(100, 750, "Test Document - Page 1")
    c.drawString(100, 700, "This is a test PDF for the document loader.")
    c.showPage()
    
    # Page 2
    c.drawString(100, 750, "Test Document - Page 2")
    c.drawString(100, 700, "This is the second page of the test document.")
    c.showPage()
    
    c.save()
    pdf_buffer.seek(0)
    return pdf_buffer


def test_health_endpoint(base_url):
    """Test the health check endpoint."""
    print("Testing health endpoint...")
    try:
        response = requests.get(f"{base_url}/health")
        response.raise_for_status()
        data = response.json()
        print(f"✓ Health check passed: {data}")
        return True
    except Exception as e:
        print(f"✗ Health check failed: {e}")
        return False


def test_root_endpoint(base_url):
    """Test the root endpoint."""
    print("\nTesting root endpoint...")
    try:
        response = requests.get(base_url)
        response.raise_for_status()
        data = response.json()
        print(f"✓ Root endpoint passed: {data}")
        return True
    except Exception as e:
        print(f"✗ Root endpoint failed: {e}")
        return False


def test_extract_endpoint(base_url, pdf_file=None):
    """Test the document extraction endpoint."""
    print("\nTesting document extraction endpoint...")
    
    try:
        if pdf_file:
            # Use provided PDF file
            with open(pdf_file, 'rb') as f:
                files = {'file': ('test.pdf', f, 'application/pdf')}
                response = requests.post(f"{base_url}/api/extract", files=files)
        else:
            # Create test PDF
            print("  Creating test PDF...")
            pdf_buffer = create_test_pdf()
            files = {'file': ('test.pdf', pdf_buffer, 'application/pdf')}
            response = requests.post(f"{base_url}/api/extract", files=files)
        
        if response.status_code == 200:
            data = response.json()
            print(f"✓ Extraction successful")
            print(f"  Extracted text length: {len(data.get('text', ''))} characters")
            print(f"  Metadata: {data.get('meta', {})}")
            
            # Show first 200 characters of extracted text
            text = data.get('text', '')
            if text:
                print(f"\n  Preview of extracted text:")
                print(f"  {text[:200]}{'...' if len(text) > 200 else ''}")
            return True
        elif response.status_code == 500 and "credentials not configured" in response.text:
            print(f"⚠ Extraction endpoint available but Azure credentials not configured")
            print(f"  This is expected if testing without Azure setup")
            return True
        else:
            print(f"✗ Extraction failed with status {response.status_code}")
            print(f"  Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"✗ Extraction test failed: {e}")
        return False


def test_invalid_file(base_url):
    """Test with invalid file type."""
    print("\nTesting invalid file type handling...")
    try:
        # Create a text file
        files = {'file': ('test.txt', io.BytesIO(b'not a pdf'), 'text/plain')}
        response = requests.post(f"{base_url}/api/extract", files=files)
        
        if response.status_code == 400:
            print(f"✓ Correctly rejected non-PDF file")
            return True
        else:
            print(f"✗ Expected 400 status code, got {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Invalid file test failed: {e}")
        return False


def main():
    """Run all tests."""
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    pdf_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    print(f"Testing OpenWebUI Document Loader at {base_url}")
    print("=" * 60)
    
    results = []
    results.append(test_health_endpoint(base_url))
    results.append(test_root_endpoint(base_url))
    results.append(test_extract_endpoint(base_url, pdf_file))
    results.append(test_invalid_file(base_url))
    
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Tests passed: {passed}/{total}")
    
    if passed == total:
        print("✓ All tests passed!")
        return 0
    else:
        print("✗ Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
