from flask import Flask, render_template_string, request, redirect, session, jsonify
import os
import requests
from supabase import create_client, Client
from datetime import datetime, timezone
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("DASHBOARD_SECRET", "changeme123")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "admin")
ERLC_BASE_URL = "https://api.policeroleplay.community/v1"

def erlc_headers():
    return {"Server-Key": os.environ.get("ERLC_KEY", "")}

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated

BASE_STYLE = """
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', sans-serif; background: #0f1117; color: #e2e8f0; min-height: 100vh; }
  .navbar { background: #1a1d2e; padding: 16px 32px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #2d3148; }
  .navbar h1 { font-size: 20px; font-weight: 700; color: #7c83f7; }
  .navbar a { color: #94a3b8; text-decoration: none; margin-left: 24px; font-size: 14px; }
  .navbar a:hover { color: #7c83f7; }
  .container { max-width: 1200px; margin: 0 auto; padding: 32px 24px; }
  .card { background: #1a1d2e; border: 1px solid #2d3148; border-radius: 12px; padding: 24px; margin-bottom: 24px; }
  .card h2 { font-size: 18px; font-weight: 600; margin-bottom: 16px; color: #c4c9ff; }
  .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .stat { background: #1a1d2e; border: 1px solid #2d3148; border-radius: 12px; padding: 20px; text-align: center; }
  .stat .value { font-size: 32px; font-weight: 700; color: #7c83f7; }
  .stat .label { font-size: 13px; color: #64748b; margin-top: 4px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; padding: 12px 16px; color: #64748b; border-bottom: 1px solid #2d3148; font-weight: 500; }
  td { padding: 12px 16px; border-bottom: 1px solid #1e2235; }
  tr:hover td { background: #1e2235; }
  .badge { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 500; }
  .badge-green { background: #14532d; color: #4ade80; }
  .badge-red { background: #7f1d1d; color: #f87171; }
  .badge-orange { background: #7c2d12; color: #fb923c; }
  .badge-blue { background: #1e3a5f; color: #60a5fa; }
  .btn { display: inline-block; padding: 10px 20px; border-radius: 8px; border: none; cursor: pointer; font-size: 14px; font-weight: 500; text-decoration: none; }
  .btn-primary { background: #7c83f7; color: white; }
  .btn-primary:hover { background: #6366f1; }
  .btn-danger { background: #dc2626; color: white; }
  .btn-danger:hover { background: #b91c1c; }
  input, select { background: #0f1117; border: 1px solid #2d3148; border-radius: 8px; padding: 10px 14px; color: #e2e8f0; font-size: 14px; width: 100%; margin-bottom: 12px; }
  input:focus, select:focus { outline: none; border-color: #7c83f7; }
  label { display: block; font-size: 13px; color: #94a3b8; margin-bottom: 4px; }
  .form-group { margin-bottom: 16px; }
  .alert { padding: 12px 16px; border-radius: 8px; margin-bottom: 16px; font-size: 14px; }
  .alert-success { background: #14532d; color: #4ade80; border: 1px solid #166534; }
  .alert-error { background: #7f1d1d; color: #f87171; border: 1px solid #991b1b; }
  .nav-tabs { display: flex; gap: 8px; margin-bottom: 24px; }
  .nav-tab { padding: 8px 16px; border-radius: 8px; font-size: 14px; cursor: pointer; text-decoration: none; color: #94a3b8; }
  .nav-tab.active, .nav-tab:hover { background: #2d3148; color: #c4c9ff; }
</style>
"""

LOGIN_HTML = BASE_STYLE + """
<div style="display:flex;align-items:center;justify-content:center;min-height:100vh;">
  <div style="background:#1a1d2e;border:1px solid #2d3148;border-radius:16px;padding:48px;width:380px;">
    <h1 style="text-align:center;color:#7c83f7;font-size:24px;margin-bottom:8px;">MSRP Dashboard</h1>
    <p style="text-align:center;color:#64748b;font-size:14px;margin-bottom:32px;">Maryland State Roleplay</p>
    {% if error %}<div class="alert alert-error">{{ error }}</div>{% endif %}
    <form method="POST">
      <div class="form-group">
        <label>Password</label>
        <input type="password" name="password" placeholder="Enter dashboard password" autofocus>
      </div>
      <button type="submit" class="btn btn-primary" style="width:100%;">Login</button>
    </form>
  </div>
</div>
"""

