"""Start the FastAPI server with Windows event loop fix."""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn
uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_level="info")
