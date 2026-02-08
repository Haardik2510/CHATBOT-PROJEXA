import requests
import json
import time

BASE_URL = "http://localhost:8000"

def test_health():
    print("Testing health endpoint...")
    try:
        response = requests.get(f"{BASE_URL}/health")
        print("Health Check:", json.dumps(response.json(), indent=2))
        return response.status_code == 200
    except Exception as e:
        print(f"Health check failed: {e}")
        return False

def test_database_info():
    print("\nTesting database info...")
    try:
        response = requests.get(f"{BASE_URL}/database/info")
        print("Database Info:", json.dumps(response.json(), indent=2))
        return response.status_code == 200
    except Exception as e:
        print(f"Database info failed: {e}")
        return False

def test_list_documents():
    print("\nTesting list documents...")
    try:
        response = requests.get(f"{BASE_URL}/documents")
        print("Documents List:", json.dumps(response.json(), indent=2))
        return response.status_code == 200
    except Exception as e:
        print(f"List documents failed: {e}")
        return False

def test_upload():
    print("\nTesting document upload...")
    try:
        # Use the existing PDF file
        files = {'file': open('./data/documents/SSR-Prequalified-HRUNGN109306.pdf', 'rb')}
        response = requests.post(f"{BASE_URL}/upload", files=files)
        print("Upload Response:", json.dumps(response.json(), indent=2))
        return response.status_code == 200
    except Exception as e:
        print(f"Upload failed: {e}")
        return False

def test_query():
    print("\nTesting query...")
    try:
        payload = {
            "question": "What are the eligibility criteria for this program?",
            "university_id": "UNIV001",
            "document_type": "admission"
        }
        response = requests.post(f"{BASE_URL}/query", json=payload)
        print("Query Response:", json.dumps(response.json(), indent=2))
        return response.status_code == 200
    except Exception as e:
        print(f"Query failed: {e}")
        return False

if __name__ == "__main__":
    print("=" * 50)
    print("Testing University Document Chatbot API")
    print("=" * 50)
    
    # Wait a moment for server to start
    time.sleep(2)
    
    # Run tests
    all_tests_passed = True
    
    all_tests_passed = test_health() and all_tests_passed
    all_tests_passed = test_database_info() and all_tests_passed
    all_tests_passed = test_list_documents() and all_tests_passed
    all_tests_passed = test_upload() and all_tests_passed
    all_tests_passed = test_query() and all_tests_passed
    
    print("\n" + "=" * 50)
    if all_tests_passed:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed!")
    print("=" * 50)