from __future__ import annotations

import json
import logging
import threading
from queue import Empty, Queue

from flask import Flask, Response, jsonify, render_template, request

from . import database as db
from .package_scanner import run_package_scan
from .stats import analyze_packages
from .vacations import VACATIONS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

_scan_lock = threading.Lock()
_scan_queue: Queue[dict] | None = None
_scan_thread: threading.Thread | None = None


def _is_scanning() -> bool:
    return _scan_thread is not None and _scan_thread.is_alive()


@app.route("/")
def index():
    db.init_db()
    all_pkg = db.get_package_history()
    analysis = analyze_packages(all_pkg)
    last_scan = db.get_last_scan()
    scan_count = db.get_scan_count()
    return render_template(
        "index.html",
        vacations=VACATIONS,
        analysis=analysis,
        last_scan=last_scan,
        scan_count=scan_count,
        is_scanning=_is_scanning(),
    )


@app.route("/scan", methods=["POST"])
def start_scan():
    global _scan_queue, _scan_thread

    with _scan_lock:
        if _is_scanning():
            return jsonify({"status": "already_running"}), 409

        headed = request.json.get("headed", False) if request.is_json else False
        _scan_queue = Queue()

        def _worker():
            try:
                for event in run_package_scan(headed=headed):
                    _scan_queue.put(event)
            except Exception as e:
                _scan_queue.put({"type": "error", "error": str(e)})

        _scan_thread = threading.Thread(target=_worker, daemon=True)
        _scan_thread.start()

    return jsonify({"status": "started"})


@app.route("/scan/stream")
def scan_stream():
    def _generate():
        while True:
            if _scan_queue is None:
                yield f"data: {json.dumps({'type': 'idle'})}\n\n"
                break
            try:
                event = _scan_queue.get(timeout=1)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in ("done", "error"):
                    break
            except Empty:
                if not _is_scanning():
                    break
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

    return Response(_generate(), mimetype="text/event-stream")


@app.route("/chart-data")
def chart_data():
    """Returns chart-ready JSON for all 5 vacations."""
    db.init_db()
    threshold = float(request.args.get("threshold", 1.0))
    all_pkg = db.get_package_history()
    analysis = analyze_packages(all_pkg, std_dev_threshold=threshold)
    return jsonify({
        "chart_data": analysis["chart_data"],
        "deals": analysis["deals"],
        "vacation_stats": analysis["vacation_stats"],
        "vacations": {
            vid: {
                "name": v.name,
                "color": v.color,
                "emoji": v.emoji,
                "subtitle": v.subtitle,
            }
            for vid, v in VACATIONS.items()
        },
    })


@app.route("/status")
def status():
    return jsonify({
        "scanning": _is_scanning(),
        "scan_count": db.get_scan_count(),
        "last_scan": db.get_last_scan(),
    })
