import zipfile
import os

zip_path = "sample_course/RuntimeMinimumCalls_SCORM12.zip"
files_to_inspect = [
    "Playing/Playing.html",
    "Etiquette/questions.js",
    "shared/assessmenttemplate.html"
]

try:
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        for file_name in files_to_inspect:
            try:
                content = zip_ref.read(file_name).decode('utf-8', errors='replace')
                print(f"\n\n--- START OF {file_name} ---")
                print(content[:2000]) # Print first 2000 chars to avoid overwhelming context
                if len(content) > 2000:
                    print("\n... (truncated) ...")
                print(f"--- END OF {file_name} ---")
            except KeyError:
                print(f"\nFile not found in zip: {file_name}")
except Exception as e:
    print(f"Error: {e}")
