"""
PAN → Udyam Batch Lookup — Streamlit version
----------------------------------------------
Upload an Excel file with a "PAN" column, fetch Udyam registration details
(including social category) from the Gridlines API for each row, and
download the results as Excel.

IMPORTANT — SECURITY / COMPLIANCE:
  - PAN numbers are sensitive financial PII. Get sign-off from your
    IT/compliance team before hosting this anywhere outside your
    organization's own infrastructure (including Streamlit Community Cloud,
    which is third-party hosting).
  - Never hardcode your real API key or app password. Use environment
    variables or Streamlit secrets (see README.md).

RUN LOCALLY:
  1. pip install -r requirements.txt
  2. export GRIDLINES_API_KEY="your_real_key_here"
  3. export APP_ACCESS_PASSWORD="choose_a_shared_password"   (optional but recommended)
  4. streamlit run streamlit_app.py
"""

import io
import os
import time
import uuid

import pandas as pd
import requests
import streamlit as st

# ----------------------- CONFIG -----------------------
def _get_secret(name: str, default: str = "") -> str:
    # Works whether the value comes from Streamlit Cloud "Secrets", a local
    # .streamlit/secrets.toml, or a plain environment variable.
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name, default)


GRIDLINES_API_KEY = _get_secret("GRIDLINES_API_KEY")
APP_ACCESS_PASSWORD = _get_secret("APP_ACCESS_PASSWORD")  # leave blank to disable the gate
API_URL = "https://api.gridlines.io/msme-api/udyam/fetch-by-pan"
DETAILED_RESPONSE = True
CONSENT = "Y"
DELAY_BETWEEN_CALLS_SEC = 1.0
# --------------------------------------------------------

st.set_page_config(page_title="PAN → Udyam Batch Lookup", page_icon="📊", layout="centered")

STATUS_LABELS = {
    "success": "✅ Found",
    "no_record": "⬜ No record",
    "cancelled": "⚠️ Cancelled",
    "error": "❌ Error",
    "unknown": "❔ Unknown",
}


