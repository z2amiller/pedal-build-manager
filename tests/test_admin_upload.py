"""Tests for POST /admin/upload endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

FIXTURE_ZIP = "/Users/andrewmiller/Claude/pedal-build/spec/fuzz-face.manifest.zip"
AUTH = ("admin", "testpass")


@pytest.fixture(autouse=True)
def set_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_PASSWORD", "testpass")
    monkeypatch.setenv("BUILDER_DB_PATH", ":memory:")
    monkeypatch.setenv("BUILDER_DATA_DIR", str(tmp_path / "boards"))


def test_upload_valid_manifest():
    with TestClient(app) as c:
        with open(FIXTURE_ZIP, "rb") as f:
            resp = c.post("/admin/upload", files={"file": f}, auth=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["slug"] == "fuzz-face"
    assert data["version"] == "1.0.0"
    assert data["url"] == "/board/fuzz-face/1.0.0"
    assert data["updated"] is False


def test_upload_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILDER_DATA_DIR", str(tmp_path / "boards2"))
    with TestClient(app) as c:
        with open(FIXTURE_ZIP, "rb") as f:
            c.post("/admin/upload", files={"file": f}, auth=AUTH)
        with open(FIXTURE_ZIP, "rb") as f:
            resp = c.post("/admin/upload", files={"file": f}, auth=AUTH)
    assert resp.status_code == 200
    assert resp.json()["updated"] is True


def test_upload_non_zip():
    with TestClient(app) as c:
        resp = c.post(
            "/admin/upload",
            files={"file": ("bad.zip", b"not a zip file", "application/zip")},
            auth=AUTH,
        )
    assert resp.status_code == 422


def test_upload_no_auth():
    with TestClient(app) as c:
        with open(FIXTURE_ZIP, "rb") as f:
            resp = c.post("/admin/upload", files={"file": f})
    assert resp.status_code == 401
