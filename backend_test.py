#!/usr/bin/env python3
"""
Backend API Testing for SET Academic Chatbot
Tests all endpoints with proper authentication and role-based access
"""

import requests
import sys
import json
from datetime import datetime
from typing import Dict, Any, Optional

class AcademicChatbotTester:
    def __init__(self, base_url="https://voice-text-assistant-1.preview.emergentagent.com/api"):
        self.base_url = base_url
        self.admin_token = None
        self.faculty_token = None
        self.student_token = None
        self.tests_run = 0
        self.tests_passed = 0
        self.session_id = None
        self.document_id = None

    def log_test(self, name: str, success: bool, details: str = ""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name}")
        else:
            print(f"❌ {name} - {details}")

    def make_request(self, method: str, endpoint: str, data: Dict[Any, Any] = None, 
                    token: str = None, files: Dict[str, Any] = None) -> tuple[bool, Dict[Any, Any], int]:
        """Make HTTP request with proper error handling"""
        url = f"{self.base_url}/{endpoint}"
        headers = {'Content-Type': 'application/json'}
        
        if token:
            headers['Authorization'] = f'Bearer {token}'
        
        if files:
            # Remove Content-Type for file uploads
            headers.pop('Content-Type', None)

        try:
            if method == 'GET':
                response = requests.get(url, headers=headers)
            elif method == 'POST':
                if files:
                    response = requests.post(url, data=data, files=files, headers=headers)
                else:
                    response = requests.post(url, json=data, headers=headers)
            elif method == 'PATCH':
                response = requests.patch(url, json=data, headers=headers)
            elif method == 'DELETE':
                response = requests.delete(url, headers=headers)
            else:
                return False, {"error": f"Unsupported method: {method}"}, 0

            try:
                response_data = response.json()
            except:
                response_data = {"text": response.text}

            return response.status_code < 400, response_data, response.status_code

        except Exception as e:
            return False, {"error": str(e)}, 0

    def test_health_check(self):
        """Test API health endpoints"""
        print("\n🔍 Testing Health Endpoints...")
        
        # Test root endpoint
        success, data, status = self.make_request('GET', '')
        self.log_test("Root endpoint", success and status == 200, 
                     f"Status: {status}, Data: {data}")
        
        # Test health endpoint
        success, data, status = self.make_request('GET', 'health')
        self.log_test("Health check", success and status == 200, 
                     f"Status: {status}, Data: {data}")

    def test_authentication(self):
        """Test authentication endpoints"""
        print("\n🔍 Testing Authentication...")
        
        # Test admin login
        admin_data = {
            "email": "admin@krmu.edu.in",
            "password": "Admin123!"
        }
        success, data, status = self.make_request('POST', 'auth/login', admin_data)
        if success and 'access_token' in data:
            self.admin_token = data['access_token']
            self.log_test("Admin login", True)
        else:
            self.log_test("Admin login", False, f"Status: {status}, Data: {data}")

        # Test register new user (student)
        timestamp = datetime.now().strftime("%H%M%S")
        student_data = {
            "name": f"Test Student {timestamp}",
            "email": f"student{timestamp}@test.com",
            "password": "TestPass123!",
            "role": "student"
        }
        success, data, status = self.make_request('POST', 'auth/register', student_data)
        if success and 'access_token' in data:
            self.student_token = data['access_token']
            self.log_test("Student registration", True)
        else:
            self.log_test("Student registration", False, f"Status: {status}, Data: {data}")

        # Test register faculty user
        faculty_data = {
            "name": f"Test Faculty {timestamp}",
            "email": f"faculty{timestamp}@test.com",
            "password": "TestPass123!",
            "role": "faculty"
        }
        success, data, status = self.make_request('POST', 'auth/register', faculty_data)
        if success and 'access_token' in data:
            self.faculty_token = data['access_token']
            self.log_test("Faculty registration", True)
        else:
            self.log_test("Faculty registration", False, f"Status: {status}, Data: {data}")

        # Test get profile with admin token
        if self.admin_token:
            success, data, status = self.make_request('GET', 'auth/me', token=self.admin_token)
            self.log_test("Get admin profile", success and data.get('role') == 'admin',
                         f"Status: {status}, Role: {data.get('role')}")

    def test_chat_functionality(self):
        """Test chat endpoints"""
        print("\n🔍 Testing Chat Functionality...")
        
        if not self.student_token:
            print("❌ No student token available for chat testing")
            return

        # Test chat message
        chat_data = {
            "message": "What are the admission requirements for SET?",
            "voice_input": False
        }
        success, data, status = self.make_request('POST', 'chat', chat_data, self.student_token)
        if success and 'response' in data:
            self.session_id = data.get('session_id')
            self.log_test("Send chat message", True)
        else:
            self.log_test("Send chat message", False, f"Status: {status}, Data: {data}")

        # Test voice chat message
        voice_chat_data = {
            "message": "Tell me about the faculty",
            "voice_input": True,
            "session_id": self.session_id
        }
        success, data, status = self.make_request('POST', 'chat', voice_chat_data, self.student_token)
        self.log_test("Send voice chat message", success and 'response' in data,
                     f"Status: {status}")

        # Test get chat sessions
        success, data, status = self.make_request('GET', 'chat/sessions', token=self.student_token)
        self.log_test("Get chat sessions", success and 'sessions' in data,
                     f"Status: {status}")

        # Test get specific session
        if self.session_id:
            success, data, status = self.make_request('GET', f'chat/sessions/{self.session_id}', 
                                                    token=self.student_token)
            self.log_test("Get specific chat session", success and 'messages' in data,
                         f"Status: {status}")

    def test_document_management(self):
        """Test document management endpoints"""
        print("\n🔍 Testing Document Management...")
        
        if not self.faculty_token:
            print("❌ No faculty token available for document testing")
            return

        # Test document upload (simulate with text file)
        test_content = "This is a test document for SET Academic Chatbot testing."
        files = {'file': ('test_document.txt', test_content, 'text/plain')}
        form_data = {
            'title': 'Test Document',
            'description': 'A test document for API testing'
        }
        
        success, data, status = self.make_request('POST', 'documents/upload', 
                                                form_data, self.faculty_token, files)
        if success and 'document_id' in data:
            self.document_id = data['document_id']
            self.log_test("Upload document", True)
        else:
            self.log_test("Upload document", False, f"Status: {status}, Data: {data}")

        # Test URL scraping
        url_data = {
            "url": "https://example.com",
            "title": "Example Website",
            "description": "Test URL scraping"
        }
        success, data, status = self.make_request('POST', 'documents/url', url_data, self.faculty_token)
        self.log_test("URL scraping", success and 'document_id' in data,
                     f"Status: {status}")

        # Test list documents
        success, data, status = self.make_request('GET', 'documents', token=self.faculty_token)
        self.log_test("List documents", success and isinstance(data, list),
                     f"Status: {status}")

        # Test student access to document upload (should fail)
        if self.student_token:
            success, data, status = self.make_request('POST', 'documents/upload', 
                                                    form_data, self.student_token, files)
            self.log_test("Student document upload (should fail)", not success and status == 403,
                         f"Status: {status}")

    def test_analytics(self):
        """Test analytics endpoints"""
        print("\n🔍 Testing Analytics...")
        
        if not self.faculty_token:
            print("❌ No faculty token available for analytics testing")
            return

        # Test analytics overview
        success, data, status = self.make_request('GET', 'analytics/overview', token=self.faculty_token)
        self.log_test("Analytics overview", success and 'total_queries' in data,
                     f"Status: {status}")

        # Test daily analytics
        success, data, status = self.make_request('GET', 'analytics/daily?days=7', token=self.faculty_token)
        self.log_test("Daily analytics", success and 'stats' in data,
                     f"Status: {status}")

        # Test student access to analytics (should fail)
        if self.student_token:
            success, data, status = self.make_request('GET', 'analytics/overview', token=self.student_token)
            self.log_test("Student analytics access (should fail)", not success and status == 403,
                         f"Status: {status}")

    def test_user_management(self):
        """Test user management endpoints (admin only)"""
        print("\n🔍 Testing User Management...")
        
        if not self.admin_token:
            print("❌ No admin token available for user management testing")
            return

        # Test list users
        success, data, status = self.make_request('GET', 'admin/users', token=self.admin_token)
        users = data.get('users', []) if success else []
        self.log_test("List users", success and 'users' in data,
                     f"Status: {status}, Users count: {len(users)}")

        # Test update user role (if we have users)
        if users and len(users) > 0:
            test_user = users[0]
            user_id = test_user['id']
            current_role = test_user['role']
            new_role = 'faculty' if current_role == 'student' else 'student'
            
            success, data, status = self.make_request('PATCH', f'admin/users/{user_id}/role?role={new_role}', 
                                                    token=self.admin_token)
            self.log_test("Update user role", success,
                         f"Status: {status}")

        # Test faculty access to user management (should fail)
        if self.faculty_token:
            success, data, status = self.make_request('GET', 'admin/users', token=self.faculty_token)
            self.log_test("Faculty user management access (should fail)", not success and status == 403,
                         f"Status: {status}")

    def test_role_based_access(self):
        """Test role-based access control"""
        print("\n🔍 Testing Role-Based Access Control...")
        
        # Test unauthorized access
        success, data, status = self.make_request('GET', 'auth/me')
        self.log_test("Unauthorized access (should fail)", not success and status == 401,
                     f"Status: {status}")

        # Test invalid token
        success, data, status = self.make_request('GET', 'auth/me', token="invalid_token")
        self.log_test("Invalid token access (should fail)", not success and status == 401,
                     f"Status: {status}")

    def run_all_tests(self):
        """Run all test suites"""
        print("🚀 Starting SET Academic Chatbot API Tests")
        print(f"📍 Testing against: {self.base_url}")
        
        self.test_health_check()
        self.test_authentication()
        self.test_role_based_access()
        self.test_chat_functionality()
        self.test_document_management()
        self.test_analytics()
        self.test_user_management()
        
        print(f"\n📊 Test Results: {self.tests_passed}/{self.tests_run} passed")
        
        if self.tests_passed == self.tests_run:
            print("🎉 All tests passed!")
            return 0
        else:
            print(f"⚠️  {self.tests_run - self.tests_passed} tests failed")
            return 1

def main():
    tester = AcademicChatbotTester()
    return tester.run_all_tests()

if __name__ == "__main__":
    sys.exit(main())