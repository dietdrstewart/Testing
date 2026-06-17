#!/usr/bin/env python3
"""Entry point: python run_price_hunter.py"""
import webbrowser
import threading
import time

from price_hunter.database import init_db
from price_hunter.app import app


def _open_browser():
    time.sleep(1.5)
    webbrowser.open("http://localhost:5050")


if __name__ == "__main__":
    init_db()
    threading.Thread(target=_open_browser, daemon=True).start()
    print("Price Hunter running at http://localhost:5050")
    print("Press Ctrl+C to stop.\n")
    app.run(host="0.0.0.0", port=5050, debug=False, use_reloader=False)
