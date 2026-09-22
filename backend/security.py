"""单用户会话和同源防护；不向浏览器发送交易所密钥。"""
import hashlib
import hmac
import ipaddress
import secrets
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

COOKIE = "quant_session"
SESSION_SECONDS = 12 * 3600


class LoginRequest(BaseModel):
    password: str = Field(max_length=256)


def install_security(app, password: str, allowed_hosts: list[str]):
    sessions: dict[str, float] = {}
    attempts: dict[str, deque] = defaultdict(deque)
    password_hash = hashlib.sha256(password.encode()).digest()

    def authenticated(request: Request):
        return not password or sessions.get(request.cookies.get(COOKIE, ""), 0) > time.monotonic()

    @app.middleware("http")
    async def protect(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            if not password:
                try:
                    local = ipaddress.ip_address(request.client.host).is_loopback
                except (ValueError, AttributeError):
                    local = False
                if not local:
                    return JSONResponse({"detail": "远程访问须先配置控制台口令"}, status_code=403)
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                origin = request.headers.get("origin")
                if request.headers.get("sec-fetch-site") == "cross-site" or (
                    origin and urlsplit(origin).netloc != request.headers.get("host")
                ):
                    return JSONResponse({"detail": "已拒绝跨站操作，请从控制台页面操作"}, status_code=403)
            if request.url.path not in {"/api/auth", "/api/login"} and not authenticated(request):
                return JSONResponse({"detail": "请先登录控制台"}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # 后加入的中间件先执行，保证域名校验在会话及路由处理之前。
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.get("/api/auth")
    async def auth(request: Request):
        return {"required": bool(password), "authenticated": authenticated(request)}

    @app.post("/api/login")
    async def login(payload: LoginRequest, request: Request, response: Response):
        now = time.monotonic()
        key = request.client.host
        recent = attempts[key]
        while recent and recent[0] < now - 60:
            recent.popleft()
        if len(recent) >= 5:
            raise HTTPException(429, "尝试次数过多，请一分钟后再试")
        if password and not hmac.compare_digest(hashlib.sha256(payload.password.encode()).digest(), password_hash):
            recent.append(now)
            raise HTTPException(401, "控制台口令不正确")
        recent.clear()
        for token, expiry in list(sessions.items()):
            if expiry <= now:
                sessions.pop(token, None)
        token = secrets.token_urlsafe(32)
        sessions[token] = now + SESSION_SECONDS
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=request.url.scheme == "https", max_age=SESSION_SECONDS)
        return {"authenticated": True}

    @app.post("/api/logout")
    async def logout(request: Request, response: Response):
        sessions.pop(request.cookies.get(COOKIE, ""), None)
        response.delete_cookie(COOKIE)
        return {"authenticated": False}
