"""
Health Check Router

Provides health check endpoints for monitoring application status.
Implements Phase 1 requirement for basic API endpoint functionality.
"""

from fastapi import APIRouter, Depends
from app.models.course import HealthCheckResponse
from app.utils.validation import get_validation_status
import time
import os
from datetime import datetime

# Initialize router
router = APIRouter()

# Application start time for uptime calculation
_start_time = time.time()

@router.get("/health", response_model=HealthCheckResponse, summary="Basic Health Check")
async def health_check():
    """
    Basic health check endpoint
    
    Returns application status, version, and environment information.
    This endpoint is used by load balancers and monitoring systems.
    """
    uptime = time.time() - _start_time
    
    return HealthCheckResponse(
        status="healthy",
        version=os.getenv("APP_VERSION", "1.0.0"),
        environment=os.getenv("ENVIRONMENT", "development"),
        timestamp=datetime.utcnow(),
        uptime=uptime
    )

@router.get("/health/detailed", summary="Detailed Health Check")
async def detailed_health_check(validation_status: dict = Depends(get_validation_status)):
    """
    Detailed health check with dependency validation
    
    Checks application components including:
    - Schema validation functionality
    - Environment configuration
    - System resources (basic check)
    """
    uptime = time.time() - _start_time
    
    # Basic system checks
    system_status = {
        "memory_available": True,  # Simplified for Phase 1
        "disk_space": True,        # Simplified for Phase 1
    }
    
    # Overall health status
    is_healthy = (
        validation_status["schema_loaded"] and 
        validation_status["validation_working"] and
        all(system_status.values())
    )
    
    return {
        "status": "healthy" if is_healthy else "degraded",
        "version": os.getenv("APP_VERSION", "1.0.0"),
        "environment": os.getenv("ENVIRONMENT", "development"),
        "timestamp": datetime.utcnow().isoformat(),
        "uptime": uptime,
        "components": {
            "validation": validation_status,
            "system": system_status
        },
        "details": {
            "cors_origins": os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
            "python_version": os.sys.version,
            "startup_time": datetime.fromtimestamp(_start_time).isoformat()
        }
    }

@router.get("/health/ready", summary="Readiness Check")
async def readiness_check():
    """
    Kubernetes-style readiness probe
    
    Returns 200 if the application is ready to serve requests,
    503 if it's starting up or experiencing issues.
    """
    # For Phase 1, we'll do basic readiness checks
    try:
        # Check if we can load the schema
        from app.utils.validation import load_course_schema
        schema = load_course_schema()
        
        if schema is None:
            raise Exception("Schema not loaded")
        
        return {"status": "ready", "timestamp": datetime.utcnow().isoformat()}
    
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail=f"Application not ready: {str(e)}"
        )

@router.get("/health/live", summary="Liveness Check") 
async def liveness_check():
    """
    Kubernetes-style liveness probe
    
    Returns 200 if the application is alive and responding,
    should rarely fail unless the application is completely broken.
    """
    return {
        "status": "alive", 
        "timestamp": datetime.utcnow().isoformat(),
        "pid": os.getpid()
    }