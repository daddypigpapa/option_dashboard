"""Flask dashboard.

- Enter/save API keys from the browser -> persisted to keys.json (local).
- Trigger the data pipeline (runs main.py as a subprocess so it picks up the
  freshly-saved keys.json).
- View the latest results (data/output/dashboard.json).

Run:  python -m webapp.app      (from the project root)
Then open http://127.0.0.1:5000
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
import yfinance as yf

# Ensure project root is importable when run directly.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, render_template, request, send_from_directory

import keystore

app = Flask(__name__)
# Local dev tool: re-read templates from disk each request so edits show on a
# simple browser refresh, without needing a server restart.
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

OUTPUT_JSON = ROOT / "data" / "output" / "dashboard.json"

# Single-run state guarded by a lock (this is a local single-user tool).
_run_state: dict = {"running": False, "returncode": None, "log": "", "started_at": None}
_run_lock = threading.Lock()
_yf_lock = threading.Lock()


# ----------------------------------------------------------------- pages
@app.route("/")
def index():
    return render_template("index.html")


# ------------------------------------------------- option dashboard (vendored)
# Static ETF/stock option analytics dashboard from
# https://github.com/daddypigpapa/option_dashboard, cloned into the project root.
# It is fully self-contained (relative ./libs/ and ./data/ paths), so we serve
# the whole folder under /options/.
OPTIONS_DIR = ROOT / "option_dashboard"


@app.route("/options/")
def options_index():
    return send_from_directory(OPTIONS_DIR, "option_dashboard.html")


@app.route("/options/<path:filename>")
def options_assets(filename):
    return send_from_directory(OPTIONS_DIR, filename)


# ----------------------------------------------------------------- keys API
@app.route("/api/keys", methods=["GET"])
def get_keys():
    """Return masked key status (never raw secrets)."""
    return jsonify(keystore.status())


@app.route("/api/keys", methods=["POST"])
def post_keys():
    """Save submitted keys. Blank fields clear that key."""
    payload = request.get_json(silent=True) or {}
    keystore.save_keys(payload)
    return jsonify({"ok": True, "status": keystore.status()})


# ----------------------------------------------------------------- run API
def _run_pipeline(skip_ai: bool, kr_only: bool = False) -> None:
    cmd = [sys.executable, str(ROOT / "main.py")]
    if kr_only:
        cmd.append("--kr-only")
    elif skip_ai:
        cmd.append("--skip-ai")
    try:
        proc = subprocess.run(
            cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=3600
        )
        with _run_lock:
            _run_state["returncode"] = proc.returncode
            _run_state["log"] = (proc.stdout or "") + (proc.stderr or "")
    except Exception as exc:  # noqa: BLE001
        with _run_lock:
            _run_state["returncode"] = -1
            _run_state["log"] = f"Pipeline failed to launch: {exc}"
    finally:
        with _run_lock:
            _run_state["running"] = False


@app.route("/api/run", methods=["POST"])
def run_pipeline():
    with _run_lock:
        if _run_state["running"]:
            return jsonify({"ok": False, "error": "A run is already in progress."}), 409
        payload = request.get_json(silent=True) or {}
        skip_ai = bool(payload.get("skip_ai", False))
        kr_only = bool(payload.get("kr_only", False))
        _run_state.update(running=True, returncode=None, log="", started_at=_now())

    threading.Thread(target=_run_pipeline, args=(skip_ai, kr_only), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/status", methods=["GET"])
def run_status():
    with _run_lock:
        return jsonify(dict(_run_state))


# ----------------------------------------------------------------- results API
@app.route("/api/dashboard", methods=["GET"])
def dashboard_data():
    if not OUTPUT_JSON.exists():
        return jsonify({"available": False})
    try:
        data = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
        data["available"] = True
        return jsonify(data)
    except (json.JSONDecodeError, OSError) as exc:
        return jsonify({"available": False, "error": str(exc)})


def _now() -> str:
    import datetime as dt

    return dt.datetime.now().isoformat(timespec="seconds")


@app.route("/api/stock/<ticker>", methods=["GET"])
def get_stock_details(ticker):
    ticker = ticker.upper().strip()
    period = request.args.get("period", "1y")
    import pandas as pd
    try:
        with _yf_lock:
            t = yf.Ticker(ticker)
            history = t.history(period=period)
            if not history.empty:
                history = history.dropna(subset=['Close'])
        if not history.empty:
            close_price = history['Close'].iloc[-1]
            if len(history) > 1:
                prev_close = history['Close'].iloc[-2]
            else:
                prev_close = close_price
            change = close_price - prev_close
            change_pct = (change / prev_close) * 100 if prev_close else 0

            dates = history.index.strftime('%Y-%m-%d').tolist()
            opens = [round(float(o), 2) for o in history['Open'].tolist()]
            highs = [round(float(h), 2) for h in history['High'].tolist()]
            lows = [round(float(l), 2) for l in history['Low'].tolist()]
            closes = [round(float(c), 2) for c in history['Close'].tolist()]
            volumes = [int(v) if pd.notna(v) else 0 for v in history['Volume'].tolist()]

            pclose = None
            mcap = None
            try:
                if period == "1y":
                    info = t.info
                    pclose = info.get("previousClose")
                    mcap = info.get("marketCap")
            except Exception:
                pass

            import math
            pclose_val = None
            if pclose is not None:
                try:
                    pclose_f = float(pclose)
                    if not math.isnan(pclose_f) and not math.isinf(pclose_f):
                        pclose_val = round(pclose_f, 2)
                except (ValueError, TypeError):
                    pass

            mcap_val = None
            if mcap is not None:
                try:
                    mcap_f = float(mcap)
                    if not math.isnan(mcap_f) and not math.isinf(mcap_f):
                        mcap_val = int(mcap_f)
                except (ValueError, TypeError):
                    pass

            return jsonify({
                "ticker": ticker,
                "price": round(close_price, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "previous_close": pclose_val if pclose_val is not None else round(float(prev_close), 2),
                "market_cap": mcap_val,
                "chart": {
                    "dates": dates,
                    "opens": opens,
                    "highs": highs,
                    "lows": lows,
                    "closes": closes,
                    "volumes": volumes
                }
            })
        else:
            return jsonify({"error": f"No data found for ticker {ticker}"}), 404
    except Exception as e:
        app.logger.error(f"Error fetching live data for {ticker}: {e}")
        return jsonify({"error": f"Failed to fetch stock data: {str(e)}"}), 500


if __name__ == "__main__":
    import os

    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
