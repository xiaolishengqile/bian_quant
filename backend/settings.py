"""读取部署环境，不覆盖进程已提供的变量。"""
import os
from pathlib import Path


def load_environment(path: Path):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if value.startswith(("'", '"')) and value[-1:] == value[:1]:
            value = value[1:-1]
        if key.replace("_", "").isalnum():
            os.environ.setdefault(key, value)
