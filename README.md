# PAN → Udyam Batch Lookup Portal

A small internal web app: upload an Excel file with a "PAN" column, it calls the
Gridlines "Fetch MSME by PAN" API for each row, and returns a downloadable Excel
file with the Udyam number, social category, and other details.

## ⚠️ Before you run this

- **PAN numbers are sensitive financial PII.** Run this only on an internal /
  secured network (your own machine, or an internal Bizloan/Vegafin server) —
  never expose it on the open internet without authentication in front of it.
- **Never hardcode or commit your real API key.** This app reads it from an
  environment variable.

## Setup

1. Install Python 3.9+ if you don't already have it.
2. From this folder, install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Set your Gridlines API key as an environment variable:
   - macOS/Linux: `export GRIDLINES_API_KEY="your_real_key_here"`
   - Windows (cmd): `set GRIDLINES_API_KEY=your_real_key_here`
   - Windows (PowerShell): `$env:GRIDLINES_API_KEY="your_real_key_here"`
4. Run the app:
   ```
   python app.py
   ```
5. Open **http://localhost:5000** in your browser.

## Using it

1. Prepare an Excel file with a column named exactly `PAN`, one PAN per row.
2. Upload it on the page and click **Fetch Udyam Details**.
3. Wait — it processes one PAN per second by default (adjustable in `app.py`
   via `DELAY_BETWEEN_CALLS_SEC`) to stay polite to the API's rate limits.
4. A results file (`udyam_results_<timestamp>.xlsx`) downloads automatically,
   containing: `PAN`, `http_status`, `response_code`, `message`,
   `udyam_number`, `social_category`, `enterprise_name`, `enterprise_type`,
   and `error`.

## Making it reachable by others on your office network (optional)

By default the app only listens on `127.0.0.1` (your own machine). If you want
colleagues on the same office network to use it, in `app.py` change:
```python
app.run(host="127.0.0.1", port=5000, debug=True)
```
to:
```python
app.run(host="0.0.0.0", port=5000, debug=False)
```
Only do this on a trusted internal network, and consider adding basic
authentication in front of it (e.g. via a reverse proxy like Nginx with basic
auth) since this handles customer PAN data.

## Notes

- `detailed_response` is set to `True` in `app.py` because `social_category`
  and other enterprise fields only come back in the detailed response. Check
  with Gridlines/OnGrid whether detailed calls are billed differently.
- For very large files (hundreds+ of PANs), consider moving processing to a
  background job/queue instead of a single request — right now the browser
  waits for the whole batch to finish before the download starts.
