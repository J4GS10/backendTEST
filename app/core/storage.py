"""Abstracción de almacenamiento local y S3-compatible (MinIO/AWS S3)."""
from __future__ import annotations

import asyncio
import hashlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import structlog

from app.core.config import settings

log = structlog.get_logger("storage")


class StorageUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredObject:
    backend: str
    object_key: str
    bucket: str | None
    size: int
    checksum_sha256: str


class StorageService(ABC):
    backend: str

    @abstractmethod
    async def put_bytes(
        self, object_key: str, content: bytes, content_type: str | None = None
    ) -> StoredObject:
        raise NotImplementedError

    @abstractmethod
    async def get_bytes(self, object_key: str, bucket: str | None = None) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, object_key: str, bucket: str | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> bool:
        raise NotImplementedError


def _safe_key(object_key: str) -> str:
    normalized = object_key.replace("\\", "/").lstrip("/")
    parts = [part for part in normalized.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError("INVALID_STORAGE_OBJECT_KEY")
    return "/".join(parts)


class LocalStorageService(StorageService):
    backend = "local"

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir).resolve()

    def _path(self, object_key: str) -> Path:
        candidate = (self.base_dir / _safe_key(object_key)).resolve()
        if self.base_dir not in candidate.parents:
            raise ValueError("INVALID_STORAGE_OBJECT_KEY")
        return candidate

    async def put_bytes(
        self, object_key: str, content: bytes, content_type: str | None = None
    ) -> StoredObject:
        path = self._path(object_key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        try:
            await asyncio.to_thread(_write)
        except OSError as exc:
            raise StorageUnavailableError("STORAGE_WRITE_FAILED") from exc
        return StoredObject(
            backend=self.backend,
            object_key=_safe_key(object_key),
            bucket=None,
            size=len(content),
            checksum_sha256=hashlib.sha256(content).hexdigest(),
        )

    async def get_bytes(self, object_key: str, bucket: str | None = None) -> bytes:
        try:
            return await asyncio.to_thread(self._path(object_key).read_bytes)
        except FileNotFoundError as exc:
            raise StorageUnavailableError("ATTACHMENT_FILE_MISSING") from exc
        except OSError as exc:
            raise StorageUnavailableError("STORAGE_READ_FAILED") from exc

    async def delete(self, object_key: str, bucket: str | None = None) -> None:
        path = self._path(object_key)
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError as exc:
            raise StorageUnavailableError("STORAGE_DELETE_FAILED") from exc

    async def health(self) -> bool:
        return await asyncio.to_thread(
            lambda: self.base_dir.is_dir() and os.access(self.base_dir, os.W_OK)
        )


class S3StorageService(StorageService):
    backend = "s3"

    def __init__(self) -> None:
        self.bucket = settings.S3_BUCKET
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError as exc:
                raise StorageUnavailableError("S3_DRIVER_NOT_INSTALLED") from exc
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.S3_ENDPOINT_URL,
                aws_access_key_id=settings.S3_ACCESS_KEY,
                aws_secret_access_key=settings.S3_SECRET_KEY,
                region_name=settings.S3_REGION,
                config=Config(
                    connect_timeout=settings.STORAGE_TIMEOUT_SECONDS,
                    read_timeout=settings.STORAGE_TIMEOUT_SECONDS,
                    retries={"max_attempts": 2, "mode": "standard"},
                    s3={"addressing_style": "path"},
                ),
            )
        return self._client

    async def put_bytes(
        self, object_key: str, content: bytes, content_type: str | None = None
    ) -> StoredObject:
        key = _safe_key(object_key)
        checksum = hashlib.sha256(content).hexdigest()
        kwargs = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": content,
            "Metadata": {"sha256": checksum},
        }
        if content_type:
            kwargs["ContentType"] = content_type
        try:
            await asyncio.to_thread(self._get_client().put_object, **kwargs)
        except Exception as exc:  # noqa: BLE001 - SDK exceptions vary
            raise StorageUnavailableError("STORAGE_WRITE_FAILED") from exc
        return StoredObject(
            backend=self.backend,
            object_key=key,
            bucket=self.bucket,
            size=len(content),
            checksum_sha256=checksum,
        )

    async def get_bytes(self, object_key: str, bucket: str | None = None) -> bytes:
        try:
            response = await asyncio.to_thread(
                self._get_client().get_object,
                Bucket=bucket or self.bucket,
                Key=_safe_key(object_key),
            )
            return await asyncio.to_thread(response["Body"].read)
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError("STORAGE_READ_FAILED") from exc

    async def delete(self, object_key: str, bucket: str | None = None) -> None:
        try:
            await asyncio.to_thread(
                self._get_client().delete_object,
                Bucket=bucket or self.bucket,
                Key=_safe_key(object_key),
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageUnavailableError("STORAGE_DELETE_FAILED") from exc

    async def health(self) -> bool:
        try:
            await asyncio.to_thread(
                self._get_client().head_bucket, Bucket=self.bucket
            )
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("storage.health_failed", error=str(exc))
            return False


s3_storage_service = S3StorageService()
local_storage_service = LocalStorageService(settings.UPLOAD_DIR)
storage_service: StorageService = (
    s3_storage_service
    if settings.STORAGE_BACKEND == "s3"
    else local_storage_service
)


def storage_for_backend(backend: str | None) -> StorageService:
    return s3_storage_service if backend == "s3" else local_storage_service
