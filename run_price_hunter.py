#!/usr/bin/env python3
"""Entry point: python run_price_hunter.py"""
import os
import threading
import time
import webbrowser

from price_hunter.database import init_db, DB_PATH
from price_hunter.app import app

PORT = int(os.environ.get("PORT", 5050))
# Only auto-open browser when running locally (not on a cloud server)
IS_LOCAL = os.environ.get("RENDER") is None


def _open_browser():
    time.sleep(1.5)
    webbrowser.open(f"http://localhost:{PORT}")


if __name__ == "__main__":
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    init_db()
    if IS_LOCAL:
        threading.Thread(target=_open_browser, daemon=True).start()
        print(f"Price Hunter running at http://localhost:{PORT}")
    else:
        print(f"Price Hunter running on port {PORT}")
    print("Press Ctrl+C to stop.\n")
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