NAVBAR = """
<div class="navbar">
  <h1>🚔 MSRP Dashboard</h1>
  <div>
    <a href="/">Home</a>
    <a href="/logs">Audit Logs</a>
    <a href="/erlc">ER:LC</a>
    <a href="/settings">Settings</a>
    <a href="/logout">Logout</a>
  </div>
</div>
"""

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == DASHBOARD_PASSWORD:
            session["logged_in"] = True
            return redirect("/")
        error = "Incorrect password."
    return render_template_string(BASE_STYLE + LOGIN_HTML, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/")
@login_required
def index():
    try:
        logs = supabase.table("audit_logs").select("*").execute().data or []
        configs = supabase.table("guild_configs").select("*").execute().data or []
        total_logs = len(logs)
        total_guilds = len(configs)
        recent = logs[-5:][::-1]
    except:
        logs, configs, recent = [], [], []
        total_logs, total_guilds = 0, 0

    rows = ""
    for log in recent:
        action = log.get("action", "N/A").capitalize()
        badge = "badge-green" if action.lower() == "promote" else "badge-red" if action.lower() == "infraction" else "badge-orange" if action.lower() == "void" else "badge-blue"
        voided = " <span class='badge badge-orange'>VOIDED</span>" if log.get("is_voided") else ""
        try:
            ts = datetime.fromisoformat(log["timestamp"]).strftime("%b %d, %Y %H:%M")
        except:
            ts = "N/A"
        rows += f"""
        <tr>
          <td><span class='badge {badge}'>{action}</span>{voided}</td>
          <td>{log.get('target_user','N/A')}</td>
          <td>{log.get('performed_by','N/A')}</td>
          <td>{log.get('reason','N/A')}</td>
          <td>{ts}</td>
        </tr>"""

    html = BASE_STYLE + NAVBAR + f"""
    <div class="container">
      <div class="stat-grid">
        <div class="stat"><div class="value">{total_logs}</div><div class="label">Total Actions Logged</div></div>
        <div class="stat"><div class="value">{total_guilds}</div><div class="label">Servers Configured</div></div>
      </div>
      <div class="card">
        <h2>Recent Activity</h2>
        <table>
          <thead><tr><th>Action</th><th>Target</th><th>By</th><th>Reason</th><th>Time</th></tr></thead>
          <tbody>{rows if rows else '<tr><td colspan="5" style="text-align:center;color:#64748b;">No logs yet</td></tr>'}</tbody>
        </table>
      </div>
    </div>"""
    return render_template_string(html)

@app.route("/logs")
@login_required
def logs():
    try:
        data = supabase.table("audit_logs").select("*").order("timestamp", desc=True).execute().data or []
    except:
        data = []

    rows = ""
    for log in data:
        action = log.get("action", "N/A").capitalize()
        badge = "badge-green" if action.lower() == "promote" else "badge-red" if action.lower() == "infraction" else "badge-orange" if action.lower() == "void" else "badge-blue"
        voided = " <span class='badge badge-orange'>VOIDED</span>" if log.get("is_voided") else ""
        try:
            ts = datetime.fromisoformat(log["timestamp"]).strftime("%b %d, %Y %H:%M")
        except:
            ts = "N/A"
        rows += f"""
        <tr>
          <td>{log.get('id','N/A')}</td>
          <td><span class='badge {badge}'>{action}</span>{voided}</td>
          <td>{log.get('target_user','N/A')}</td>
          <td>{log.get('role_name','N/A')}</td>
          <td>{log.get('performed_by','N/A')}</td>
          <td>{log.get('reason','N/A')}</td>
          <td>{log.get('notes') or '—'}</td>
          <td>{ts}</td>
        </tr>"""

    html = BASE_STYLE + NAVBAR + f"""
    <div class="container">
      <div class="card">
        <h2>📋 Audit Logs</h2>
        <table>
          <thead><tr><th>ID</th><th>Action</th><th>Target</th><th>Role</th><th>By</th><th>Reason</th><th>Notes</th><th>Time</th></tr></thead>
          <tbody>{rows if rows else '<tr><td colspan="8" style="text-align:center;color:#64748b;">No logs yet</td></tr>'}</tbody>
        </table>
      </div>
    </div>"""
    return render_template_string(html)

@app.route("/erlc")
@login_required
def erlc():
    server_data = {}
    players = []
    killlogs = []
    modcalls = []
    error = None

    try:
        r = requests.get(f"{ERLC_BASE_URL}/server", headers=erlc_headers(), timeout=10)
        if r.status_code == 200:
            server_data = r.json()
        elif r.status_code == 422:
            error = "No active ER:LC session running."
    except Exception as e:
        error = str(e)

    if not error:
        try:
            r = requests.get(f"{ERLC_BASE_URL}/server/players", headers=erlc_headers(), timeout=10)
            if r.status_code == 200:
                players = r.json()
        except: pass

        try:
            r = requests.get(f"{ERLC_BASE_URL}/server/killlogs", headers=erlc_headers(), timeout=10)
            if r.status_code == 200:
                killlogs = r.json()[:10]
        except: pass

        try:
            r = requests.get(f"{ERLC_BASE_URL}/server/modcalls", headers=erlc_headers(), timeout=10)
            if r.status_code == 200:
                modcalls = r.json()
        except: pass

    player_rows = "".join(f"<tr><td>{p.get('Player','?')}</td><td>{p.get('Team','?')}</td></tr>" for p in players) or "<tr><td colspan='2' style='text-align:center;color:#64748b;'>No players</td></tr>"
    kill_rows = "".join(f"<tr><td>{k.get('Killer','?')}</td><td>{k.get('Killed','?')}</td><td>{k.get('Kill','?')}</td></tr>" for k in killlogs) or "<tr><td colspan='3' style='text-align:center;color:#64748b;'>No kill logs</td></tr>"
    mod_rows = "".join(f"<tr><td>{m.get('Caller','?')}</td><td>{m.get('Reason','?')}</td></tr>" for m in modcalls) or "<tr><td colspan='2' style='text-align:center;color:#64748b;'>No mod calls</td></tr>"

    status_section = f"""
    <div class="stat-grid">
      <div class="stat"><div class="value">{server_data.get('CurrentPlayers', 0)}</div><div class="label">Players Online</div></div>
      <div class="stat"><div class="value">{server_data.get('MaxPlayers', 0)}</div><div class="label">Max Players</div></div>
      <div class="stat"><div class="value">{server_data.get('Queue', 0)}</div><div class="label">In Queue</div></div>
      <div class="stat"><div class="value">{server_data.get('JoinKey', 'N/A')}</div><div class="label">Join Key</div></div>
    </div>""" if server_data else ""

    error_section = f"<div class='alert alert-error'>{error}</div>" if error else ""

    html = BASE_STYLE + NAVBAR + f"""
    <div class="container">
      {error_section}
      {status_section}
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;">
        <div class="card">
          <h2>🎮 Players Online ({len(players)})</h2>
          <table><thead><tr><th>Player</th><th>Team</th></tr></thead><tbody>{player_rows}</tbody></table>
        </div>
        <div class="card">
          <h2>📢 Mod Calls ({len(modcalls)})</h2>
          <table><thead><tr><th>Caller</th><th>Reason</th></tr></thead><tbody>{mod_rows}</tbody></table>
        </div>
      </div>
      <div class="card">
        <h2>💀 Recent Kill Logs</h2>
        <table><thead><tr><th>Killer</th><th>Killed</th><th>Weapon</th></tr></thead><tbody>{kill_rows}</tbody></table>
      </div>
    </div>"""
    return render_template_string(html)

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    message = None
    error = None

    if request.method == "POST":
        action = request.form.get("action")
        if action == "password":
            new_pass = request.form.get("new_password")
            if new_pass:
                os.environ["DASHBOARD_PASSWORD"] = new_pass
                message = "Password updated for this session! Update DASHBOARD_PASSWORD in Railway to make it permanent."
        elif action == "guild_config":
            guild_id = request.form.get("guild_id")
            session_channel = request.form.get("session_channel_id", "")
            log_channel = request.form.get("log_channel_id", "")
            if guild_id:
                try:
                    existing = supabase.table("guild_configs").select("guild_id").eq("guild_id", guild_id).execute()
                    update = {}
                    if session_channel:
                        update["session_channel_id"] = session_channel
                    if log_channel:
                        update["log_channel_id"] = log_channel
                    if update:
                        if existing.data:
                            supabase.table("guild_configs").update(update).eq("guild_id", guild_id).execute()
                        else:
                            supabase.table("guild_configs").insert({"guild_id": guild_id, **update}).execute()
                        message = "Server settings updated!"
                except Exception as e:
                    error = str(e)

    try:
        configs = supabase.table("guild_configs").select("*").execute().data or []
    except:
        configs = []

    config_rows = "".join(f"""
    <tr>
      <td>{c.get('guild_id','N/A')}</td>
      <td>{c.get('log_channel_id') or '—'}</td>
      <td>{c.get('session_channel_id') or '—'}</td>
      <td>{c.get('hr_role_id') or '—'}</td>
    </tr>""" for c in configs) or "<tr><td colspan='4' style='text-align:center;color:#64748b;'>No servers configured yet</td></tr>"

    msg_html = f"<div class='alert alert-success'>{message}</div>" if message else ""
    err_html = f"<div class='alert alert-error'>{error}</div>" if error else ""

    html = BASE_STYLE + NAVBAR + f"""
    <div class="container">
      {msg_html}{err_html}
      <div class="card">
        <h2>⚙️ Server Configurations</h2>
        <table>
          <thead><tr><th>Guild ID</th><th>Log Channel</th><th>Session Channel</th><th>HR Role</th></tr></thead>
          <tbody>{config_rows}</tbody>
        </table>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;">
        <div class="card">
          <h2>Update Server Settings</h2>
          <form method="POST">
            <input type="hidden" name="action" value="guild_config">
            <div class="form-group"><label>Guild ID</label><input name="guild_id" placeholder="Your Discord server ID"></div>
            <div class="form-group"><label>Session Channel ID</label><input name="session_channel_id" placeholder="Channel ID for session pings"></div>
            <div class="form-group"><label>Log Channel ID</label><input name="log_channel_id" placeholder="Channel ID for logs"></div>
            <button type="submit" class="btn btn-primary">Save Settings</button>
          </form>
        </div>
        <div class="card">
          <h2>Change Dashboard Password</h2>
          <form method="POST">
            <input type="hidden" name="action" value="password">
            <div class="form-group"><label>New Password</label><input type="password" name="new_password" placeholder="New password"></div>
            <button type="submit" class="btn btn-primary">Update Password</button>
          </form>
        </div>
      </div>
    </div>"""
    return render_template_string(html)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
