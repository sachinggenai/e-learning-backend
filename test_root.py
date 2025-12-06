import requests

try:
    print("Attempting to connect to http://localhost:8000/")
    response = requests.get("http://localhost:8000/", timeout=5)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text[:200]}")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
