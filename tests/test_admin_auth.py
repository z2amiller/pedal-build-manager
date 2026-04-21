import base64

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def auth_header(password: str, username: str = "admin") -> dict:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_correct_password_returns_200(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    response = client.get("/admin/ping", headers=auth_header("secret"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_wrong_password_returns_401(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    response = client.get("/admin/ping", headers=auth_header("wrong"))
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Basic"


def test_no_auth_header_returns_401(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    response = client.get("/admin/ping")
    assert response.status_code == 401


def test_unset_env_var_returns_503(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    response = client.get("/admin/ping", headers=auth_header("anything"))
    assert response.status_code == 503
