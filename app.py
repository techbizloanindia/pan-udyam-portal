"""
PAN → Udyam Batch Lookup Portal
--------------------------------
A small internal Flask web app:
  1. User uploads an Excel file with a "PAN" column (drag-and-drop or picker).
  2. Server processes PANs in a background thread, calling the Gridlines
     "Fetch MSME by PAN" API for each row.
  3. The page polls a status endpoint and shows live progress + a results
     table as each PAN completes.
  4. Once done, the results Excel file is available to download.

IMPORTANT — SECURITY / COMPLIANCE:
  - PAN numbers are sensitive PII. Run this only on an internal/secured
    network (e.g. Bizloan's internal server or your own machine), never
    on a public host without authentication.
  - Never commit your real API key into version control. Set it via the
    GRIDLINES_API_KEY environment variable instead of hardcoding it.

SETUP:
  1. pip install -r requirements.txt
  2. export GRIDLINES_API_KEY="your_real_key_here"      (Windows PowerShell: $env:GRIDLINES_API_KEY="your_real_key_here")
  3. python app.py
  4. Open http://localhost:5000 in your browser
"""

import os
import uuid
import time
import threading
from datetime import datetime

import pandas as pd
import requests
from flask import Flask, render_template, request, send_file, jsonify

# ----------------------- CONFIG -----------------------
GRIDLINES_API_KEY = os.environ.get("GRIDLINES_API_KEY", "")  # set via env var only — never hardcode a real key here
API_URL = "https://api.gridlines.io/msme-api/udyam/fetch-by-pan"
DETAILED_RESPONSE = True          # needed for social_category, enterprise details
CONSENT = "Y"
DELAY_BETWEEN_CALLS_SEC = 1.0     # be polite to the API / avoid rate limits

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
ALLOWED_EXTENSIONS = {".xlsx", ".xls"}
# --------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-secret-in-production")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

# In-memory job store. Fine for a single-user internal tool;
# swap for Redis/DB if this needs to support many concurrent users.
JOBS = {}
JOBS_LOCK = threading.Lock()


def fetch_udyam_by_pan(pan_number: str) -> dict:
    """Call the Gridlines Fetch MSME by PAN API for a single PAN."""
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-API-Key": GRIDLINES_API_KEY,
        "X-Auth-Type": "API-Key",
        "X-Reference-ID": f"bzln-{uuid.uuid4().hex}",
    }
    payload = {
        "pan_number": pan_number,
        "detailed_response": DETAILED_RESPONSE,
        "consent": CONSENT,
    }

    try:
        resp = requests.post(API_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data", {})
        enterprise_data = data.get("enterprise_data") or {}
        return {
            "PAN": pan_number,
            "http_status": resp.status_code,
            "response_code": data.get("code"),
            "message": data.get("message"),
            "udyam_number": data.get("udyam_number", ""),
            "social_category": enterprise_data.get("social_category", ""),
            "enterprise_name": enterprise_data.get("name", ""),
            "enterprise_type": enterprise_data.get("enterprise_type", ""),
            "error": "",
        }
    except requests.exceptions.HTTPError as e:
        body_text = ""
        try:
            body_text = e.response.text[:500]
        except Exception:
            pass
        return {
            "PAN": pan_number, "http_status": getattr(e.response, "status_code", ""),
            "response_code": "", "message": "", "udyam_number": "",
            "social_category": "", "enterprise_name": "", "enterprise_type": "",
            "error": f"HTTP error: {e} | Response body: {body_text}",
        }
    except Exception as e:
        return {
            "PAN": pan_number, "http_status": "", "response_code": "", "message": "",
            "udyam_number": "", "social_category": "", "enterprise_name": "",
            "enterprise_type": "", "error": f"Request failed: {e}",
        }


def allowed_file(filename: str) -> bool:
    return os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS


def _status_label(result: dict) -> str:
    """Classify a single result row for the UI: success / no_record / error."""
    if result.get("error"):
        return "error"
    code = str(result.get("response_code") or "")
    if code == "1011":
        return "no_record"
    if code in ("1014", "1016"):
        return "success"
    if code == "1015":
        return "cancelled"
    return "unknown"


def run_job(job_id: str, input_path: str):
    """Background worker: reads the Excel, calls the API per PAN, updates JOBS progress."""
    try:
        df_in = pd.read_excel(input_path)
    except Exception as e:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error_message"] = f"Could not read the Excel file: {e}"
        return

    if "PAN" not in df_in.columns:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error_message"] = (
                f"Uploaded file must have a column named 'PAN'. Found columns: {list(df_in.columns)}"
            )
        return

    pans = df_in["PAN"].dropna().astype(str).str.strip().tolist()
    if not pans:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error_message"] = "No PAN numbers found in the uploaded file."
        return

    with JOBS_LOCK:
        JOBS[job_id]["total"] = len(pans)
        JOBS[job_id]["status"] = "processing"

    results = []
    for i, pan in enumerate(pans):
        result = fetch_udyam_by_pan(pan)
        result["status_label"] = _status_label(result)
        results.append(result)

        with JOBS_LOCK:
            JOBS[job_id]["completed"] = i + 1
            JOBS[job_id]["results"] = list(results)  # snapshot for polling

        if i < len(pans) - 1:
            time.sleep(DELAY_BETWEEN_CALLS_SEC)

    df_out = pd.DataFrame([{k: v for k, v in r.items() if k != "status_label"} for r in results])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"udyam_results_{timestamp}.xlsx"
    output_path = os.path.join(RESULTS_DIR, output_filename)
    df_out.to_excel(output_path, index=False)

    with JOBS_LOCK:
        JOBS[job_id]["status"] = "done"
        JOBS[job_id]["output_path"] = output_path
        JOBS[job_id]["output_filename"] = output_filename


