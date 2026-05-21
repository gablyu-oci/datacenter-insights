"""Best-effort mirror of locally-archived Aterio CSVs to OCI Object Storage.

This module owns a single verb: PUT one local file to one OCI object key.
It is invoked as a side effect from ``backend/pipeline/runner.py`` after the
boto3 download succeeds; the runner does not care whether the upload
succeeds. See ``docs/architecture/aterio_oci_mirror.md`` for the contract.

Public API:

    mirror_to_oci(local_path: pathlib.Path, object_name: str) -> bool

Returns ``True`` on a 2xx PUT, ``False`` on any failure (kill switch,
missing file, auth error, ``ServiceError``, unexpected exception). Never
raises into the caller -- pipeline durability outweighs strict mirror
consistency (ADR-1).

Patch targets for unit tests (see architecture doc, Test Seams):

    backend.pipeline.aterio_oci_mirror.ObjectStorageClient
    backend.pipeline.aterio_oci_mirror.from_file
"""

from __future__ import annotations

import logging
import os
import pathlib
from pathlib import Path

# Imports kept at module top so unit tests can patch the symbols at the
# import site (per architecture doc Test Seams + research doc gotcha:
# "patch the symbol where it's used, not at the source module"). The cost
# of importing the OCI SDK is paid only when this sibling module is first
# imported -- runner.py imports it lazily inside _download_aterio_object,
# so the API process startup is unaffected.
from oci.config import from_file
from oci.exceptions import ServiceError
from oci.object_storage import ObjectStorageClient

logger = logging.getLogger(__name__)

# Defaults match the provisioned tenancy/bucket. Both are overridable via
# env for staging/test environments.
_DEFAULT_NAMESPACE = "iduyx1qnmway"
_DEFAULT_BUCKET = "aterio-archive"


def _resolve_namespace() -> str:
    return os.environ.get("OCI_ARCHIVE_NAMESPACE", _DEFAULT_NAMESPACE)


def _resolve_bucket() -> str:
    return os.environ.get("OCI_ARCHIVE_BUCKET", _DEFAULT_BUCKET)


def _build_client() -> ObjectStorageClient:
    """Construct a per-call ObjectStorageClient from the local OCI config.

    Per-call construction is intentional (ADR-2): the archiver runs at most
    a few times per day, and per-call lifetime makes mocking trivially
    correct and avoids long-lived state.
    """
    config = from_file(
        file_location=os.environ.get("OCI_CONFIG_FILE", "~/.oci/config"),
        profile_name=os.environ.get("OCI_CONFIG_PROFILE", "DEFAULT"),
    )
    return ObjectStorageClient(config)


def mirror_to_oci(local_path: pathlib.Path, object_name: str) -> bool:
    """Idempotently PUT ``local_path`` to ``oci://<bucket>/<object_name>``.

    Parameters
    ----------
    local_path:
        Path on local disk to upload. Must be an existing regular file;
        otherwise the function logs a warning and returns ``False`` without
        attempting any network call.
    object_name:
        Literal OCI object key. Slashes are part of the key (OCI has no real
        directories -- the slash just produces a logical prefix when listing).
        Caller owns key construction; this function does not validate shape.

    Returns
    -------
    bool
        ``True`` on a 2xx response from ``put_object``. ``False`` for any
        failure mode: kill switch off, missing file, auth/config error,
        ``ServiceError`` (4xx/5xx), or any unexpected exception. Never raises.
    """
    # Kill switch first -- evaluated BEFORE any client construction so that
    # disabling the feature (e.g. in CI / local dev) costs nothing and does
    # not touch ~/.oci/config.
    if os.environ.get("OCI_ARCHIVE_ENABLED", "1") == "0":
        logger.info(
            "aterio_oci_mirror.disabled skipping upload local=%s key=%s",
            local_path, object_name,
        )
        return False

    # Normalize to Path so callers can pass str or Path.
    local_path = Path(local_path)
    if not local_path.is_file():
        logger.warning(
            "aterio_oci_mirror.not_a_file local=%s key=%s",
            local_path, object_name,
        )
        return False

    namespace = _resolve_namespace()
    bucket = _resolve_bucket()
    size = local_path.stat().st_size

    try:
        client = _build_client()
        # Stream via an open binary handle -- SDK reads synchronously, so a
        # ``with`` block is safe. Explicit content_length avoids chunked
        # encoding and gives clean Content-Length headers (research doc 3).
        with local_path.open("rb") as fh:
            resp = client.put_object(
                namespace_name=namespace,
                bucket_name=bucket,
                object_name=object_name,
                put_object_body=fh,
                content_length=size,
                content_type="text/csv",
            )
    except ServiceError as exc:
        # 4xx/5xx from OCI -- log structured fields for triage and swallow.
        logger.error(
            "aterio_oci_mirror.service_error local=%s key=%s status=%s code=%s msg=%s",
            local_path, object_name, exc.status, exc.code, exc.message,
        )
        return False
    except Exception:
        # Auth failure, missing config file, network blow-up, etc. Log with
        # traceback and swallow -- the runner must not be blocked.
        logger.exception(
            "aterio_oci_mirror.unexpected_error local=%s key=%s",
            local_path, object_name,
        )
        return False

    # `put_object` returns oci.response.Response. Treat any non-2xx as
    # failure even if the SDK didn't raise (defensive).
    status = getattr(resp, "status", None)
    if status is not None and not (200 <= int(status) < 300):
        logger.error(
            "aterio_oci_mirror.non_2xx local=%s key=%s status=%s",
            local_path, object_name, status,
        )
        return False

    headers = getattr(resp, "headers", {}) or {}
    logger.info(
        "aterio_oci_mirror.uploaded local=%s key=oci://%s/%s size=%d etag=%s opc_request_id=%s",
        local_path,
        bucket,
        object_name,
        size,
        headers.get("etag"),
        headers.get("opc-request-id"),
    )
    return True
