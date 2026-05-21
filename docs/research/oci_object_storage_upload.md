# OCI Object Storage Upload from Python — Implementer's Guide

Target: upload one local CSV (tens of MB) per call to bucket `aterio-archive` in namespace `iduyx1qnmway`, key `<YYYY-MM-DD>/<subdir>/<basename>`. Auth via default `~/.oci/config`. Overwrite OK. Must not crash caller on failure.

## TL;DR

- Use `oci.object_storage.ObjectStorageClient.put_object(...)` directly. Skip `UploadManager` — overkill for tens of MB.
- Instantiate the client **per call** (simpler tests, negligible cost for a rarely-invoked archiver).
- Stream the file by passing an open binary file handle as `put_object_body`. Set `content_length` explicitly — it lets the SDK avoid buffering and produces clean `Content-Length` headers.
- Catch `oci.exceptions.ServiceError` + broad `Exception`, log, return False. Never raise to the caller.
- Pin `oci>=2.126,<3.0`.

## 1. Canonical `put_object` signature (current SDK)

```
put_object(namespace_name, bucket_name, object_name, put_object_body, **kwargs)
```

| Name | Type | Notes |
|---|---|---|
| `namespace_name` | `str` | e.g. `"iduyx1qnmway"` |
| `bucket_name` | `str` | e.g. `"aterio-archive"` |
| `object_name` | `str` | object key, slashes are literal in the key |
| `put_object_body` | file-like (`read()`) or `bytes` | the payload |

Useful kwargs: `content_length`, `content_type`, `content_md5`, `if_match`, `if_none_match`, `retry_strategy`, `opc_meta`.

Return: `oci.response.Response` with `data=None`. ETag in `response.headers["etag"]`, request id in `response.headers["opc-request-id"]`.

PUT is idempotent at the key — re-uploading the same `object_name` overwrites. No "exists" preflight needed.

## 2. `UploadManager` vs `put_object` for this use case

`UploadManager` is useful when:

- File is > ~100 MB and you want parallel parts.
- Network is flaky and you want per-part retry instead of full-file retry.
- You want a single progress callback.

Drawbacks here: extra threading model, dedicated-client requirement on some SDK versions, harder to mock.

**Recommendation: stick with `put_object`.** Tens of MB over the OCI backbone completes in seconds.

## 3. Streaming a file handle and `content_length`

`put_object_body` accepts any file-like object with `read()`. Pass an `open(path, "rb")` handle inside a `with` block. Pass `content_length=os.path.getsize(path)` — it's free and avoids chunked encoding surprises.

```python
size = os.path.getsize(path)
with open(path, "rb") as fh:
    client.put_object(
        namespace_name=NAMESPACE,
        bucket_name=BUCKET,
        object_name=key,
        put_object_body=fh,
        content_length=size,
        content_type="text/csv",
    )
```

## 4. Client lifetime: per-call vs module singleton

**Per-call.** The archiver runs once per snapshot cycle; per-call avoids long-lived state, simplifies thread safety, and makes `patch("backend.pipeline.aterio_oci_mirror.ObjectStorageClient")` trivially correct.

## 5. Mocking pattern for pytest

Patch the name in the **module that imports it**, not the source module.

```python
from unittest.mock import patch, MagicMock

@patch("backend.pipeline.aterio_oci_mirror.ObjectStorageClient")
@patch("backend.pipeline.aterio_oci_mirror.from_file")
def test_upload_happy_path(mock_from_file, mock_client_cls, tmp_path):
    mock_from_file.return_value = {"region": "us-ashburn-1"}
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.put_object.return_value = MagicMock(
        status=200, headers={"etag": "abc", "opc-request-id": "rid"}
    )

    csv = tmp_path / "x.csv"
    csv.write_bytes(b"a,b\n1,2\n")

    from backend.pipeline.aterio_oci_mirror import upload_file
    ok = upload_file(csv, "2026-05-21/inventory/x.csv")

    assert ok is True
    kwargs = mock_client.put_object.call_args.kwargs
    assert kwargs["namespace_name"] == "iduyx1qnmway"
    assert kwargs["bucket_name"] == "aterio-archive"
    assert kwargs["object_name"] == "2026-05-21/inventory/x.csv"
    assert kwargs["content_length"] == csv.stat().st_size
```

Failure-path mocking:

