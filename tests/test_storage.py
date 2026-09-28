from pathlib import Path

import pytest

from app.core.storage import LocalStorageService


@pytest.mark.asyncio
async def test_local_storage_roundtrip(tmp_path):
    storage = LocalStorageService(str(tmp_path))
    stored = await storage.put_bytes(
        "activos/abc/factura.pdf", b"%PDF storage", "application/pdf"
    )

    assert stored.backend == "local"
    assert stored.bucket is None
    assert len(stored.checksum_sha256) == 64
    assert await storage.get_bytes(stored.object_key) == b"%PDF storage"

    await storage.delete(stored.object_key)
    assert not (Path(tmp_path) / stored.object_key).exists()


def test_local_storage_rejects_path_traversal(tmp_path):
    storage = LocalStorageService(str(tmp_path))
    with pytest.raises(ValueError, match="INVALID_STORAGE_OBJECT_KEY"):
        storage._path("../escape.txt")
