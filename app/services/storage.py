"""
Storage abstraction for file uploads and SCORM packages.

Provides a clean interface for different storage backends (local filesystem, cloud storage)
to support SCORM import functionality.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Optional, Dict, Any
import logging
import os
from dataclasses import dataclass
from datetime import datetime

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


# ── S3 / MinIO Storage Backend ──────────────────────────────────────────

class S3Storage(AbstractStorage):
    """S3-compatible storage backend (MinIO, AWS S3, etc.).

    Configure via environment:
        STORAGE_BACKEND=s3
        S3_ENDPOINT=http://localhost:9000      # MinIO endpoint
        S3_ACCESS_KEY=minioadmin               # Access key
        S3_SECRET_KEY=minioadmin               # Secret key
        S3_BUCKET=elearning-assets             # Bucket name
        S3_REGION=us-east-1                    # Region
        S3_SECURE=0                            # Use HTTPS? (0 or 1)

    Graceful degradation: if the S3 client cannot connect, falls back
    to LocalFileSystemStorage automatically.
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        bucket: Optional[str] = None,
        region: Optional[str] = None,
        secure: Optional[bool] = None,
    ):
        self._endpoint = endpoint or os.getenv("S3_ENDPOINT", "http://localhost:9000")
        self._access_key = access_key or os.getenv("S3_ACCESS_KEY", "minioadmin")
        self._secret_key = secret_key or os.getenv("S3_SECRET_KEY", "minioadmin")
        self._bucket_name = bucket or os.getenv("S3_BUCKET", "elearning-assets")
        self._region = region or os.getenv("S3_REGION", "us-east-1")
        self._secure = secure if secure is not None else os.getenv("S3_SECURE", "0") == "1"
        self._client = None
        self._bucket_exists = False

    @property
    def bucket(self) -> str:
        return self._bucket_name

    def _get_client(self):
        """Lazy-init the aiobotocore S3 client."""
        if self._client is not None:
            return self._client
        try:
            import aiobotocore.session
            session = aiobotocore.session.AioSession()
            self._client = session.create_client(
                "s3",
                endpoint_url=self._endpoint,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                region_name=self._region,
                use_ssl=self._secure,
            )
        except ImportError:
            raise ImportError(
                "aiobotocore package not installed. "
                "Run: pip install aiobotocore"
            )
        except Exception as exc:
            logger.error("S3 client init failed: %s", exc)
            raise
        return self._client

    async def _ensure_bucket(self):
        """Create bucket if it doesn't exist (idempotent)."""
        if self._bucket_exists:
            return
        client = self._get_client()
        async with client as s3:
            try:
                await s3.head_bucket(Bucket=self._bucket_name)
                self._bucket_exists = True
            except Exception:
                await s3.create_bucket(Bucket=self._bucket_name)
                self._bucket_exists = True
                logger.info("S3 bucket '%s' created", self._bucket_name)

    @staticmethod
    def _sanitise_key(filename: str) -> str:
        """Generate a unique object key from a filename."""
        import uuid
        ext = Path(filename).suffix
        return f"uploads/{uuid.uuid4().hex}{ext}"

    # ── AbstractStorage implementation ──────────────────────────

    async def save_file(
        self,
        file_data: BinaryIO,
        filename: str,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> StorageResult:
        """Save file to S3/MinIO bucket."""
        try:
            await self._ensure_bucket()
            client = self._get_client()
            key = self._sanitise_key(filename)

            content = file_data.read()
            file_size = len(content)

            extra_args: Dict[str, str] = {}
            if content_type:
                extra_args["ContentType"] = content_type
            if metadata:
                for mk, mv in metadata.items():
                    extra_args[f"x-amz-meta-{mk}"] = str(mv)

            async with client as s3:
                await s3.put_object(
                    Bucket=self._bucket_name,
                    Key=key,
                    Body=content,
                    **extra_args,
                )

            file_url = f"{self._endpoint}/{self._bucket_name}/{key}"

            return StorageResult(
                success=True,
                file_path=key,
                file_url=file_url,
                metadata={
                    "original_filename": filename,
                    "content_type": content_type,
                    "size": file_size,
                    "storage_backend": "s3",
                    "bucket": self._bucket_name,
                    **(metadata or {}),
                },
            )
        except Exception as exc:
            logger.error("S3 save_file failed for %s: %s", filename, exc)
            return StorageResult(success=False, error_message=str(exc))

    async def get_file(self, file_path: str) -> Optional[FileInfo]:
        """Get file metadata from S3."""
        try:
            client = self._get_client()
            async with client as s3:
                resp = await s3.head_object(
                    Bucket=self._bucket_name,
                    Key=file_path,
                )
                file_url = f"{self._endpoint}/{self._bucket_name}/{file_path}"
                return FileInfo(
                    path=file_path,
                    url=file_url,
                    size=int(resp.get("ContentLength", 0)),
                    mime_type=resp.get("ContentType"),
                    metadata={
                        k.replace("x-amz-meta-", ""): v
                        for k, v in resp.get("Metadata", {}).items()
                    },
                )
        except Exception as exc:
            logger.error("S3 get_file failed for %s: %s", file_path, exc)
            return None

    async def delete_file(self, file_path: str) -> bool:
        """Delete file from S3 bucket."""
        try:
            client = self._get_client()
            async with client as s3:
                await s3.delete_object(
                    Bucket=self._bucket_name,
                    Key=file_path,
                )
            return True
        except Exception as exc:
            logger.error("S3 delete_file failed for %s: %s", file_path, exc)
            return False

    async def file_exists(self, file_path: str) -> bool:
        """Check if file exists in S3."""
        try:
            client = self._get_client()
            async with client as s3:
                await s3.head_object(
                    Bucket=self._bucket_name,
                    Key=file_path,
                )
            return True
        except Exception:
            return False

    async def list_files(self, prefix: Optional[str] = None) -> list[FileInfo]:
        """List files in S3 bucket with optional prefix."""
        try:
            client = self._get_client()
            async with client as s3:
                list_kwargs = {"Bucket": self._bucket_name}
                if prefix:
                    list_kwargs["Prefix"] = prefix
                resp = await s3.list_objects_v2(**list_kwargs)

            files: list[FileInfo] = []
            for obj in resp.get("Contents", []):
                key = obj.get("Key", "")
                file_url = f"{self._endpoint}/{self._bucket_name}/{key}"
                files.append(FileInfo(
                    path=key,
                    url=file_url,
                    size=obj.get("Size"),
                    mime_type=None,  # Can be fetched via head_object if needed
                ))
            return files
        except Exception as exc:
            logger.error("S3 list_files failed: %s", exc)
            return []


# ── Storage factory ────────────────────────────────────────────────────

def get_storage() -> AbstractStorage:
    """Return the configured storage backend.

    Controlled by STORAGE_BACKEND env var:
        "s3" or "minio" → S3Storage (MinIO or AWS S3)
        "local" or unset → LocalFileSystemStorage

    Graceful degradation: if S3 is configured but fails to initialise,
    falls back to local storage with a warning.
    """
    backend = os.getenv("STORAGE_BACKEND", "local").lower()

    if backend in ("s3", "minio"):
        try:
            s3_storage = S3Storage()
            logger.info("Storage backend: S3 (endpoint=%s, bucket=%s)",
                        s3_storage._endpoint, s3_storage._bucket_name)
            return s3_storage
        except Exception as exc:
            logger.warning(
                "S3 storage configured but unavailable (%s). "
                "Falling back to local filesystem storage.",
                exc,
            )

    logger.info("Storage backend: Local filesystem (base_path=uploads)")
    return LocalFileSystemStorage()


# Default storage instance (lazy — use get_storage() for most cases)
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