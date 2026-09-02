# Deploying the Streamlit version (streamlit_app.py)

⚠️ **Before you deploy anywhere:** this tool processes customer PAN numbers —
sensitive financial PII. Get your IT/compliance team's sign-off on *where*
this is allowed to run before making it available to your organization,
regardless of which option below you pick.

## Option A — Self-host on an internal server (recommended for PAN data)

This keeps everything inside Bizloan/Vegafin's own network — no third party
ever sees the data.

1. Copy this folder to an internal server (or a VM your IT team provisions).
2. `pip install -r requirements.txt`
3. Set your secrets as environment variables on that server:
   ```
   export GRIDLINES_API_KEY="your_real_production_key"
   export APP_ACCESS_PASSWORD="a_shared_password_for_your_team"
   ```
4. Run it so it stays up:
   ```
   streamlit run streamlit_app.py --server.address=0.0.0.0 --server.port=8501
   ```
   For a production-grade always-on setup, run this under a process
   supervisor (systemd, pm2, or Docker + a restart policy) instead of a
   plain terminal, and put it behind your internal reverse proxy (Nginx/IIS)
   with HTTPS.
5. Colleagues on your office network/VPN open `http://<server-ip>:8501`.
6. Anyone opening it will be asked for `APP_ACCESS_PASSWORD` before they can
   upload anything — share that password only with people who should have
   access, and rotate it periodically.

**Optional hardening:** restrict the port to your internal network/VPN only
via firewall rules, so it's unreachable from the public internet even if
someone mistypes the server's public IP.

## Option B — Streamlit Community Cloud (third-party hosting)

Streamlit Community Cloud can host **private apps** with an email-based
viewer allow-list (viewers sign in via Google OAuth or a one-time emailed
link) — but the app and its traffic still run on Streamlit/Snowflake's
infrastructure, outside your organization's network. Only use this path if
your compliance team has explicitly approved third-party hosting of PAN
data.

1. Push this project to a GitHub repo (private repo recommended).
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with
   GitHub, and deploy from that repo, pointing at `streamlit_app.py`.
3. In the app's **Settings → Secrets**, add:
   ```toml
   GRIDLINES_API_KEY = "your_real_production_key"
   APP_ACCESS_PASSWORD = "a_shared_password_for_your_team"
   ```
4. In **Settings → Sharing**, set the app to **private** and add your
   colleagues' emails to the viewer list — this is on top of the in-app
   password gate, giving you two layers of access control.
5. Send them the app URL from the Share panel; they'll need to sign in
   (Google OAuth or emailed link) *and* know the shared password.

## Running it locally first (either option)

```
pip install -r requirements.txt
export GRIDLINES_API_KEY="your_real_key"
export APP_ACCESS_PASSWORD="test123"     # optional, omit to disable the gate
streamlit run streamlit_app.py
```
Opens automatically at `http://localhost:8501`.

## Notes

- `APP_ACCESS_PASSWORD` is a single shared password, not per-user accounts.
  It's meant to stop random/accidental access, not to be a substitute for
  proper authentication. If you need individual logins and audit trails,
  ask and I can add a small user-list-based auth layer instead.
- The Flask version (`app.py`) still works if you'd rather self-host that
  instead — both read/write the same kind of Excel files.
