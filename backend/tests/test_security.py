"""访问控制回归：外部网站不能借本机服务控制交易。"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.security import install_security


def client(password=""):
    app = FastAPI()
    install_security(app, password=password, allowed_hosts=["testserver"])

    @app.get("/api/private")
    def private():
        return {"ok": True}

    @app.post("/api/change")
    def change():
        return {"ok": True}

    return TestClient(app, client=("127.0.0.1", 50000))


def test_password_protects_read_and_write_and_logout():
    c = client("a-strong-local-password")
    assert c.get("/api/private").status_code == 401
    assert c.post("/api/change").status_code == 401
    assert c.post("/api/login", json={"password": "wrong"}).status_code == 401
    response = c.post("/api/login", json={"password": "a-strong-local-password"})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert c.get("/api/private").json() == {"ok": True}
    c.post("/api/logout")
    assert c.get("/api/private").status_code == 401


def test_local_mode_blocks_cross_origin_write_and_dns_rebinding():
    c = client()
    assert c.post("/api/change", headers={"origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/change", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert c.get("/api/private", headers={"host": "evil.example"}).status_code == 400
    assert c.post("/api/change", headers={"origin": "http://testserver"}).status_code == 200


def test_remote_client_cannot_use_passwordless_instance():
    app = FastAPI()
    install_security(app, password="", allowed_hosts=["testserver"])
    c = TestClient(app, client=("203.0.113.9", 50000))
    assert c.get("/api/auth").status_code == 403


def test_wrong_password_is_rate_limited():
    c = client("a-strong-local-password")
    for _ in range(5):
        assert c.post("/api/login", json={"password": "wrong"}).status_code == 401
    assert c.post("/api/login", json={"password": "wrong"}).status_code == 429
