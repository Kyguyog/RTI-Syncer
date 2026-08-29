#!/usr/bin/env python3
"""Automatic session chooser.

Loads saved credentials + priority rules from a config file, periodically logs
into RTI Scheduler, and for every upcoming day that has no session chosen yet,
picks a session based on the priority keyword list and enrolls in it.
"""
import json
import os
import threading
import time

from rti_client import RTIClient, RTIError

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rti_config.json")

CHECK_INTERVAL_SECONDS = 12 * 60 * 60  # every 12 hours
BOOTSTRAP_DELAY_SECONDS = 45  # run a first check shortly after start


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def _target_text(session, category):
    """Return the text to match against for a category, or None if unknown."""
    category = (category or "session").lower()
    if category in ("session", "session name", "name"):
        return session.get("name") or ""
    if category in ("teacher", "instructor", "teacher name"):
        return (session.get("instructor") or "").lower()
    if category in ("room", "room #", "room number"):
        return session.get("room") or ""
    return session.get("name") or ""


def rule_matches(rule, session):
    """True if an open-session dict matches a priority rule."""
    if not rule or not rule.get("keyword"):
        return False
    target = _target_text(session, rule.get("category")).lower()
    keyword = str(rule.get("keyword", "")).lower()
    return keyword in target


def choose_for_day(open_sessions, rules):
    """Return the open-session dict picked for a day by the priority rules,
    or None if nothing matches. Rules are evaluated in order; the first rule
    that matches any open session wins."""
    for rule in rules or []:
        for s in open_sessions or []:
            if rule_matches(rule, s):
                return s
    return None


def run_once(email, password, rules):
    """Log in and fill every unset upcoming session using the rules.
    Returns a dict report {log: [...], enrolled: [...], errors: [...]}."""
    report = {"log": [], "enrolled": [], "errors": []}
    client = RTIClient(email, password)
    try:
        client.login()
    except RTIError as e:
        report["errors"].append(f"Login failed: {e}")
        return report

    schedule = client.get_schedule()
    report["log"].append("Checked schedule for upcoming days.")

    for day in schedule["days"]:
        if not day.get("selectable") or day.get("past"):
            continue  # not enrollable or already in the past
        schedule_id = day.get("schedule_id")
        if not schedule_id:
            continue
        if day.get("sessions"):
            report["log"].append(f"{day['name']}: already has a session; skipped.")
            continue
        try:
            info = client.list_open_sessions(schedule_id)
        except RTIError as e:
            report["errors"].append(f"{day['name']}: could not load sessions - {e}")
            continue
        if not info["sessions"]:
            report["log"].append(f"{day['name']}: no open sessions available.")
            continue
        pick = choose_for_day(info["sessions"], rules)
        if not pick:
            report["log"].append(f"{day['name']}: no session matched the priority list; none chosen.")
            continue
        try:
            client.enroll(schedule_id, pick["id"])
            report["enrolled"].append(
                f"{day['name']}: enrolled in '{pick['name']}' ({pick['room']} / {pick['instructor']})"
            )
        except RTIError as e:
            report["errors"].append(f"{day['name']}: enrolling '{pick['name']}' failed - {e}")

    report["log"].extend(report["errors"])
    return report


def background_loop(stop_event):
    """Run on a background thread. First check shortly after start, then
    periodically while enabled, using the saved config."""
    time.sleep(BOOTSTRAP_DELAY_SECONDS)
    last_run = 0.0
    while not stop_event.is_set():
        cfg = load_config()
        if cfg.get("enabled") and cfg.get("email") and cfg.get("password"):
            if time.time() - last_run >= CHECK_INTERVAL_SECONDS:
                try:
                    run_once(cfg["email"], cfg["password"], cfg.get("rules") or [])
                except Exception:
                    pass
                last_run = time.time()
                cfg["last_run"] = time.time()
                try:
                    save_config(cfg)
                except Exception:
                    pass
        stop_event.wait(60)


_scheduler_thread = None
_stop_event = None


def start_scheduler():
    global _scheduler_thread, _stop_event
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _stop_event = threading.Event()
    _scheduler_thread = threading.Thread(target=background_loop, args=(_stop_event,), daemon=True)
    _scheduler_thread.start()
