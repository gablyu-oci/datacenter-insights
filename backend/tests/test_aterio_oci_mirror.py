"""Unit tests for ``pipeline.aterio_oci_mirror.mirror_to_oci``.

Patch targets (per architecture doc Test Seams) are at the module's import
site. Tests run from inside ``backend/`` with ``backend/`` on ``sys.path``
(see ``tests/conftest.py``), so the runtime-resolvable module name is
``pipeline.aterio_oci_mirror`` (not ``backend.pipeline.aterio_oci_mirror``,
which is the doc-style fully-qualified name but is not importable from the
test process).

Each test is independent. No real network calls. No reads of
``~/.oci/config`` -- ``from_file`` is always patched out.
"""
from __future__ import annotations

import os
import pathlib
import sys
from unittest.mock import MagicMock, patch

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MIRROR_MOD = "pipeline.aterio_oci_mirror"


def _mk_csv(tmp_path: pathlib.Path, name: str = "foo.csv", body: bytes = b"a,b\n1,2\n") -> pathlib.Path:
    p = tmp_path / name
    p.write_bytes(body)
    return p


def _ok_response() -> MagicMock:
    return MagicMock(status=200, headers={"etag": "abc", "opc-request-id": "rid"})


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


def test_mirror_to_oci_calls_put_object_with_correct_args(tmp_path, monkeypatch):
    # Make sure the kill switch and any env overrides from the shell are
    # neutralized for this test.
    monkeypatch.delenv("OCI_ARCHIVE_ENABLED", raising=False)
    monkeypatch.delenv("OCI_ARCHIVE_NAMESPACE", raising=False)
    monkeypatch.delenv("OCI_ARCHIVE_BUCKET", raising=False)

    local = _mk_csv(tmp_path, "foo.csv", b"hello,world\n1,2\n")
    expected_size = local.stat().st_size

    with patch(f"{_MIRROR_MOD}.ObjectStorageClient") as MockClient, \
         patch(f"{_MIRROR_MOD}.from_file") as mock_from_file:
        mock_from_file.return_value = {"region": "us-ashburn-1"}
        client = MockClient.return_value
        client.put_object.return_value = _ok_response()

        from pipeline.aterio_oci_mirror import mirror_to_oci

        result = mirror_to_oci(local, "2026-05-21/inventory/foo.csv")

    assert result is True
    client.put_object.assert_called_once()
    _, kwargs = client.put_object.call_args
    assert kwargs["namespace_name"] == "iduyx1qnmway"
    assert kwargs["bucket_name"] == "aterio-archive"
    assert kwargs["object_name"] == "2026-05-21/inventory/foo.csv"
    assert kwargs["content_length"] == expected_size
    assert kwargs["content_type"] == "text/csv"
    # put_object_body should be an open binary handle from the local file.
    assert "put_object_body" in kwargs


# ---------------------------------------------------------------------------
# 2. ServiceError (4xx/5xx) is swallowed -> False
# ---------------------------------------------------------------------------


def test_mirror_to_oci_returns_false_on_service_error(tmp_path, monkeypatch):
    monkeypatch.delenv("OCI_ARCHIVE_ENABLED", raising=False)

    from oci.exceptions import ServiceError

    local = _mk_csv(tmp_path)

    with patch(f"{_MIRROR_MOD}.ObjectStorageClient") as MockClient, \
         patch(f"{_MIRROR_MOD}.from_file") as mock_from_file:
        mock_from_file.return_value = {"region": "us-ashburn-1"}
        client = MockClient.return_value
        client.put_object.side_effect = ServiceError(
            status=503, code="X", headers={}, message="boom",
        )

        from pipeline.aterio_oci_mirror import mirror_to_oci

        # Must NOT raise.
        result = mirror_to_oci(local, "2026-05-21/inventory/foo.csv")

    assert result is False
    client.put_object.assert_called_once()


# ---------------------------------------------------------------------------
# 3. Unexpected exception is swallowed -> False
# ---------------------------------------------------------------------------


def test_mirror_to_oci_returns_false_on_unexpected_exception(tmp_path, monkeypatch):
    monkeypatch.delenv("OCI_ARCHIVE_ENABLED", raising=False)

    local = _mk_csv(tmp_path)

    with patch(f"{_MIRROR_MOD}.ObjectStorageClient") as MockClient, \
         patch(f"{_MIRROR_MOD}.from_file") as mock_from_file:
        mock_from_file.return_value = {"region": "us-ashburn-1"}
        client = MockClient.return_value
        client.put_object.side_effect = RuntimeError("nope")

        from pipeline.aterio_oci_mirror import mirror_to_oci

        # Must NOT raise.
        result = mirror_to_oci(local, "2026-05-21/inventory/foo.csv")

    assert result is False


# ---------------------------------------------------------------------------
# 4. Kill switch: no client construction, no SDK call
# ---------------------------------------------------------------------------


def test_mirror_to_oci_skips_when_kill_switch_set(tmp_path, monkeypatch):
    monkeypatch.setenv("OCI_ARCHIVE_ENABLED", "0")

    local = _mk_csv(tmp_path)

    with patch(f"{_MIRROR_MOD}.ObjectStorageClient") as MockClient, \
         patch(f"{_MIRROR_MOD}.from_file") as mock_from_file:
        from pipeline.aterio_oci_mirror import mirror_to_oci

        result = mirror_to_oci(local, "2026-05-21/inventory/foo.csv")

    assert result is False
    # Neither the class nor the config loader should have been touched.
    MockClient.assert_not_called()
    mock_from_file.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Missing file: return False without building a client
# ---------------------------------------------------------------------------


def test_mirror_to_oci_returns_false_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("OCI_ARCHIVE_ENABLED", raising=False)

    missing = tmp_path / "does_not_exist.csv"
    assert not missing.exists()

    with patch(f"{_MIRROR_MOD}.ObjectStorageClient") as MockClient, \
         patch(f"{_MIRROR_MOD}.from_file") as mock_from_file:
        from pipeline.aterio_oci_mirror import mirror_to_oci

        result = mirror_to_oci(missing, "2026-05-21/inventory/missing.csv")

    assert result is False
    MockClient.assert_not_called()
    mock_from_file.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Env overrides flow into the put_object call
# ---------------------------------------------------------------------------


def test_mirror_to_oci_honors_env_overrides(tmp_path, monkeypatch):
    monkeypatch.delenv("OCI_ARCHIVE_ENABLED", raising=False)
    monkeypatch.setenv("OCI_ARCHIVE_NAMESPACE", "ns2")
    monkeypatch.setenv("OCI_ARCHIVE_BUCKET", "bkt2")

    local = _mk_csv(tmp_path)

    with patch(f"{_MIRROR_MOD}.ObjectStorageClient") as MockClient, \
         patch(f"{_MIRROR_MOD}.from_file") as mock_from_file:
        mock_from_file.return_value = {"region": "us-ashburn-1"}
        client = MockClient.return_value
        client.put_object.return_value = _ok_response()

        from pipeline.aterio_oci_mirror import mirror_to_oci

        result = mirror_to_oci(local, "2026-05-21/inventory/foo.csv")

    assert result is True
    _, kwargs = client.put_object.call_args
    assert kwargs["namespace_name"] == "ns2"
    assert kwargs["bucket_name"] == "bkt2"
