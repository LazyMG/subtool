"""
subtool 웹 화면 실행: python app.py → http://localhost:8000
"""

import argparse
import sys
import threading
import webbrowser

import uvicorn


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="subtool 웹 화면")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true", help="브라우저 자동 열기 안 함")
    args = ap.parse_args()
    url = f"http://localhost:{args.port}"
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"subtool: {url} (종료: Ctrl+C)")
    uvicorn.run("subtool.server:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
