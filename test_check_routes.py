import requests

try:
    response = requests.get("http://127.0.0.1:8000/openapi.json", timeout=5)
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print(f"Paths available:")
        for path in sorted(data.get('paths', {}).keys()):
            if 'import' in path.lower():
                print(f"  {path}")
    else:
        print(response.text)
except Exception as e:
    print(f"Error: {e}")
