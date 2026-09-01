#!/usr/bin/env python3
import time
from flask import Flask, render_template_string, request, session
from rti_client import RTIClient, RTIError
import auto_chooser

app = Flask(__name__)
app.secret_key = "change-me-rti-sync"

BASE_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RTI Schedule</title>
  <style>
    :root { --bg:#0f172a; --card:#1e293b; --muted:#94a3b8; --accent:#38bdf8; --border:#334155; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: system-ui, -apple-system, sans-serif; background:var(--bg); color:#e2e8f0; }
    .wrap { max-width:720px; margin:0 auto; padding:24px 16px 60px; }
    h1 { font-size:1.4rem; margin:0 0 4px; }
    .sub { color:var(--muted); margin:0 0 24px; }
    .week-heading { font-size:.8rem; letter-spacing:.12em; text-transform:uppercase; font-weight:700; color:var(--accent); margin:26px 0 10px; display:flex; align-items:center; gap:10px; }
    .week-heading::after { content:""; flex:1; height:1px; background:var(--border); }
    .card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:18px 20px; margin-bottom:16px; }
    .day-header { font-weight:600; font-size:1.05rem; display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; }
    .day-sub { color:var(--muted); font-size:.85rem; margin-top:4px; }
    .badge { font-size:.7rem; padding:2px 8px; border-radius:999px; background:#334155; color:#cbd5e1; align-self:center; }
    .badge.chosen { background:#14532d; color:#86efac; }
    .badge.needed { background:#7f1d1d; color:#fca5a5; }
    .sessions { margin-top:12px; border-top:1px solid var(--border); padding-top:10px; }
    .sess { display:flex; gap:10px; padding:10px 0; border-bottom:1px solid var(--border); align-items:center; }
    .sess:last-child { border-bottom:none; }
    .sess .name { font-size:.95rem; }
    .sess .meta { color:var(--muted); font-size:.8rem; }
    .sess .room { margin-left:auto; font-weight:600; color:var(--accent); }
    .empty { color:var(--muted); font-style:italic; }
    .card.disabled { opacity:.45; }
    .card.disabled .day-header, .card.disabled .day-sub, .card.disabled .sess { filter:grayscale(1); }
    form { display:flex; flex-direction:column; gap:14px; }
    label { font-size:.85rem; color:var(--muted); }
    input { padding:12px 14px; border-radius:8px; border:1px solid var(--border); background:#0f172a; color:#e2e8f0; font-size:1rem; }
    button { padding:12px; border:none; border-radius:8px; background:var(--accent); color:#0f172a; font-weight:700; font-size:1rem; cursor:pointer; }
    button:disabled { opacity:.5; cursor:not-allowed; }
    .choose-btn { margin-top:12px; padding:9px 14px; font-size:.85rem; font-weight:600; width:100%; }
    button.ghost { background:transparent; color:var(--accent); border:1px solid var(--accent); }
    .pick { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:10px; }
    .pick li { border:1px solid var(--border); border-radius:10px; padding:12px 14px; display:flex; gap:12px; align-items:center; background:#0f172a; cursor:pointer; }
    .pick input { width:auto; }
    .pick .cap { color:var(--muted); font-size:.78rem; }
    .pick label { flex:1; cursor:pointer; }
    .rule { display:flex; gap:8px; margin-bottom:8px; align-items:center; }
    .rule select { padding:10px; border-radius:8px; border:1px solid var(--border); background:#0f172a; color:#e2e8f0; font-size:.9rem; flex:1; }
    .rule input { flex:1.4; padding:10px; }
    .rule button { padding:10px; width:auto; }
    .error { background:#7f1d1d; border:1px solid #b91c1c; color:#fecaca; padding:12px 16px; border-radius:8px; margin-bottom:16px; }
    .links { margin-top:20px; font-size:.85rem; }
    .links a { color:var(--accent); }
    @media (max-width:600px) {
      .day-header { flex-direction:column; gap:6px; }
      .badge { align-self:flex-start; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    {{ content | safe }}
  </div>
</body>
</html>
"""

LOGIN_PAGE = """
<h1>RTI Schedule</h1>
<p class="sub">Sign in with your school (ClassLink) credentials to view your schedule.</p>
{% if error %}<div class="error">{{ error }}</div>{% endif %}
<form method="post">
  <div>
    <label for="email">Email</label>
    <input type="text" id="email" name="email" value="{{ email }}" required autofocus>
  </div>
  <div>
    <label for="password">Password</label>
    <input type="password" id="password" name="password" required>
  </div>
  <button type="submit" id="submit">Load my schedule</button>
</form>
"""

SCHEDULE_PAGE = """
<h1>My Schedule</h1>
<p class="sub">{{ student.get('firstName') }} {{ student.get('lastName') }} &middot; {{ school.get('name') }}</p>
{% if message %}<div class="error" style="background:#14532d;border-color:#166534;color:#86efac;">{{ message }}</div>{% endif %}
{% if error %}<div class="error">{{ error }}</div>{% endif %}
{% if not days %}
  <div class="card"><div class="empty">No upcoming schedules found.</div></div>
{% endif %}
{% set ns = namespace(current='') %}
{% for day in days %}
  {% if day.week_label != ns.current %}
    {% set ns.current = day.week_label %}
    <div class="week-heading">{{ day.week_label }}</div>
  {% endif %}
  <div class="card{% if not day.selectable %} disabled{% endif %}">
    <div class="day-header">
      <span>{{ day.name }}</span>
      {% if not day.selectable %}
        <span class="badge">{{ day.status }}</span>
      {% elif day.sessions %}
        <span class="badge chosen">Session Chosen</span>
      {% else %}
        <span class="badge needed">Choose Session</span>
      {% endif %}
    </div>
    <div class="sessions">
      {% if not day.sessions %}<span class="empty">No sessions scheduled for you.</span>{% endif %}
      {% for s in day.sessions %}
        <div class="sess">
          <div>
            <div class="name">{{ s.name }}</div>
            <div class="meta">{% if s.teacher %}{{ s.teacher }}{% endif %}</div>
          </div>
          <span class="room">{% if s.room %}{{ s.room }}{% endif %}</span>
        </div>
      {% endfor %}
      {% if day.selectable %}
        <form method="post" action="{{ url_for('choose_session', day_id=day.schedule_id) }}">
          <input type="hidden" name="name" value="{{ day.name }}">
          {% if day.sessions %}<input type="hidden" name="changing" value="1">{% endif %}
          <button type="submit" class="choose-btn">{{ 'Change Session' if day.sessions else 'Choose Session' }}</button>
        </form>
      {% endif %}
    </div>
  </div>
{% endfor %}
<p class="links"><a href="{{ url_for('settings_page') }}">Auto-Session Chooser</a> &middot; <a href="{{ url_for('logout') }}">Sign out</a></p>
"""

CHOOSE_PAGE = """
<h1>{{ day_name }}</h1>
<p class="sub">Pick the session you want for this day. {% if current_name %}Currently: {{ current_name }}.{% endif %}</p>
{% if not sessions %}
  <div class="card"><div class="empty">No open sessions are available to choose for this day.</div></div>
  <p class="links"><a href="{{ url_for('schedule_page') }}">&larr; Back to schedule</a></p>
{% else %}
  <form method="post" action="{{ url_for('enroll', day_id=day_id) }}">
    <ul class="pick">
      {% for s in sessions %}
        <li>
          <input type="radio" name="session_id" id="s{{ s.id }}" value="{{ s.id }}" {% if s.id == current %}checked{% endif %} required>
          <label for="s{{ s.id }}">
            <div>{{ s.name }}</div>
            <div class="cap">{{ s.room }}{% if s.instructor %} &middot; {{ s.instructor }}{% endif %}</div>
            <div class="cap">{{ s.enrolled }} / {{ s.capacity }} enrolled</div>
          </label>
        </li>
      {% endfor %}
    </ul>
    <div style="display:flex; gap:10px;">
      <button type="submit" class="ghost">Confirm</button>
      <a href="{{ url_for('schedule_page') }}" style="flex:1; text-align:center; padding:12px; color:var(--muted); text-decoration:none; border:1px solid var(--border); border-radius:8px;">Cancel</a>
    </div>
  </form>
{% endif %}
"""

SETTINGS_PAGE = """
<h1>Auto-Session Chooser</h1>
<p class="sub">Automatically picks your session for any upcoming day you haven't set yet, using a priority keyword list. Runs every 12 hours when enabled.</p>
{% if message %}<div class="error" style="background:#14532d;border-color:#166534;color:#86efac;">{{ message }}</div>{% endif %}
{% if error %}<div class="error">{{ error }}</div>{% endif %}
<form method="post" action="{{ url_for('save_settings') }}">
  <div style="display:flex; align-items:center; gap:10px; margin-bottom:18px;">
    <label for="enabled" style="flex:1;">Enabled</label>
    <input type="checkbox" id="enabled" name="enabled" {% if enabled %}checked{% endif %} style="width:auto;">
  </div>

  <div class="week-heading">Priority List (first match wins)</div>
  {% if rule_errors %}<div class="error">{{ rule_errors }}</div>{% endif %}
  <div id="rules">
    {% for r in rules %}
      <div class="rule">
        <select name="category[]">
          {% for c in categories %}
            <option value="{{ c[0] }}" {% if r.category == c[0] %}selected{% endif %}>{{ c[1] }}</option>
          {% endfor %}
        </select>
        <input type="text" name="keyword[]" value="{{ r.keyword }}" placeholder="keyword">
        <button type="button" class="ghost remove-rule" style="width:auto;">Remove</button>
      </div>
    {% endfor %}
  </div>
  <button type="button" class="ghost add-rule" style="width:auto; margin-bottom:16px;">+ Add another keyword</button>

  <button type="submit">Save settings</button>
</form>

<div style="margin-top:14px; display:flex; gap:10px;">
  <form method="post" action="{{ url_for('run_now') }}">
    <button type="submit" class="ghost" style="width:auto;">Run check now</button>
  </form>
  <a href="{{ url_for('schedule_page') }}" style="flex:1; padding:12px; color:var(--muted); text-decoration:none; border:1px solid var(--border); border-radius:8px; text-align:center;">Back to schedule</a>
</div>

{% if last_run %}
<p class="sub" style="margin-top:18px;">Last auto-run: {{ last_run }}</p>
{% endif %}
<script>
  var catOptions = {{ cat_options | safe }};
  function ruleRow(category, keyword) {
    var div = document.createElement('div');
    div.className = 'rule';
    var sel = '<select name="category[]">';
    catOptions.forEach(function(c){ sel += '<option value="'+c[0]+'"'+(c[0]===category?' selected':'')+'>'+c[1]+'</option>'; });
    sel += '</select>';
    div.innerHTML = sel + '<input type="text" name="keyword[]" value="'+ (keyword||'') +'" placeholder="keyword"><button type="button" class="ghost remove-rule" style="width:auto;">Remove</button>';
    return div;
  }
  document.querySelector('.add-rule').addEventListener('click', function(){
    document.getElementById('rules').appendChild(ruleRow('session',''));
  });
  document.getElementById('rules').addEventListener('click', function(e){
    if (e.target.classList.contains('remove-rule')) { e.target.closest('.rule').remove(); }
  });
</script>
"""


def fmt_time(iso):
    if not iso:
        return ""
    if len(iso) <= 10:
        return ""
    try:
        return time.strftime("%I:%M %p", time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return iso


def load_schedule(email, password):
    client = RTIClient(email, password)
    client.login()
    return client.get_schedule()


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        try:
            schedule = load_schedule(email, password)
            session["email"] = email
            session["password"] = password
            # Persist credentials for this user so the background auto-chooser
            # can log in on their behalf.
            cfg = auto_chooser.get_config(email)
            cfg["email"] = email
            cfg["password"] = password
            auto_chooser.set_config(email, cfg)
        except (RTIError, Exception) as e:
            return render_template_string(
                BASE_HTML,
                content=render_template_string(LOGIN_PAGE, error=str(e), email=email),
            )
        return render_schedule(schedule)

    error = session.pop("_error", None)
    return render_template_string(BASE_HTML, content=render_template_string(LOGIN_PAGE, error=error, email=session.get("email", "")))


def render_schedule(schedule, message=None, error=None):
    days = []
    for d in schedule["days"]:
        days.append({
            "name": d["name"],
            "status": d["status"],
            "selectable": d.get("selectable", True),
            "schedule_id": d.get("schedule_id"),
            "week_label": d.get("week_label", ""),
            "start_time": fmt_time(d["start"]),
            "end_time": fmt_time(d["end"]),
            "sessions": [
                {
                    "name": s["name"],
                    "type": s["type"],
                    "teacher": (f"{s['instructor'].get('firstName', '')} {s['instructor'].get('lastName', '')}").strip(),
                    "room": s["room"],
                }
                for s in d["sessions"]
            ],
        })
    page = render_template_string(
        SCHEDULE_PAGE,
        student=schedule["student"],
        school=schedule["school"],
        days=days,
        message=message,
        error=error,
    )
    return render_template_string(BASE_HTML, content=page)


@app.route("/schedule")
def schedule_page():
    if "email" not in session:
        return index()
    message = session.pop("_message", None)
    error = session.pop("_error", None)
    try:
        schedule = load_schedule(session["email"], session["password"])
    except Exception as e:
        session.pop("email", None)
        session.pop("password", None)
        return render_template_string(BASE_HTML, content=render_template_string(LOGIN_PAGE, error=str(e), email=""))
    return render_schedule(schedule, message=message, error=error)


@app.route("/choose/<int:day_id>", methods=["POST"])
def choose_session(day_id):
    if "email" not in session:
        return index()
    client = RTIClient(session["email"], session["password"])
    try:
        client.login()
        info = client.list_open_sessions(day_id, choosing_another=bool(request.form.get("changing")))
    except RTIError as e:
        session["_error"] = str(e)
        return schedule_page()
    return render_template_string(
        BASE_HTML,
        content=render_template_string(
            CHOOSE_PAGE,
            day_name=request.form.get("name", ""),
            day_id=day_id,
            sessions=info["sessions"],
            current=info["current"],
            current_name=info["current_name"],
        ),
    )


@app.route("/enroll/<int:day_id>", methods=["POST"])
def enroll(day_id):
    if "email" not in session:
        return index()
    session_id = request.form.get("session_id")
    if not session_id:
        session["_error"] = "Please choose a session."
        return schedule_page()
    client = RTIClient(session["email"], session["password"])
    try:
        client.login()
        client.enroll(day_id, session_id)
        session["_message"] = "Done."
    except RTIError as e:
        session["_error"] = str(e)
    return schedule_page()


@app.route("/logout")
def logout():
    session.clear()
    return index()


CATEGORIES = [
    ("session", "Session name"),
    ("teacher", "Teacher name"),
    ("room", "Room #/name"),
]


def _cat_options_json():
    import json
    return json.dumps(CATEGORIES)


def render_settings(email, message=None, error=None, rule_errors=None):
    cfg = auto_chooser.get_config(email)
    rules = cfg.get("rules") or []
    return render_template_string(
        BASE_HTML,
        content=render_template_string(
            SETTINGS_PAGE,
            enabled=bool(cfg.get("enabled")),
            rules=rules,
            categories=CATEGORIES,
            cat_options=_cat_options_json(),
            message=message,
            error=error,
            rule_errors=rule_errors,
            last_run=cfg.get("last_run"),
        ),
    )


@app.route("/settings")
def settings_page():
    if "email" not in session:
        return index()
    return render_settings(session["email"])


@app.route("/settings", methods=["POST"])
def save_settings():
    if "email" not in session:
        return index()
    email = session["email"]
    cfg = auto_chooser.get_config(email)
    cfg["enabled"] = "enabled" in request.form

    categories = request.form.getlist("category[]")
    keywords = request.form.getlist("keyword[]")
    rules = []
    rule_errors = None
    for cat, kw in zip(categories, keywords):
        kw = kw.strip()
        if not kw:
            continue
        if cat not in [c[0] for c in CATEGORIES]:
            rule_errors = "One of the categories is invalid."
            break
        rules.append({"category": cat, "keyword": kw})
    if not rule_errors:
        cfg["rules"] = rules
        auto_chooser.set_config(email, cfg)
        return render_settings(email, message="Settings saved.")
    return render_settings(email, rule_errors=rule_errors)


@app.route("/run-now", methods=["POST"])
def run_now():
    if "email" not in session:
        return index()
    email = session["email"]
    cfg = auto_chooser.get_config(email)
    if not (cfg.get("email") and cfg.get("password")):
        return render_settings(email, error="No saved credentials. Sign in first.")
    report = auto_chooser.run_once(email, cfg.get("password"), cfg.get("rules") or [])
    cfg["last_run"] = time.time()
    auto_chooser.set_config(email, cfg)
    lines = []
    if report["enrolled"]:
        lines.append("<b>Chosen/enrolled:</b><ul>" + "".join(f"<li>{x}</li>" for x in report["enrolled"]) + "</ul>")
    if report["errors"]:
        lines.append("<b>Errors:</b><ul>" + "".join(f"<li>{x}</li>" for x in report["errors"]) + "</ul>")
    body = "".join(lines) or "<p>No changes needed.</p>"
    return render_template_string(
        BASE_HTML,
        content=render_template_string(
            SETTINGS_PAGE + "{{ report | safe }}",
            enabled=bool(cfg.get("enabled")),
            rules=cfg.get("rules") or [],
            categories=CATEGORIES,
            cat_options=_cat_options_json(),
            message=None,
            error=None,
            rule_errors=None,
            last_run=cfg.get("last_run"),
            report=body,
        ),
    )


if __name__ == "__main__":
    auto_chooser.start_scheduler()
    app.run(host="127.0.0.1", port=5000, debug=False)