@app.route("/", methods=["GET"])
def index():
    api_key_missing = not GRIDLINES_API_KEY
    return render_template("index.html", api_key_missing=api_key_missing)


@app.route("/upload", methods=["POST"])
def upload():
    if not GRIDLINES_API_KEY:
        return jsonify({"error": "Server is missing GRIDLINES_API_KEY. Set it and restart the app."}), 400

    file = request.files.get("excel_file")
    if not file or file.filename == "":
        return jsonify({"error": "Please choose an Excel file to upload."}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Only .xlsx or .xls files are supported."}), 400

    job_id = uuid.uuid4().hex[:12]
    input_path = os.path.join(UPLOAD_DIR, f"{job_id}_input.xlsx")
    file.save(input_path)

    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "starting",
            "total": 0,
            "completed": 0,
            "results": [],
            "input_filename": file.filename,
        }

    thread = threading.Thread(target=run_job, args=(job_id, input_path), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>", methods=["GET"])
def status(job_id):
    since = request.args.get("since", default=0, type=int)

    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Unknown job id."}), 404
        snapshot = dict(job)

    all_results = snapshot.get("results", [])
    response = {
        "status": snapshot["status"],
        "total": snapshot.get("total", 0),
        "completed": snapshot.get("completed", 0),
        "results": all_results[since:],   # only new rows since the client's last poll
        "input_filename": snapshot.get("input_filename", ""),
    }
    if snapshot["status"] == "error":
        response["error_message"] = snapshot.get("error_message", "Unknown error.")
    if snapshot["status"] == "done":
        response["download_url"] = f"/download/{job_id}"
    return jsonify(response)


@app.route("/download/<job_id>", methods=["GET"])
def download(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job or job.get("status") != "done":
            return jsonify({"error": "Result not ready."}), 404
        output_path = job["output_path"]
        output_filename = job["output_filename"]

    return send_file(
        output_path,
        as_attachment=True,
        download_name=output_filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    # debug=False in anything resembling production; bind to localhost only unless you
    # deliberately want it reachable on your internal network (host="0.0.0.0").
    app.run(host="127.0.0.1", port=5000, debug=True, threaded=True)
