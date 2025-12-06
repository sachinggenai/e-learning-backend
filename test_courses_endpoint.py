import requests

try:
    response = requests.get("http://localhost:8000/api/v1/courses", timeout=10)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text[:500]}")
except Exception as e:
    print(f"Error: {e}")
