"""
Storage abstraction for file uploads and SCORM packages.

Provides a clean interface for different storage backends (local filesystem, cloud storage)
to support SCORM import functionality.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Optional, Dict, Any
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class StorageResult:
    """Result of a storage operation."""
    success: bool
    file_path: Optional[str] = None
    file_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


@dataclass
class FileInfo:
    """Information about a stored file."""
    path: str
    url: Optional[str] = None
    size: Optional[int] = None
    mime_type: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class AbstractStorage(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    async def save_file(
        self,
        file_data: BinaryIO,
        filename: str,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> StorageResult:
        """Save a file to storage.

        Args:
            file_data: Binary file data stream
            filename: Original filename
            content_type: MIME content type
            metadata: Additional metadata

        Returns:
            StorageResult with operation outcome
        """
        pass

    @abstractmethod
    async def get_file(self, file_path: str) -> Optional[FileInfo]:
        """Get file information.

        Args:
            file_path: Path to the file

        Returns:
            FileInfo if file exists, None otherwise
        """
        pass

    @abstractmethod
    async def delete_file(self, file_path: str) -> bool:
        """Delete a file from storage.

        Args:
            file_path: Path to the file

        Returns:
            True if deleted successfully, False otherwise
        """
        pass

    @abstractmethod
    async def file_exists(self, file_path: str) -> bool:
        """Check if file exists.

        Args:
            file_path: Path to check

        Returns:
            True if file exists, False otherwise
        """
        pass

    @abstractmethod
    async def list_files(self, prefix: Optional[str] = None) -> list[FileInfo]:
        """List files with optional prefix filter.

        Args:
            prefix: Optional path prefix to filter by

        Returns:
            List of FileInfo objects
        """
        pass


class LocalFileSystemStorage(AbstractStorage):
    """Local filesystem storage implementation."""

    def __init__(self, base_path: str = "uploads", base_url: Optional[str] = None):
        """Initialize local storage.

        Args:
            base_path: Base directory path for storing files
            base_url: Base URL for generating file URLs (optional)
        """
        self.base_path = Path(base_path)
        self.base_url = base_url
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def save_file(
        self,
        file_data: BinaryIO,
        filename: str,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> StorageResult:
        """Save file to local filesystem."""
        try:
            # Generate unique filename to avoid conflicts
            import uuid
            file_extension = Path(filename).suffix
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            file_path = self.base_path / unique_filename

            # Ensure directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            import aiofiles
            async with aiofiles.open(file_path, 'wb') as f:
                content = file_data.read()
                await f.write(content)

            # Generate URL if base_url provided
            file_url = None
            if self.base_url:
                file_url = f"{self.base_url.rstrip('/')}/{unique_filename}"

            return StorageResult(
                success=True,
                file_path=str(file_path),
                file_url=file_url,
                metadata={
                    "original_filename": filename,
                    "content_type": content_type,
                    "size": len(content),
                    **(metadata or {})
                }
            )

        except Exception as e:
            logger.error(f"Failed to save file {filename}: {e}")
            return StorageResult(
                success=False,
                error_message=str(e)
            )

    async def get_file(self, file_path: str) -> Optional[FileInfo]:
        """Get file information."""
        try:
            path = Path(file_path)
            if not path.exists() or not path.is_file():
                return None

            import mimetypes
            mime_type, _ = mimetypes.guess_type(str(path))

            # Generate URL if base_url provided
            file_url = None
            if self.base_url:
                relative_path = path.relative_to(self.base_path)
                file_url = f"{self.base_url.rstrip('/')}/{relative_path}"

            return FileInfo(
                path=str(path),
                url=file_url,
                size=path.stat().st_size,
                mime_type=mime_type
            )

        except Exception as e:
            logger.error(f"Failed to get file info for {file_path}: {e}")
            return None

    async def delete_file(self, file_path: str) -> bool:
        """Delete file from filesystem."""
        try:
            path = Path(file_path)
            if path.exists() and path.is_file():
                path.unlink()
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete file {file_path}: {e}")
            return False

    async def file_exists(self, file_path: str) -> bool:
        """Check if file exists."""
        try:
            path = Path(file_path)
            return path.exists() and path.is_file()
        except Exception:
            return False

    async def list_files(self, prefix: Optional[str] = None) -> list[FileInfo]:
        """List files with optional prefix."""
        try:
            files = []
            search_path = self.base_path

            if prefix:
                search_path = search_path / prefix

            if not search_path.exists():
                return files

            import mimetypes
            for path in search_path.rglob("*"):
                if path.is_file():
                    mime_type, _ = mimetypes.guess_type(str(path))
                    relative_path = path.relative_to(self.base_path)

                    file_url = None
                    if self.base_url:
                        file_url = f"{self.base_url.rstrip('/')}/{relative_path}"

                    files.append(FileInfo(
                        path=str(path),
                        url=file_url,
                        size=path.stat().st_size,
                        mime_type=mime_type
                    ))

            return files

        except Exception as e:
            logger.error(f"Failed to list files with prefix {prefix}: {e}")
            return []


# Default storage instance
default_storage = LocalFileSystemStorage()


class StorageService:
    """High-level storage service for SCORM import operations."""

    def __init__(self, storage: Optional[AbstractStorage] = None):
        """Initialize storage service.

        Args:
            storage: Storage backend to use (defaults to local filesystem)
        """
        self.storage = storage or default_storage

    async def save_scorm_package(
        self,
        file_data: BinaryIO,
        filename: str,
        job_id: str
    ) -> StorageResult:
        """Save a SCORM package file.

        Args:
            file_data: SCORM zip file data
            filename: Original filename
            job_id: Import job ID for organization

        Returns:
            StorageResult with file information
        """
        # Add SCORM-specific metadata
        metadata = {
            "job_id": job_id,
            "file_type": "scorm_package",
            "uploaded_at": datetime.now().isoformat()
        }

        return await self.storage.save_file(
            file_data=file_data,
            filename=filename,
            content_type="application/zip",
            metadata=metadata
        )

    async def get_scorm_package(self, file_path: str) -> Optional[FileInfo]:
        """Get SCORM package information.

        Args:
            file_path: Path to the SCORM package

        Returns:
            FileInfo if package exists, None otherwise
        """
        return await self.storage.get_file(file_path)

    async def cleanup_scorm_package(self, file_path: str) -> bool:
        """Clean up a SCORM package after processing.

        Args:
            file_path: Path to the SCORM package

        Returns:
            True if cleaned up successfully
        """
        return await self.storage.delete_file(file_path)

    async def validate_scorm_file(self, file_path: str) -> bool:
        """Validate that a file is a proper SCORM package.

        Args:
            file_path: Path to the potential SCORM file

        Returns:
            True if valid SCORM package, False otherwise
        """
        try:
            import zipfile
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                # Check for imsmanifest.xml
                if 'imsmanifest.xml' not in zip_ref.namelist():
                    return False
                return True
        except Exception as e:
            logger.error(f"SCORM validation failed for {file_path}: {e}")
            return False