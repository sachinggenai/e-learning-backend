import os
os.chdir(r"C:\Users\ADMIN\e-learning-backend")
from dotenv import load_dotenv
load_dotenv()
from app.main import app
for r in sorted(app.routes, key=lambda x: x.path):
    if "session" in r.path.lower() or r.path.startswith("/api/v1/ai"):
        methods = r.methods if hasattr(r, "methods") else "WS"
        print(f"{methods} {r.path}")