```python
from oci.exceptions import ServiceError
mock_client.put_object.side_effect = ServiceError(
    status=503, code="ServiceUnavailable", headers={}, message="boom"
)
```

Gotchas: `ServiceError.__init__` requires `status`, `code`, `headers`, `message`. Don't patch `oci.object_storage.ObjectStorageClient` — patch the symbol where it's used.

## 6. Environment variable overrides

```python
from oci.config import from_file
config = from_file(
    file_location=os.environ.get("OCI_CONFIG_FILE", "~/.oci/config"),
    profile_name=os.environ.get("OCI_CONFIG_PROFILE", "DEFAULT"),
)
```

Also useful:

- `OCI_ARCHIVE_BUCKET`, `OCI_ARCHIVE_NAMESPACE` — override target for staging/tests.
- `OCI_ARCHIVE_ENABLED=0` — kill-switch for local dev.

## 7. SDK version pin

`oci>=2.126,<3.0` — the `put_object` kwargs have been stable across the 2.x line; `<3.0` guards against a future breaking major.

## 8. Full reference implementation

```python
# backend/pipeline/aterio_oci_mirror.py
from __future__ import annotations

import logging
import os
from pathlib import Path

from oci.config import from_file
from oci.exceptions import ServiceError
from oci.object_storage import ObjectStorageClient

log = logging.getLogger(__name__)

NAMESPACE = os.environ.get("OCI_ARCHIVE_NAMESPACE", "iduyx1qnmway")
BUCKET = os.environ.get("OCI_ARCHIVE_BUCKET", "aterio-archive")


def _build_client() -> ObjectStorageClient:
    config = from_file(
        file_location=os.environ.get("OCI_CONFIG_FILE", "~/.oci/config"),
        profile_name=os.environ.get("OCI_CONFIG_PROFILE", "DEFAULT"),
    )
    return ObjectStorageClient(config)


def upload_file(local_path: Path, object_name: str) -> bool:
    """Idempotent PUT. Returns True on success, False on any failure. Never raises."""
    if os.environ.get("OCI_ARCHIVE_ENABLED", "1") == "0":
        log.info("OCI archive disabled; skipping upload of %s", local_path)
        return False

    local_path = Path(local_path)
    if not local_path.is_file():
        log.warning("aterio_oci_mirror: %s is not a file; skipping", local_path)
        return False

    size = local_path.stat().st_size
    try:
        client = _build_client()
        with local_path.open("rb") as fh:
            resp = client.put_object(
                namespace_name=NAMESPACE,
                bucket_name=BUCKET,
                object_name=object_name,
                put_object_body=fh,
                content_length=size,
                content_type="text/csv",
            )
        log.info(
            "aterio_oci_mirror: uploaded %s -> oci://%s/%s (%d bytes, etag=%s, rid=%s)",
            local_path, BUCKET, object_name, size,
            resp.headers.get("etag"), resp.headers.get("opc-request-id"),
        )
        return True
    except ServiceError as e:
        log.error(
            "aterio_oci_mirror: ServiceError uploading %s to %s: status=%s code=%s msg=%s",
            local_path, object_name, e.status, e.code, e.message,
        )
        return False
    except Exception:
        log.exception(
            "aterio_oci_mirror: unexpected error uploading %s to %s",
            local_path, object_name,
        )
        return False
```

## Warnings / Gotchas

- **Mock target**: patch `backend.pipeline.aterio_oci_mirror.ObjectStorageClient`, not `oci.object_storage.ObjectStorageClient`.
- **`ServiceError` constructor**: requires `status`, `code`, `headers`, `message`.
- **File handle lifetime**: `put_object` reads synchronously; `with open(...)` is fine.
- **Profile defaults**: `from_file()` defaults to `DEFAULT`. If `~/.oci/config` lacks that section, you'll get a clear ConfigFileNotFound.
- **Region**: `ObjectStorageClient` uses the region from the config file. Cross-region requests are redirected (extra latency).
- **No HEAD preflight**: PUT overwrites; checking existence first costs an extra round trip.

## References

- [ObjectStorageClient](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/object_storage/client/oci.object_storage.ObjectStorageClient.html)
- [Exceptions](https://docs.oracle.com/en-us/iaas/tools/python/latest/exceptions.html)
- [UploadManager](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/upload_manager.html)
- [oci on PyPI](https://pypi.org/project/oci/)
- [oci-python-sdk](https://github.com/oracle/oci-python-sdk)
