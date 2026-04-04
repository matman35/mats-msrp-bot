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
  .navbar { background: #1a1d2e; padding: 16px 32px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #2d3148; position: sticky; top: 0; z-index: 100; }
  .navbar h1 { font-size: 20px; font-weight: 700; color: #7c83f7; }
  .navbar a { color: #94a3b8; text-decoration: none; margin-left: 24px; font-size: 14px; transition: color 0.2s; }
  .navbar a:hover { color: #7c83f7; }
  .container { max-width: 1200px; margin: 0 auto; padding: 32px 24px; }
  .card { background: #1a1d2e; border: 1px solid #2d3148; border-radius: 12px; padding: 24px; margin-bottom: 24px; }
  .card h2 { font-size: 18px; font-weight: 600; margin-bottom: 20px; color: #c4c9ff; border-bottom: 1px solid #2d3148; padding-bottom: 12px; }
  .card h3 { font-size: 15px; font-weight: 600; margin-bottom: 14px; color: #94a3b8; }
  .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .stat { background: #1a1d2e; border: 1px solid #2d3148; border-radius: 12px; padding: 20px; text-align: center; }
  .stat .value { font-size: 32px; font-weight: 700; color: #7c83f7; }
  .stat .label { font-size: 13px; color: #64748b; margin-top: 4px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; padding: 12px 16px; color: #64748b; border-bottom: 1px solid #2d3148; font-weight: 500; font-size: 13px; }
  td { padding: 12px 16px; border-bottom: 1px solid #1e2235; font-size: 13px; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #1e2235; }
  .badge { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 11px; font-weight: 600; }
  .badge-green { background: #14532d; color: #4ade80; }
  .badge-red { background: #7f1d1d; color: #f87171; }
  .badge-orange { background: #7c2d12; color: #fb923c; }
  .badge-blue { background: #1e3a5f; color: #60a5fa; }
  .badge-purple { background: #3b0764; color: #c084fc; }
  .btn { display: inline-block; padding: 10px 20px; border-radius: 8px; border: none; cursor: pointer; font-size: 14px; font-weight: 500; text-decoration: none; transition: background 0.2s; }
  .btn-primary { background: #7c83f7; color: white; }
  .btn-primary:hover { background: #6366f1; }
  .btn-sm { padding: 6px 14px; font-size: 13px; }
  input, select, textarea { background: #0f1117; border: 1px solid #2d3148; border-radius: 8px; padding: 10px 14px; color: #e2e8f0; font-size: 14px; width: 100%; transition: border-color 0.2s; }
  input:focus, select:focus, textarea:focus { outline: none; border-color: #7c83f7; }
  label { display: block; font-size: 12px; color: #94a3b8; margin-bottom: 6px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }
  .form-group { margin-bottom: 16px; }
  .form-hint { font-size: 11px; color: #475569; margin-top: 4px; }
  .alert { padding: 12px 16px; border-radius: 8px; margin-bottom: 16px; font-size: 14px; }
  .alert-success { background: #14532d; color: #4ade80; border: 1px solid #166534; }
  .alert-error { background: #7f1d1d; color: #f87171; border: 1px solid #991b1b; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
  .grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 24px; }
  .section-divider { border: none; border-top: 1px solid #2d3148; margin: 20px 0; }
  .page-title { font-size: 24px; font-weight: 700; color: #c4c9ff; margin-bottom: 8px; }
  .page-subtitle { font-size: 14px; color: #64748b; margin-bottom: 24px; }
  @media (max-width: 768px) { .grid-2, .grid-3 { grid-template-columns: 1fr; } }
</style>
"""

NAVBAR = """
<div class="navbar">
  <h1>🚔 MSRP Dashboard</h1>
  <div>
    <a href="/">🏠 Home</a>
    <a href="/logs">📋 Logs</a>
    <a href="/erlc">🎮 ER:LC</a>
    <a href="/settings">⚙️ Settings</a>
    <a href="/logout" style="color:#f87171;">Logout</a>
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
    html = BASE_STYLE + """
    <div style="display:flex;align-items:center;justify-content:center;min-height:100vh;">
      <div style="background:#1a1d2e;border:1px solid #2d3148;border-radius:16px;padding:48px;width:400px;">
        <div style="text-align:center;margin-bottom:32px;">
          <div style="font-size:48px;margin-bottom:12px;">🚔</div>
          <h1 style="color:#7c83f7;font-size:24px;margin-bottom:4px;">MSRP Dashboard</h1>
          <p style="color:#64748b;font-size:14px;">Maryland State Roleplay</p>
        </div>
        {% if error %}<div class="alert alert-error">{{ error }}</div>{% endif %}
        <form method="POST">
          <div class="form-group">
            <label>Password</label>
            <input type="password" name="password" placeholder="Enter your dashboard password" autofocus>
          </div>
          <button type="submit" class="btn btn-primary" style="width:100%;padding:12px;">Login</button>
        </form>
      </div>
    </div>"""
    return render_template_string(html, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/")
@login_required
def index():
    try:
        logs = supabase.table("audit_logs").select("*").order("timestamp", desc=True).execute().data or []
        configs = supabase.table("guild_configs").select("*").execute().data or []
        total_logs = len(logs)
        total_guilds = len(configs)
        recent = logs[:10]
    except:
        logs, configs, recent = [], [], []
        total_logs, total_guilds = 0, 0

    rows = ""
    for log in recent:
        action = log.get("action", "N/A").capitalize()
        badge = "badge-green" if action.lower() == "promote" else "badge-red" if action.lower() == "infraction" else "badge-orange" if action.lower() == "void" else "badge-purple" if "session" in action.lower() else "badge-blue"
        voided = " <span class='badge badge-orange'>VOIDED</span>" if log.get("is_voided") else ""
        try:
            ts = datetime.fromisoformat(log["timestamp"]).strftime("%b %d %H:%M")
        except:
            ts = "N/A"
        rows += f"""<tr>
          <td><span class='badge {badge}'>{action}</span>{voided}</td>
          <td>{log.get('target_user','N/A')}</td>
          <td>{log.get('performed_by','N/A')}</td>
          <td style="color:#64748b;">{log.get('reason','N/A')[:40]}</td>
          <td style="color:#64748b;">{ts}</td>
        </tr>"""

    html = BASE_STYLE + NAVBAR + f"""
    <div class="container">
      <div class="page-title">Dashboard</div>
      <div class="page-subtitle">Welcome to the Maryland State Roleplay Bot Dashboard</div>
      <div class="stat-grid">
        <div class="stat"><div class="value">{total_logs}</div><div class="label">Total Actions Logged</div></div>
        <div class="stat"><div class="value">{total_guilds}</div><div class="label">Servers Configured</div></div>
        <div class="stat"><div class="value">{len([l for l in logs if l.get('action') == 'promote'])}</div><div class="label">Total Promotions</div></div>
        <div class="stat"><div class="value">{len([l for l in logs if l.get('action') == 'infraction'])}</div><div class="label">Total Infractions</div></div>
      </div>
      <div class="card">
        <h2>Recent Activity</h2>
        <table>
          <thead><tr><th>Action</th><th>Target</th><th>By</th><th>Reason</th><th>Time</th></tr></thead>
          <tbody>{rows or '<tr><td colspan="5" style="text-align:center;color:#64748b;padding:24px;">No logs yet</td></tr>'}</tbody>
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
        badge = "badge-green" if action.lower() == "promote" else "badge-red" if action.lower() == "infraction" else "badge-orange" if action.lower() == "void" else "badge-purple" if "session" in action.lower() else "badge-blue"
        voided = " <span class='badge badge-orange'>VOIDED</span>" if log.get("is_voided") else ""
        try:
            ts = datetime.fromisoformat(log["timestamp"]).strftime("%b %d, %Y %H:%M")
        except:
            ts = "N/A"
        rows += f"""<tr>
          <td style="color:#64748b;">{log.get('id','N/A')}</td>
          <td><span class='badge {badge}'>{action}</span>{voided}</td>
          <td>{log.get('target_user','N/A')}</td>
          <td>{log.get('role_name') or '—'}</td>
          <td>{log.get('performed_by','N/A')}</td>
          <td>{log.get('reason','N/A')}</td>
          <td style="color:#64748b;">{log.get('notes') or '—'}</td>
          <td style="color:#64748b;">{ts}</td>
        </tr>"""

    html = BASE_STYLE + NAVBAR + f"""
    <div class="container">
      <div class="page-title">Audit Logs</div>
      <div class="page-subtitle">All bot actions logged here</div>
      <div class="card">
        <table>
          <thead><tr><th>ID</th><th>Action</th><th>Target</th><th>Role</th><th>By</th><th>Reason</th><th>Notes</th><th>Time</th></tr></thead>
          <tbody>{rows or '<tr><td colspan="8" style="text-align:center;color:#64748b;padding:24px;">No logs yet</td></tr>'}</tbody>
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
        else:
            error = f"API error: {r.status_code}"
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
                killlogs = r.json()[:15]
        except: pass
        try:
            r = requests.get(f"{ERLC_BASE_URL}/server/modcalls", headers=erlc_headers(), timeout=10)
            if r.status_code == 200:
                modcalls = r.json()
        except: pass

    player_rows = "".join(f"<tr><td>{p.get('Player','?')}</td><td><span class='badge badge-blue'>{p.get('Team','?')}</span></td></tr>" for p in players) or "<tr><td colspan='2' style='text-align:center;color:#64748b;padding:16px;'>No players online</td></tr>"
    kill_rows = "".join(f"<tr><td>{k.get('Killer','?')}</td><td style='color:#f87171;'>{k.get('Killed','?')}</td><td style='color:#64748b;'>{k.get('Kill','?')}</td></tr>" for k in killlogs) or "<tr><td colspan='3' style='text-align:center;color:#64748b;padding:16px;'>No kill logs</td></tr>"
    mod_rows = "".join(f"<tr><td>{m.get('Caller','?')}</td><td style='color:#64748b;'>{m.get('Reason','?')}</td></tr>" for m in modcalls) or "<tr><td colspan='2' style='text-align:center;color:#64748b;padding:16px;'>No mod calls</td></tr>"

    status_section = f"""
    <div class="stat-grid">
      <div class="stat"><div class="value">{server_data.get('CurrentPlayers', 0)}</div><div class="label">Players Online</div></div>
      <div class="stat"><div class="value">{server_data.get('MaxPlayers', 0)}</div><div class="label">Max Players</div></div>
      <div class="stat"><div class="value">{server_data.get('Queue', 0)}</div><div class="label">In Queue</div></div>
      <div class="stat"><div class="value">{server_data.get('JoinKey', 'N/A')}</div><div class="label">Join Key</div></div>
    </div>""" if server_data else ""

    html = BASE_STYLE + NAVBAR + f"""
    <div class="container">
      <div class="page-title">ER:LC Live</div>
      <div class="page-subtitle">Live data from your ER:LC private server</div>
      {'<div class="alert alert-error">'+error+'</div>' if error else ''}
      {status_section}
      <div class="grid-2">
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
        guild_id = request.form.get("guild_id", "").strip()

        if action == "general" and guild_id:
            try:
                config = {
                    "staff_role_id": request.form.get("staff_role_id", "").strip(),
                    "admin_role_id": request.form.get("admin_role_id", "").strip(),
                    "hr_role_id": request.form.get("hr_role_id", "").strip(),
                    "mute_role_id": request.form.get("mute_role_id", "").strip(),
                    "log_channel_id": request.form.get("log_channel_id", "").strip(),
                    "welcome_channel_id": request.form.get("welcome_channel_id", "").strip(),
                }
                config = {k: v for k, v in config.items() if v}
                existing = supabase.table("guild_configs").select("guild_id").eq("guild_id", guild_id).execute()
                if existing.data:
                    supabase.table("guild_configs").update(config).eq("guild_id", guild_id).execute()
                else:
                    supabase.table("guild_configs").insert({"guild_id": guild_id, **config}).execute()
                message = "General settings saved!"
            except Exception as e:
                error = str(e)

        elif action == "promote_config" and guild_id:
            try:
                config = {
                    "promote_channel_id": request.form.get("promote_channel_id", "").strip(),
                    "promote_role_ids": request.form.get("promote_role_ids", "").strip(),
                }
                config = {k: v for k, v in config.items() if v}
                existing = supabase.table("guild_configs").select("guild_id").eq("guild_id", guild_id).execute()
                if existing.data:
                    supabase.table("guild_configs").update(config).eq("guild_id", guild_id).execute()
                else:
                    supabase.table("guild_configs").insert({"guild_id": guild_id, **config}).execute()
                message = "Promote settings saved!"
            except Exception as e:
                error = str(e)

        elif action == "infraction_config" and guild_id:
            try:
                config = {
                    "infraction_channel_id": request.form.get("infraction_channel_id", "").strip(),
                    "infraction_role_ids": request.form.get("infraction_role_ids", "").strip(),
                    "void_channel_id": request.form.get("void_channel_id", "").strip(),
                    "void_role_ids": request.form.get("void_role_ids", "").strip(),
                }
                config = {k: v for k, v in config.items() if v}
                existing = supabase.table("guild_configs").select("guild_id").eq("guild_id", guild_id).execute()
                if existing.data:
                    supabase.table("guild_configs").update(config).eq("guild_id", guild_id).execute()
                else:
                    supabase.table("guild_configs").insert({"guild_id": guild_id, **config}).execute()
                message = "Infraction settings saved!"
            except Exception as e:
                error = str(e)

        elif action == "erlc_config" and guild_id:
            try:
                config = {
                    "session_channel_id": request.form.get("session_channel_id", "").strip(),
                    "session_ping_message": request.form.get("session_ping_message", "").strip(),
                    "killlog_channel_id": request.form.get("killlog_channel_id", "").strip(),
                    "modcall_channel_id": request.form.get("modcall_channel_id", "").strip(),
                }
                min_players = request.form.get("min_players_ping", "0").strip()
                if min_players.isdigit():
                    config["min_players_ping"] = int(min_players)
                config = {k: v for k, v in config.items() if v != "" and v is not None}
                existing = supabase.table("guild_configs").select("guild_id").eq("guild_id", guild_id).execute()
                if existing.data:
                    supabase.table("guild_configs").update(config).eq("guild_id", guild_id).execute()
                else:
                    supabase.table("guild_configs").insert({"guild_id": guild_id, **config}).execute()
                message = "ER:LC settings saved!"
            except Exception as e:
                error = str(e)

        elif action == "password":
            new_pass = request.form.get("new_password", "").strip()
            if new_pass:
                global DASHBOARD_PASSWORD
                DASHBOARD_PASSWORD = new_pass
                message = "Password updated for this session! Add DASHBOARD_PASSWORD to Railway Variables to make it permanent."

    try:
        configs = supabase.table("guild_configs").select("*").execute().data or []
        current = configs[0] if configs else {}
        guild_id_val = current.get("guild_id", "")
    except:
        configs, current, guild_id_val = [], {}, ""

    msg_html = f"<div class='alert alert-success'>{message}</div>" if message else ""
    err_html = f"<div class='alert alert-error'>{error}</div>" if error else ""

    html = BASE_STYLE + NAVBAR + f"""
    <div class="container">
      <div class="page-title">Settings</div>
      <div class="page-subtitle">Configure your bot for your Discord server</div>
      {msg_html}{err_html}

      <!-- GENERAL SETTINGS -->
      <div class="card">
        <h2>⚙️ General Settings</h2>
        <form method="POST">
          <input type="hidden" name="action" value="general">
          <div class="form-group">
            <label>Guild ID (Your Discord Server ID)</label>
            <input name="guild_id" placeholder="e.g. 123456789012345678" value="{guild_id_val}">
            <div class="form-hint">Right click your server icon → Copy Server ID</div>
          </div>
          <hr class="section-divider">
          <h3>Roles</h3>
          <div class="grid-3">
            <div class="form-group">
              <label>Staff Role ID</label>
              <input name="staff_role_id" placeholder="Role ID" value="{current.get('staff_role_id','') or ''}">
            </div>
            <div class="form-group">
              <label>Admin Role ID</label>
              <input name="admin_role_id" placeholder="Role ID" value="{current.get('admin_role_id','') or ''}">
            </div>
            <div class="form-group">
              <label>HR Role ID</label>
              <input name="hr_role_id" placeholder="Role ID" value="{current.get('hr_role_id','') or ''}">
            </div>
            <div class="form-group">
              <label>Mute Role ID</label>
              <input name="mute_role_id" placeholder="Role ID" value="{current.get('mute_role_id','') or ''}">
            </div>
          </div>
          <hr class="section-divider">
          <h3>Channels</h3>
          <div class="grid-3">
            <div class="form-group">
              <label>General Log Channel ID</label>
              <input name="log_channel_id" placeholder="Channel ID" value="{current.get('log_channel_id','') or ''}">
            </div>
            <div class="form-group">
              <label>Welcome Channel ID</label>
              <input name="welcome_channel_id" placeholder="Channel ID" value="{current.get('welcome_channel_id','') or ''}">
            </div>
          </div>
          <button type="submit" class="btn btn-primary">Save General Settings</button>
        </form>
      </div>

      <!-- PROMOTE SETTINGS -->
      <div class="card">
        <h2>🟢 Promote Command Settings</h2>
        <form method="POST">
          <input type="hidden" name="action" value="promote_config">
          <div class="form-group">
            <label>Guild ID</label>
            <input name="guild_id" placeholder="Your Discord Server ID" value="{guild_id_val}">
          </div>
          <div class="grid-2">
            <div class="form-group">
              <label>Promote Log Channel ID</label>
              <input name="promote_channel_id" placeholder="Channel ID" value="{current.get('promote_channel_id','') or ''}">
              <div class="form-hint">Where promotion logs get sent</div>
            </div>
            <div class="form-group">
              <label>Allowed Role IDs (comma separated)</label>
              <input name="promote_role_ids" placeholder="e.g. 123456,789012" value="{current.get('promote_role_ids','') or ''}">
              <div class="form-hint">Roles that can use /promote (besides HR & Admin)</div>
            </div>
          </div>
          <button type="submit" class="btn btn-primary">Save Promote Settings</button>
        </form>
      </div>

      <!-- INFRACTION SETTINGS -->
      <div class="card">
        <h2>🔴 Infraction Command Settings</h2>
        <form method="POST">
          <input type="hidden" name="action" value="infraction_config">
          <div class="form-group">
            <label>Guild ID</label>
            <input name="guild_id" placeholder="Your Discord Server ID" value="{guild_id_val}">
          </div>
          <div class="grid-2">
            <div class="form-group">
              <label>Infraction Log Channel ID</label>
              <input name="infraction_channel_id" placeholder="Channel ID" value="{current.get('infraction_channel_id','') or ''}">
              <div class="form-hint">Where infraction logs get sent</div>
            </div>
            <div class="form-group">
              <label>Allowed Role IDs for Infractions (comma separated)</label>
              <input name="infraction_role_ids" placeholder="e.g. 123456,789012" value="{current.get('infraction_role_ids','') or ''}">
              <div class="form-hint">Roles that can use /infraction_issue</div>
            </div>
            <div class="form-group">
              <label>Void Log Channel ID</label>
              <input name="void_channel_id" placeholder="Channel ID" value="{current.get('void_channel_id','') or ''}">
              <div class="form-hint">Where void infraction logs get sent</div>
            </div>
            <div class="form-group">
              <label>Allowed Role IDs for Voiding (comma separated)</label>
              <input name="void_role_ids" placeholder="e.g. 123456,789012" value="{current.get('void_role_ids','') or ''}">
              <div class="form-hint">Roles that can use /void_infraction</div>
            </div>
          </div>
          <button type="submit" class="btn btn-primary">Save Infraction Settings</button>
        </form>
      </div>

      <!-- ERLC SETTINGS -->
      <div class="card">
        <h2>🚔 ER:LC Settings</h2>
        <form method="POST">
          <input type="hidden" name="action" value="erlc_config">
          <div class="form-group">
            <label>Guild ID</label>
            <input name="guild_id" placeholder="Your Discord Server ID" value="{guild_id_val}">
          </div>
          <div class="grid-2">
            <div class="form-group">
              <label>Session Ping Channel ID</label>
              <input name="session_channel_id" placeholder="Channel ID" value="{current.get('session_channel_id','') or ''}">
              <div class="form-hint">Where session start/end pings are sent</div>
            </div>
            <div class="form-group">
              <label>Custom Session Ping Message</label>
              <input name="session_ping_message" placeholder="A new session is starting! Join now!" value="{current.get('session_ping_message','') or ''}">
            </div>
            <div class="form-group">
              <label>Kill Log Channel ID</label>
              <input name="killlog_channel_id" placeholder="Channel ID" value="{current.get('killlog_channel_id','') or ''}">
              <div class="form-hint">Auto-posts kill logs here</div>
            </div>
            <div class="form-group">
              <label>Mod Call Channel ID</label>
              <input name="modcall_channel_id" placeholder="Channel ID" value="{current.get('modcall_channel_id','') or ''}">
              <div class="form-hint">Auto-posts mod calls here</div>
            </div>
            <div class="form-group">
              <label>Minimum Players to Ping</label>
              <input name="min_players_ping" type="number" placeholder="0" value="{current.get('min_players_ping', 0) or 0}">
              <div class="form-hint">Only ping session channel when this many players are online</div>
            </div>
          </div>
          <button type="submit" class="btn btn-primary">Save ER:LC Settings</button>
        </form>
      </div>

      <!-- PASSWORD -->
      <div class="card">
        <h2>🔒 Dashboard Password</h2>
        <form method="POST">
          <input type="hidden" name="action" value="password">
          <div class="form-group" style="max-width:400px;">
            <label>New Password</label>
            <input type="password" name="new_password" placeholder="Enter new password">
            <div class="form-hint">Also update DASHBOARD_PASSWORD in Railway Variables to make it permanent</div>
          </div>
          <button type="submit" class="btn btn-primary">Update Password</button>
        </form>
      </div>
    </div>"""
    return render_template_string(html)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
