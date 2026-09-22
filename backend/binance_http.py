"""币安传输边界：无隐式重试，异常不携带密钥、签名或原始响应。"""
import hashlib
import hmac
import time
from collections.abc import Callable
from urllib.parse import urlencode, urlsplit
from urllib.request import getproxies, proxy_bypass_environment

import httpx


LIVE_URL = "https://fapi.binance.com"
TESTNET_URL = "https://demo-fapi.binance.com"


def now_ms() -> int:
    return int(time.time() * 1000)


class BinanceAPIError(RuntimeError):
    def __init__(self, code: int | None = None):
        self.code = code
        label = f"（错误码 {code}）" if code is not None else ""
        super().__init__(f"币安请求失败{label}，请检查网络、权限和交易所限制")


class BinanceHTTP:
    def __init__(self, base_url: str, *, transport=None, clock: Callable[[], int] = now_ms):
        self.base_url = base_url
        self.transport = transport
        self.clock = clock
        self.offset = 0

    def _transport(self):
        if self.transport is not None:
            return self.transport
        # 只为当前固定域名选代理。标准库匹配绕过列表，不把 IPv6 网段当 URL 解析。
        target = urlsplit(self.base_url)
        proxies = getproxies()
        host = f"{target.hostname}:{target.port or 443}"
        proxy = None if proxy_bypass_environment(host, proxies) else proxies.get(target.scheme, proxies.get("all"))
        if proxy and "://" not in proxy:
            proxy = "http://" + proxy
        return httpx.AsyncHTTPTransport(proxy=proxy, retries=0)

    async def sync_time(self):
        before = self.clock()
        data = await self.request("GET", "/fapi/v1/time")
        try:
            self.offset = int(data["serverTime"]) - (before + self.clock()) // 2
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("币安服务器时间无效，无法签名请求") from None

    async def request(self, method: str, path: str, params: dict | None = None,
                      *, credentials: tuple[str, str] | None = None):
        values = dict(params or {})
        headers = {}
        if credentials:
            key, secret = credentials
            values.update(recvWindow=5000, timestamp=self.clock() + self.offset)
            headers["X-MBX-APIKEY"] = key
        encoded = urlencode(values)
        if credentials:
            signature = hmac.new(credentials[1].encode(), encoded.encode(), hashlib.sha256).hexdigest()
            encoded += "&signature=" + signature
        # 写请求使用正文，避免在访问日志中留下签名查询字符串。
        url = self.base_url + path
        kwargs = {"headers": headers}
        if method == "GET":
            url += "?" + encoded if encoded else ""
        else:
            kwargs["content"] = encoded
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            async with httpx.AsyncClient(transport=self._transport(), timeout=10, follow_redirects=False) as client:
                response = await client.request(method, url, **kwargs)
            data = response.json()
        except httpx.InvalidURL:
            raise RuntimeError("服务器代理地址配置无效，请检查代理及绕过代理地址设置") from None
        except (httpx.HTTPError, ValueError):
            raise BinanceAPIError() from None
        code = data.get("code") if isinstance(data, dict) else None
        if response.is_error or (isinstance(code, int) and code < 0):
            raise BinanceAPIError(code if isinstance(code, int) else None)
        if not isinstance(data, (dict, list)):
            raise RuntimeError("币安返回数据格式无效")
        return data


def is_usdt_perpetual(item: dict) -> bool:
    return (item.get("status") == "TRADING" and item.get("contractType") == "PERPETUAL"
            and item.get("quoteAsset") == "USDT" and item.get("marginAsset") == "USDT")
