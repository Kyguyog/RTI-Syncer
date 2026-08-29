#!/usr/bin/env python3
import time
from flask import Flask, render_template_string, request, session
from rti_client import RTIClient, RTIError

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
    .error { background:#7f1d1d; border:1px solid #b91c1c; color:#fecaca; padding:12px 16px; border-radius:8px; margin-bottom:16px; }
    .links { margin-top:20px; font-size:.85rem; }
    .links a { color:var(--accent); }
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
    </div>
  </div>
{% endfor %}
<p class="links"><a href="{{ url_for('logout') }}">Sign out</a></p>
"""


def fmt_time(iso):
    if not iso:
        return ""
    # date-only ISO (e.g. placeholder days with no schedule) -> no time
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
        except (RTIError, Exception) as e:
            return render_template_string(
                BASE_HTML,
                content=render_template_string(LOGIN_PAGE, error=str(e), email=email),
            )
        return render_schedule(schedule)

    error = session.pop("_error", None)
    return render_template_string(BASE_HTML, content=render_template_string(LOGIN_PAGE, error=error, email=session.get("email", "")))


def render_schedule(schedule):
    days = []
    for d in schedule["days"]:
        days.append({
            "name": d["name"],
            "status": d["status"],
            "selectable": d.get("selectable", True),
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
    )
    return render_template_string(BASE_HTML, content=page)


@app.route("/schedule")
def schedule_page():
    if "email" not in session:
        return index()
    try:
        schedule = load_schedule(session["email"], session["password"])
    except Exception as e:
        session.pop("email", None)
        session.pop("password", None)
        return render_template_string(BASE_HTML, content=render_template_string(LOGIN_PAGE, error=str(e), email=""))
    return render_schedule(schedule)


@app.route("/logout")
def logout():
    session.clear()
    return index()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
