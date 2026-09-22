"""以单进程启动，避免多工作进程对同一账户重复下单。"""
import argparse
import os
from pathlib import Path
import uvicorn
from backend.settings import load_environment


def main():
    root = Path(__file__).resolve().parent.parent
    load_environment(root / ".env")
    parser = argparse.ArgumentParser(description="个人合约量化工作台")
    parser.add_argument("--host", default=os.getenv("QUANT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("QUANT_PORT", "8765")))
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"} and len(os.getenv("CONSOLE_PASSWORD", "")) < 12:
        parser.error("远程监听须先配置至少十二位控制台口令")
    from backend.app import create_app
    uvicorn.run(create_app(), host=args.host, port=args.port, workers=1, proxy_headers=False)


if __name__ == "__main__":
    main()
