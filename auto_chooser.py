#!/usr/bin/env python3
"""Automatic session chooser (per-user).

Loads each user's saved credentials + priority rules from a config file,
periodically logs into RTI Scheduler for every enabled user, and for every
upcoming day that has no session chosen yet, picks a session based on that
user's priority keyword list and enrolls in it.
"""
import json
import os
import threading
import time
from datetime import datetime, timedelta

from rti_client import RTIClient, RTIError

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rti_config.json")

def _load_store():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
    return {}


def _save_store(store):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(store, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def _key(email):
    return (email or "").strip().lower()


def get_config(email):
    """Return the config dict for a user, or an empty dict if none."""
    store = _load_store()
    return store.get(_key(email), {})


def set_config(email, cfg):
    """Persist a config dict for a user (merges into the store)."""
    store = _load_store()
    store[_key(email)] = cfg
    _save_store(store)


def all_users():
    """Return a dict of email -> config for every stored user."""
    return _load_store()


def _target_text(session, category):
    """Return the text to match against for a category, or empty if unknown."""
    category = (category or "session").lower()
    if category in ("session", "session name", "name"):
        return session.get("name") or ""
    if category in ("teacher", "instructor", "teacher name"):
        return session.get("instructor") or ""
    if category in ("room", "room #", "room number"):
        return session.get("room") or ""
    return session.get("name") or ""


def rule_matches(rule, session):
    """True if an open-session dict matches a priority rule (case-insensitive)."""
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


def next_scheduled_run(now=None):
    """Return the next local noon or midnight after *now*."""
    now = now or datetime.now()
    if now.hour < 12:
        return now.replace(hour=12, minute=0, second=0, microsecond=0)
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def _seconds_until_next_run(now=None):
    now = now or datetime.now()
    return max(0, next_scheduled_run(now).timestamp() - now.timestamp())


def background_loop(stop_event):
    """Run enabled users at local midnight and noon each day."""
    while not stop_event.is_set():
        if stop_event.wait(_seconds_until_next_run()):
            break
        for email, cfg in (all_users() or {}).items():
            if not cfg.get("enabled"):
                continue
            try:
                run_once(email, cfg.get("password"), cfg.get("rules") or [])
                # Read the latest config again so a settings change made
                # during the check is not overwritten by this older copy.
                latest_cfg = get_config(email)
                latest_cfg["last_run"] = time.time()
                set_config(email, latest_cfg)
            except Exception:
                pass


_scheduler_thread = None
_stop_event = None


def start_scheduler():
    global _scheduler_thread, _stop_event
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _stop_event = threading.Event()
    _scheduler_thread = threading.Thread(target=background_loop, args=(_stop_event,), daemon=True)
    _scheduler_thread.start()
