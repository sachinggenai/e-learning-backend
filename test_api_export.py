#!/usr/bin/env python3
"""
Test the actual export API endpoint
"""
import requests
import json
from pathlib import Path

def test_export_api():
    """Test the export API endpoint"""
    
    # Test course data matching the API expected format
    test_course_data = {
        "courseId": "api-test-001",
        "title": "API Export Test Course",
        "description": "Testing export through the API",
        "author": "API Test User",
        "language": "en",
        "version": "1.0.0",
        "templates": [
            {
                "id": "api-template-1",
                "type": "welcome",
                "title": "Welcome",
                "order": 0,
                "data": {
                    "content": "Welcome to our API test course!"
                }
            },
            {
                "id": "api-template-2",
                "type": "content-text",
                "title": "Learning Content",
                "order": 1,
                "data": {
                    "content": "This is some learning content delivered via API export."
                }
            }
        ]
    }
    
    # API endpoint
    api_url = "http://127.0.0.1:8002/api/v1/export"
    
    try:
        print("🔗 Testing Export API Endpoint...")
        print(f"📡 URL: {api_url}")
        
        # Make POST request
        response = requests.post(
            api_url,
            json=test_course_data,
            timeout=30,
            stream=True  # Important for downloading binary content
        )
        
        print(f"📊 Response Status: {response.status_code}")
        print(f"📋 Response Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            # Save the ZIP file
            output_file = Path("/tmp/api_test_export.zip")
            with open(output_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            file_size = output_file.stat().st_size
            print(f"✅ API Export Successful!")
            print(f"   📦 File: {output_file}")
            print(f"   📏 Size: {file_size:,} bytes")
            
            # Verify it's a valid ZIP
            import zipfile
            try:
                with zipfile.ZipFile(output_file, 'r') as zip_file:
                    file_list = zip_file.namelist()
                    print(f"   📋 ZIP Contents: {len(file_list)} files")
                    for file in sorted(file_list):
                        info = zip_file.getinfo(file)
                        print(f"      - {file} ({info.file_size} bytes)")
                return True
            except zipfile.BadZipFile:
                print("❌ Downloaded file is not a valid ZIP")
                return False
                
        else:
            print(f"❌ API Request Failed")
            print(f"   Response: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to API server")
        print("   Make sure the backend server is running on port 8002")
        return False
    except Exception as e:
        print(f"❌ API Test Error: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("🌐 E-Learning Export API Test")
    print("=" * 60)
    
    success = test_export_api()
    
    print("\n" + "=" * 60)
    if success:
        print("🎉 API EXPORT TEST PASSED!")
        print("✅ Export API is working correctly")
        print("✅ ZIP download through HTTP works")
        print("✅ End-to-end export functionality confirmed")
    else:
        print("❌ API EXPORT TEST FAILED")
        print("⚠️ Check that backend server is running and accessible")
        
    print("=" * 60)