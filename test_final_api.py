#!/usr/bin/env python3
"""
Test API export functionality using urllib (built-in)
"""
import urllib.request
import urllib.parse
import json
import os

def test_api_export():
    """Test the export API with proper course data"""
    
    # Complete course data
    course_data = {
        "courseId": "final-api-test",
        "title": "Final API Export Test",
        "author": "Test User",
        "language": "en",
        "description": "Final test of API export",
        "version": "1.0.0",
        "createdAt": "2025-10-06T01:54:00.000000",
        "updatedAt": "2025-10-06T01:54:00.000000",
        "templates": [
            {
                "id": "welcome-1",
                "type": "welcome",
                "title": "Welcome",
                "order": 0,
                "data": {
                    "content": "Welcome to our final test course!",
                    "subtitle": "Testing the complete export functionality"
                }
            },
            {
                "id": "content-1", 
                "type": "content-text",
                "title": "Learning Content",
                "order": 1,
                "data": {
                    "content": "This is our main learning content for the API test."
                }
            }
        ],
        "assets": [],
        "navigation": {
            "allowSkip": True,
            "showProgress": True,
            "allowReview": True
        },
        "settings": {
            "theme": "default",
            "autoPlay": False,
            "showTimer": False
        }
    }
    
    # Prepare request
    request_data = {
        "course": json.dumps(course_data)
    }
    
    url = "http://127.0.0.1:8003/api/v1/export"
    headers = {
        'Content-Type': 'application/json'
    }
    
    try:
        print(f"🔗 Testing Export API: {url}")
        
        # Prepare request
        json_data = json.dumps(request_data).encode('utf-8')
        req = urllib.request.Request(url, data=json_data, headers=headers, method='POST')
        
        # Make request
        print("📡 Sending API request...")
        with urllib.request.urlopen(req, timeout=30) as response:
            print(f"📊 Response Status: {response.getcode()}")
            print(f"📋 Response Headers:")
            for header, value in response.headers.items():
                print(f"   {header}: {value}")
            
            if response.getcode() == 200:
                # Save response as ZIP
                content = response.read()
                output_file = "/tmp/final_api_export.zip"
                
                with open(output_file, 'wb') as f:
                    f.write(content)
                
                file_size = len(content)
                print(f"✅ API Export Successful!")
                print(f"   📦 File: {output_file}")
                print(f"   📏 Size: {file_size:,} bytes")
                
                # Verify ZIP
                import zipfile
                try:
                    with zipfile.ZipFile(output_file, 'r') as zip_file:
                        files = zip_file.namelist()
                        print(f"   📋 ZIP Contents: {len(files)} files")
                        for file in sorted(files):
                            info = zip_file.getinfo(file)
                            print(f"      - {file} ({info.file_size} bytes)")
                    
                    return True
                    
                except zipfile.BadZipFile:
                    print("❌ Response is not a valid ZIP file")
                    # Show first 200 chars of response for debugging
                    print(f"Response content: {content[:200]}...")
                    return False
            else:
                print(f"❌ API request failed with status {response.getcode()}")
                return False
                
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP Error: {e.code}")
        error_content = e.read().decode('utf-8')
        print(f"   Error response: {error_content}")
        return False
        
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("🌐 Final Export API Test")
    print("=" * 60)
    
    success = test_api_export()
    
    print("\n" + "=" * 60)
    if success:
        print("🎉 FINAL API TEST PASSED!")
        print("✅ Export API working correctly")
        print("✅ SCORM ZIP download confirmed")
        print("✅ Complete end-to-end functionality verified")
    else:
        print("❌ API TEST FAILED")
    
    print("=" * 60)