def fetch_udyam_by_pan(pan_number: str) -> dict:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-API-Key": GRIDLINES_API_KEY,
        "X-Auth-Type": "API-Key",
        "X-Reference-ID": f"bzln-{uuid.uuid4().hex}",
    }
    payload = {"pan_number": pan_number, "detailed_response": DETAILED_RESPONSE, "consent": CONSENT}

    try:
        resp = requests.post(API_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data", {})
        enterprise_data = data.get("enterprise_data") or {}
        code = str(data.get("code") or "")
        status_label = (
            "success" if code in ("1014", "1016")
            else "no_record" if code == "1011"
            else "cancelled" if code == "1015"
            else "unknown"
        )
        return {
            "PAN": pan_number,
            "http_status": resp.status_code,
            "response_code": code,
            "message": data.get("message"),
            "udyam_number": data.get("udyam_number", ""),
            "social_category": enterprise_data.get("social_category", ""),
            "enterprise_name": enterprise_data.get("name", ""),
            "enterprise_type": enterprise_data.get("enterprise_type", ""),
            "error": "",
            "status_label": status_label,
        }
    except requests.exceptions.HTTPError as e:
        body_text = ""
        try:
            body_text = e.response.text[:500]
        except Exception:
            pass
        return {
            "PAN": pan_number, "http_status": getattr(e.response, "status_code", ""),
            "response_code": "", "message": "", "udyam_number": "", "social_category": "",
            "enterprise_name": "", "enterprise_type": "",
            "error": f"HTTP error: {e} | Response body: {body_text}", "status_label": "error",
        }
    except Exception as e:
        return {
            "PAN": pan_number, "http_status": "", "response_code": "", "message": "",
            "udyam_number": "", "social_category": "", "enterprise_name": "", "enterprise_type": "",
            "error": f"Request failed: {e}", "status_label": "error",
        }


def check_password() -> bool:
    """Simple shared-password gate. Returns True once the correct password is entered."""
    if not APP_ACCESS_PASSWORD:
        return True  # gate disabled — not recommended for PII, but allowed if explicitly unset

    if st.session_state.get("authed"):
        return True

    st.markdown("### 🔒 Restricted access")
    st.caption("This tool processes customer PAN data. Enter the shared access password to continue.")
    pw = st.text_input("Access password", type="password")
    if st.button("Unlock"):
        if pw == APP_ACCESS_PASSWORD:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    return buffer.getvalue()


def main():
    st.title("📊 PAN → Udyam Batch Lookup")
    st.caption("Upload a PAN list · Fetch Udyam & social category data · Export results to Excel")

    if not check_password():
        st.stop()

    if not GRIDLINES_API_KEY:
        st.warning("⚠️ GRIDLINES_API_KEY is not configured. Set it as a Streamlit secret or environment variable.")
        st.stop()

    uploaded_file = st.file_uploader(
        "Excel file (.xlsx) with a column named exactly \"PAN\"",
        type=["xlsx", "xls"],
    )

    if uploaded_file is None:
        st.info("Upload a file to get started. Rows are processed one at a time to respect API rate limits — a 200-300 row file can take several minutes, so keep this tab open once you start.")
        return

    try:
        df_in = pd.read_excel(uploaded_file)
    except Exception as e:
        st.error(f"Could not read the Excel file: {e}")
        return

    if "PAN" not in df_in.columns:
        st.error(f"Uploaded file must have a column named 'PAN'. Found columns: {list(df_in.columns)}")
        return

    pans = df_in["PAN"].dropna().astype(str).str.strip().tolist()
    if not pans:
        st.error("No PAN numbers found in the uploaded file.")
        return

    st.write(f"**{len(pans)} PAN(s)** found in `{uploaded_file.name}`.")

    if st.button("🚀 Fetch Udyam Details", type="primary"):
        progress_bar = st.progress(0.0, text=f"Starting… 0 / {len(pans)}")
        table_placeholder = st.empty()
        eta_placeholder = st.empty()

        results = []
        start_time = time.time()

        for i, pan in enumerate(pans):
            result = fetch_udyam_by_pan(pan)
            results.append(result)

            fraction = (i + 1) / len(pans)
            progress_bar.progress(fraction, text=f"Processing PAN {i + 1} of {len(pans)}")

            display_df = pd.DataFrame(results)[
                ["PAN", "status_label", "udyam_number", "social_category"]
            ].rename(columns={
                "status_label": "Result", "udyam_number": "Udyam Number", "social_category": "Social Category",
            })
            display_df["Result"] = display_df["Result"].map(STATUS_LABELS).fillna(display_df["Result"])
            # Show the results in a fixed-height, scrollable container so 200-300 rows never blow up the page
            table_placeholder.dataframe(display_df, height=360, use_container_width=True)

            elapsed = time.time() - start_time
            rate = elapsed / (i + 1)
            remaining = (len(pans) - i - 1) * rate
            eta_placeholder.caption(f"⏳ Estimated time remaining: ~{int(remaining // 60)}m {int(remaining % 60)}s")

            if i < len(pans) - 1:
                time.sleep(DELAY_BETWEEN_CALLS_SEC)

        eta_placeholder.empty()
        st.success("All done!")

        df_out = pd.DataFrame([{k: v for k, v in r.items() if k != "status_label"} for r in results])

        counts = pd.Series([r["status_label"] for r in results]).value_counts()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total", len(results))
        c2.metric("Found", int(counts.get("success", 0)))
        c3.metric("No Record", int(counts.get("no_record", 0)))
        c4.metric("Errors", int(counts.get("error", 0)))

        st.download_button(
            "⬇️ Download Results Excel",
            data=to_excel_bytes(df_out),
            file_name=f"udyam_results_{time.strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )


if __name__ == "__main__":
    main()
