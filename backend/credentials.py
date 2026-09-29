"""把网页提交的交易密钥保存在服务器私有文件，不写入账户数据库。"""
import json
import os
import tempfile
from pathlib import Path


class CredentialStore:
    def __init__(self, database_path: str):
        self.path = Path(database_path + ".credentials")

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        if self.path.is_symlink():
            raise RuntimeError("交易密钥文件路径不安全")
        try:
            if self.path.stat().st_mode & 0o077:
                raise RuntimeError("交易密钥文件权限过宽，请改为仅服务器账户可读写")
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (OSError, ValueError):
            raise RuntimeError("无法读取服务器交易密钥，请检查文件权限") from None

    def get(self, mode: str) -> tuple[str, str] | None:
        saved = self._read().get(mode)
        if isinstance(saved, dict) and saved.get("key") and saved.get("secret"):
            return saved["key"], saved["secret"]
        prefix = "BINANCE_TESTNET" if mode == "testnet" else "BINANCE"
        key, secret = os.getenv(prefix + "_API_KEY"), os.getenv(prefix + "_API_SECRET")
        return (key, secret) if key and secret else None

    def has_saved(self, mode: str) -> bool:
        return mode in self._read()

    def _write(self, data: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".credentials-", delete=False) as file:
                temporary = Path(file.name)
                json.dump(data, file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def save(self, mode: str, key: str, secret: str):
        data = self._read()
        data[mode] = {"key": key, "secret": secret}
        self._write(data)

    def remove(self, mode: str):
        data = self._read()
        data.pop(mode, None)
        if data:
            self._write(data)
        else:
            self.path.unlink(missing_ok=True)
