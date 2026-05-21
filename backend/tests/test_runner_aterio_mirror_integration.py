"""Integration tests for ``pipeline.runner._download_aterio_object``.

These tests verify the mirror call is wired up correctly without changing
the function's return contract: ``_download_aterio_object`` must still
return a ``pathlib.Path`` regardless of mirror outcome.

Why this file exists separately from ``test_aterio_oci_mirror.py``:
the mirror module is unit-tested in isolation there; here we verify the
runner integration point (the lazy import + try/except wrapper + ordering
relative to the boto3 download) without exercising the OCI SDK.

Strategy notes
--------------

* ``boto3`` is imported *inside* ``_download_aterio_object``. We inject a
  stub ``boto3`` into ``sys.modules`` so the lazy ``import boto3`` line
  resolves to our fake. The fake's ``Session(...).client(...).download_file``
  creates the destination file via ``Path.write_bytes(b"")`` so the
  ``dest.exists()`` check on subsequent calls would short-circuit the
  download (we only call once per test).
* ``mirror_to_oci`` is also imported lazily, via
  ``from pipeline.aterio_oci_mirror import mirror_to_oci``. That import
  resolves at call time by looking up the attribute on the
  ``pipeline.aterio_oci_mirror`` module object -- so monkeypatching the
  attribute on that module BEFORE invoking the runner is sufficient and
  needs no ``sys.modules`` shenanigans.
* ``datetime.utcnow()`` is frozen by monkeypatching
  ``pipeline.runner.datetime`` with a tiny stand-in.
* ``_ATERIO_ARCHIVE_ROOT`` is redirected to ``tmp_path`` so we never write
  into ``backend/data/aterio_archive/``.
"""
from __future__ import annotations

import os
import pathlib
import sys
from datetime import datetime
from unittest.mock import MagicMock

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FrozenDatetime:
    """Minimal stand-in for the ``datetime`` symbol imported into
    ``pipeline.runner`` -- only ``utcnow()`` is exercised by the function
    under test."""

    @staticmethod
    def utcnow():
        return datetime(2026, 5, 21, 12, 0, 0)


def _install_fake_boto3(monkeypatch):
    """Inject a stub ``boto3`` module so the lazy ``import boto3`` inside
    ``_download_aterio_object`` resolves to our fake. Returns the
    ``download_file`` MagicMock so callers can assert on it if needed.
    """
    download_file = MagicMock()

    def _side_effect(_access_point, _key, dest_path_str):
        # Create the destination so the runner's existence-check semantics
        # match a real boto3 download.
        pathlib.Path(dest_path_str).write_bytes(b"")

    download_file.side_effect = _side_effect

    fake_client = MagicMock()
    fake_client.download_file = download_file

    fake_session_instance = MagicMock()
    fake_session_instance.client.return_value = fake_client

    fake_boto3 = MagicMock()
    fake_boto3.Session.return_value = fake_session_instance

    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    return download_file


# ---------------------------------------------------------------------------
# 1. Happy path: returns local Path, mirror invoked with expected key
# ---------------------------------------------------------------------------


def test_download_aterio_object_returns_local_path_and_triggers_mirror(
    tmp_path, monkeypatch,
):
    # Imports deferred so monkeypatch.setitem(sys.modules,'boto3',...) is
    # active before the lazy import inside the function runs.
    import pipeline.runner as runner_mod
    import pipeline.aterio_oci_mirror as mirror_mod

    # 1) Redirect the archive root into tmp_path.
    monkeypatch.setattr(runner_mod, "_ATERIO_ARCHIVE_ROOT", tmp_path)

    # 2) Freeze datetime.utcnow() at 2026-05-21.
    monkeypatch.setattr(runner_mod, "datetime", _FrozenDatetime)

    # 3) Spy on the mirror function. Patch the attribute on the module
    #    that runner.py imports from -- since runner.py uses
    #    ``from pipeline.aterio_oci_mirror import mirror_to_oci`` at call
    #    time, the lookup hits this attribute.
    spy = MagicMock(return_value=True)
    monkeypatch.setattr(mirror_mod, "mirror_to_oci", spy)

    # 4) Stub boto3 so no real S3 call happens.
    _install_fake_boto3(monkeypatch)

    obj = {"Key": "data-centers/inventory/foo.csv"}
    result = runner_mod._download_aterio_object(obj, "inventory")

    expected_path = tmp_path / "2026-05-21" / "inventory" / "foo.csv"
    assert isinstance(result, pathlib.Path)
    assert result == expected_path
    assert result.exists()

    spy.assert_called_once()
    args, kwargs = spy.call_args
    # Runner calls mirror_to_oci(dest, object_name) positionally.
    assert args[0] == expected_path
    assert args[1] == "2026-05-21/inventory/foo.csv"


# ---------------------------------------------------------------------------
# 2. Mirror raises -> runner swallows and still returns local Path
# ---------------------------------------------------------------------------


def test_download_aterio_object_returns_path_even_when_mirror_fails(
    tmp_path, monkeypatch,
):
    import pipeline.runner as runner_mod
    import pipeline.aterio_oci_mirror as mirror_mod

    monkeypatch.setattr(runner_mod, "_ATERIO_ARCHIVE_ROOT", tmp_path)
    monkeypatch.setattr(runner_mod, "datetime", _FrozenDatetime)

    def _boom(*_a, **_kw):
        raise RuntimeError("mirror exploded")

    monkeypatch.setattr(mirror_mod, "mirror_to_oci", _boom)

    _install_fake_boto3(monkeypatch)

    obj = {"Key": "data-centers/events/bar.csv"}
    # Must NOT re-raise.
    result = runner_mod._download_aterio_object(obj, "events")

    expected_path = tmp_path / "2026-05-21" / "events" / "bar.csv"
    assert isinstance(result, pathlib.Path)
    assert result == expected_path
    assert result.exists()
