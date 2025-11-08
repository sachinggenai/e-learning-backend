"""Main FastAPI application entry point.

Provides CORS, health/export endpoints and (Phase 2 foundation) courses CRUD.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import os
from datetime import datetime

# Import routers
from app.routers import (
    health, export, courses, templates, media, enhanced_templates
)
# (engine import removed; direct DB access not needed here post-migration)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Application metadata
APP_NAME = "eLearning Authoring App API"
VERSION = "1.0.0"
DESCRIPTION = """
eLearning Authoring App Backend API

## Features

* **Health Check**: Monitor application status
* **Course Export**: Generate SCORM packages from course data
* **Validation**: Server-side course data validation
* **CORS Support**: Cross-origin resource sharing for development

## Phase 1 Implementation

This Phase 1 MVP includes:
- Basic project scaffolding
- Course schema validation
- Dummy SCORM export functionality
- Health monitoring endpoints
"""

# Initialize FastAPI app
app = FastAPI(
    title=APP_NAME,
    description=DESCRIPTION,
    version=VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# CORS middleware configuration
cors_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:3001"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Global exception handler


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions with consistent error format"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": exc.detail,
            "timestamp": datetime.utcnow().isoformat(),
            "path": str(request.url)
        }
    )

 
@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error",
            "timestamp": datetime.utcnow().isoformat(),
            "path": str(request.url)
        }
    )

# Include routers
app.include_router(health.router, prefix="/api/v1", tags=["Health"])
app.include_router(export.router, prefix="/api/v1", tags=["Export"])
app.include_router(courses.router, prefix="/api/v1", tags=["Courses"])
app.include_router(templates.router, prefix="/api/v1", tags=["Templates"])
app.include_router(enhanced_templates.router, prefix="/api/v1")
app.include_router(media.router, prefix="/api/v1", tags=["Media"])

# Root endpoint
 
 
@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with API information"""
    return {
        "name": APP_NAME,
        "version": VERSION,
        "status": "running",
        "environment": os.getenv("ENVIRONMENT", "development"),
        "timestamp": datetime.utcnow().isoformat(),
        "docs": "/docs",
        "health": "/api/v1/health"
    }

# Application startup event
 
 
@app.on_event("startup")
async def startup_event():
    """Application startup tasks"""
    logger.info(f"Starting {APP_NAME} v{VERSION}")
    logger.info(f"Environment: {os.getenv('ENVIRONMENT', 'development')}")
    logger.info(f"CORS Origins: {cors_origins}")
    # Optional automatic Alembic upgrade (env flag) replaces prior create_all
    if os.getenv("AUTO_MIGRATE", "false").lower() in {"1", "true", "yes"}:
        try:
            import subprocess
            logger.info("AUTO_MIGRATE enabled: running 'alembic upgrade head'")
            result = subprocess.run(
                ["alembic", "upgrade", "head"],
                cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                logger.error(
                    "Alembic upgrade failed (code %s): %s\n%s",
                    result.returncode,
                    result.stdout,
                    result.stderr,
                )
            else:
                logger.info("Alembic migration applied successfully")
        except FileNotFoundError:
            logger.error(
                "Alembic not found – ensure it's installed in the environment"
            )
        except Exception as exc:  # pragma: no cover
            logger.error(f"Alembic migration unexpected error: {exc}")

# Application shutdown event
 
 
@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown tasks"""
    logger.info(f"Shutting down {APP_NAME}")

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )
