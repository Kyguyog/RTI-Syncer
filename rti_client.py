#!/usr/bin/env python3
import json
import re
import uuid
import requests


class RTIError(Exception):
    pass


class RTIClient:
    """Authenticates with RTI Scheduler via ClassLink and fetches a student's schedule."""

    DISTRICT = "alpinesd"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "pragma": "no-cache",
    }

    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.s = requests.Session()
        self.s.headers.update(self.HEADERS)

    def login(self):
        s = self.s

        r = s.get(
            "https://www.rtischeduler.com/user/authenticate-classlink",
            params={"continue": ""},
            headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "referer": "https://www.rtischeduler.com/",
                "sec-fetch-dest": "document",
                "sec-fetch-mode": "navigate",
                "sec-fetch-site": "same-origin",
                "upgrade-insecure-requests": "1",
            },
            allow_redirects=True,
        )
        r.raise_for_status()

        oauth_url = ""
        for h in r.history:
            if "/oauth2/v2/auth" in h.url:
                oauth_url = h.url
                break
        if not oauth_url:
            raise RTIError("Could not find ClassLink OAuth authorization URL")

        r = s.get(
            f"https://launchpad.classlink.com/{self.DISTRICT}",
            headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "referer": "https://launchpad.classlink.com/",
                "sec-fetch-dest": "document",
                "sec-fetch-mode": "navigate",
                "sec-fetch-site": "same-origin",
                "upgrade-insecure-requests": "1",
            },
        )
        r.raise_for_status()

        csrf_token = ""
        m = re.search(r"var IdConfig = (\{.*?\});", r.text, re.DOTALL)
        if m:
            try:
                cfg = json.loads(m.group(1))
                csrf_token = cfg.get("csrfToken", "")
            except Exception:
                csrf_token = ""
        if not csrf_token:
            m2 = re.search(r'"csrfToken"\s*:\s*"([^"]+)"', r.text)
            if m2:
                csrf_token = m2.group(1)
        if not csrf_token:
            raise RTIError("Could not extract CSRF token from ClassLink login page")

        r = s.post(
            "https://launchpad.classlink.com/login",
            headers={
                "accept": "*/*",
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "csrf-token": csrf_token,
                "origin": "https://launchpad.classlink.com",
                "referer": f"https://launchpad.classlink.com/{self.DISTRICT}",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "x-requested-with": "XMLHttpRequest",
            },
            data={
                "username": self.email,
                "password": self.password,
                "os": "Linux",
                "userdn": "",
                "code": self.DISTRICT,
                "Browser": "Chrome",
                "Resolution": "1920x1080",
            },
        )
        r.raise_for_status()

        try:
            login_json = r.json()
            desc = login_json.get("ResultDescription", "")
            if "Invalid username or password" in desc or "Invalid" in desc.lower():
                raise RTIError(f"Login failed: {desc}")
            if login_json.get("response") != "success" and login_json.get("ResultCode") != 1:
                raise RTIError(f"Login failed: {desc or login_json}")
        except ValueError:
            raise RTIError("Unexpected response from ClassLink login")

        r = s.get(
            oauth_url,
            headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "referer": f"https://launchpad.classlink.com/{self.DISTRICT}",
                "sec-fetch-dest": "document",
                "sec-fetch-mode": "navigate",
                "sec-fetch-site": "same-origin",
                "upgrade-insecure-requests": "1",
            },
            allow_redirects=True,
        )
        r.raise_for_status()

        if not s.cookies.get("rti_client_identifier"):
            s.cookies.set("rti_client_identifier", str(uuid.uuid4()))

        return True

    @staticmethod
    def _day_suffix(day):
        if 10 <= day % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return suffix

    def _api_headers(self, school_id, student_id, referer):
        return {
            "accept": "application/json, text/plain, */*",
            "buildid": "8454",
            "referer": referer,
            "rti-entity-id": str(student_id),
            "rti-entity-type": "Student",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "time-zone": "America/Denver",
            "time-zone-offset-minutes": "360",
        }

    def get_schedule(self):
        """Returns a dict: {student: {...}, school: {...}, days: [...]}"""
        s = self.s

        r = s.get(
            "https://www.rtischeduler.com/user/entities",
            headers={
                "accept": "application/json, text/plain, */*",
                "buildid": "8454",
                "referer": "https://www.rtischeduler.com/ui/choose-login",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "time-zone": "America/Denver",
                "time-zone-offset-minutes": "360",
            },
        )
        r.raise_for_status()
        entities = r.json()

        student = None
        for entity in entities:
            if entity.get("role") == "Student" or "Student" in entity.get("roles", []):
                student = entity
                break
        if not student:
            raise RTIError("No student entity found for this account")

        student_id = student.get("entity", {}).get("id")
        school_id = student.get("school", {}).get("id")
        school_info = student.get("school", {})

        import time
        from datetime import datetime, timedelta, timezone, date

        now = datetime.now(timezone.utc)
        # Start of the current week (Monday 00:00), end of next week (Sunday 23:59:59)
        days_since_monday = now.weekday()
        week_start = (now - timedelta(days=days_since_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        window_end = week_start + timedelta(days=13, hours=23, minutes=59, seconds=59)
        start = int(week_start.timestamp() * 1000)
        end = int(window_end.timestamp() * 1000)

        r = s.get(
            f"https://www.rtischeduler.com/api/operations/schedule/school/{school_id}/schedules-by-date-range",
            params={
                "start": start,
                "end": end,
                "withSessionsForStudent": student_id,
            },
            headers=self._api_headers(
                school_id, student_id, f"https://www.rtischeduler.com/ui/school-timeline/{school_id}"
            ),
        )
        r.raise_for_status()
        data = r.json()

        # This endpoint returns the schedule days in the window, plus the
        # sessions this student is actually enrolled in (mySessions), linked
        # to a day via sessionScheduleId.
        days = {}
        for sched in data.get("schedules", []) or []:
            ssid = sched.get("sessionScheduleId")
            # Whether the student can pick a class on this day
            # (e.g. Wednesdays have studentEnrollment=None -> not selectable)
            selectable = bool(sched.get("studentEnrollment"))
            days[ssid] = {
                "name": sched.get("name", "Untitled"),
                "start": sched.get("scheduleStart", ""),
                "end": sched.get("scheduleEnd", ""),
                "status": sched.get("status", "") if selectable else "No schedule",
                "selectable": selectable,
                "schedule_id": ssid,
                "self_enroll_key": sched.get("selfEnrollAccessKey", ""),
                "exists": True,
                "sessions": [],
            }
        # Baseline: use mySessions as the historical record for each day (this
        # is reliable for past days). For upcoming/selectable days the
        # authoritative self-enrollment service overrides it below.
        for sess in data.get("mySessions", []) or []:
            ssid = sess.get("sessionScheduleId")
            if ssid in days:
                days[ssid]["sessions"].append(
                    {
                        "name": sess.get("name", "Untitled"),
                        "type": sess.get("sessionType", ""),
                        "room": sess.get("room", ""),
                        "instructor": sess.get("instructor", {}) or {},
                    }
                )
        # Fill in every weekday in the window so that missing days (e.g. a
        # Wednesday with no published schedule) still appear as greyed-out.
        # The authoritative current enrollment for each day comes from the
        # self-enrollment service (mySessions can be stale), so we query it here.
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/Denver")).date()
        by_date = {}
        for ssid, d in days.items():
            by_date[d["start"][:10]] = d
        day_list = []
        day = week_start
        while day.date() <= window_end.date():
            if day.weekday() < 5:  # Mon-Fri only
                iso = day.date().isoformat()
                week_index = (day.date() - week_start.date()).days // 7
                general = {
                    "name": day.strftime("%A, %B ") + str(day.day) + self._day_suffix(day.day),
                    "start": iso,
                    "end": iso,
                    "week_index": week_index,
                    "week_label": "This Week" if week_index == 0 else ("Next Week" if week_index == 1 else f"Week {week_index + 1}"),
                }
                if iso in by_date:
                    day_info = by_date[iso]
                    day_info["past"] = date.fromisoformat(iso) < today
                    day_info.update(
                        {
                            "week_index": week_index,
                            "week_label": "This Week" if week_index == 0 else ("Next Week" if week_index == 1 else f"Week {week_index + 1}"),
                        }
                    )
                    if day_info["past"]:
                        day_info["status"] = "Past"
                        day_info["selectable"] = False
                    # Pull the real current enrollment from the self-enrollment
                    # service (mySessions can be out of date / show classes that
                    # aren't actually available). Tolerate errors: fall back to
                    # showing no sessions and the day's plain status.
                    if day_info.get("schedule_id") and day_info.get("selectable"):
                        try:
                            info = self._self_enrollment_info(
                                day_info["schedule_id"], student_id=student_id, school_id=school_id
                            )
                            sel = info.get("selectedSession") or {}
                            if sel.get("sessionId"):
                                inst = sel.get("instructor") or {}
                                day_info["sessions"] = [
                                    {
                                        "name": sel.get("name", "Untitled"),
                                        "type": sel.get("sessionType", ""),
                                        "room": sel.get("room", ""),
                                        "instructor": inst,
                                    }
                                ]
                            else:
                                day_info["sessions"] = []
                        except RTIError:
                            day_info["sessions"] = []
                    day_list.append(day_info)
                else:
                    general["status"] = "No schedule"
                    general["selectable"] = False
                    general["exists"] = False
                    general["sessions"] = []
                    day_list.append(general)
            day += timedelta(days=1)


        return {
            "student": student.get("entity", {}),
            "school": {
                "id": school_info.get("id"),
                "name": school_info.get("name"),
                "district": school_info.get("district"),
            },
            "days": day_list,
        }

    def _student_ref(self):
        """Returns (student_id, school_id) for the logged-in student entity."""
        s = self.s
        r = s.get(
            "https://www.rtischeduler.com/user/entities",
            headers={
                "accept": "application/json, text/plain, */*",
                "buildid": "8454",
                "referer": "https://www.rtischeduler.com/ui/choose-login",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "time-zone": "America/Denver",
                "time-zone-offset-minutes": "360",
            },
        )
        r.raise_for_status()
        for entity in r.json():
            if entity.get("role") == "Student" or "Student" in entity.get("roles", []):
                return entity.get("entity", {}).get("id"), entity.get("school", {}).get("id")
        raise RTIError("No student entity found for this account")

    def _self_enrollment_info(self, schedule_id, choosing_another=False, student_id=None, school_id=None):
        """GET the self-enrollment info for a schedule day: the open (choosable)
        sessions plus the student's current selected session for that day."""
        if student_id is None or school_id is None:
            student_id, school_id = self._student_ref()
        params = {}
        if choosing_another:
            params["choosingAnotherSession"] = "true"
        r = self.s.get(
            f"https://www.rtischeduler.com/self-enrollment-api/operations/self-enrollment/student/{student_id}/schedule/{schedule_id}/logged-in-self-enrollment",
            params=params or None,
            headers=self._api_headers(
                school_id, student_id, f"https://www.rtischeduler.com/ui/school-timeline/{school_id}"
            ),
        )
        if r.status_code == 401:
            raise RTIError("Session expired. Log in again.")
        if r.status_code == 400:
            raise RTIError(r.json().get("message", "Cannot choose a session for this day."))
        if r.status_code != 200:
            raise RTIError(f"Failed to load sessions (HTTP {r.status_code}).")
        return r.json()

    def list_open_sessions(self, schedule_id, choosing_another=False):
        """Returns the open (choosable) sessions for a schedule day, plus the
        current selection if already enrolled. Dict: {sessions, current, current_name}."""
        data = self._self_enrollment_info(schedule_id, choosing_another)
        sessions = []
        for entry in data.get("openSessions", []) or []:
            sess = entry.get("session", {}) or {}
            instructor = (entry.get("instructor", {}) or {}).get("lastName", "")
            sessions.append(
                {
                    "id": sess.get("sessionId"),
                    "name": sess.get("name", "Untitled"),
                    "room": sess.get("room", ""),
                    "instructor": instructor,
                    "capacity": sess.get("capacity"),
                    "enrolled": sess.get("currentlyEnrolled"),
                    "type": sess.get("sessionType", ""),
                }
            )
        sel = data.get("selectedSession") or {}
        instructor = sel.get("instructor") or {}
        return {
            "sessions": sessions,
            "current": sel.get("sessionId"),
            "current_name": sel.get("name"),
            "current_room": sel.get("room"),
            "current_teacher": f"{instructor.get('firstName', '')} {instructor.get('lastName', '')}".strip(),
        }

    def enroll(self, schedule_id, session_id):
        """Enrolls the student in a session for a schedule day. Returns the
        server's message, or raises RTIError on failure.
        Mirrors the exact request the RTI web app sends (empty body with
        content-length 0, XSRF double-submit, and the full browser-like
        headers), which is required for the server to accept the write."""
        student_id, school_id = self._student_ref()
        if not self.s.cookies.get("rti_client_identifier"):
            self.s.cookies.set("rti_client_identifier", str(uuid.uuid4()))
        referer = (
            f"https://www.rtischeduler.com/ui/school/{school_id}/schedule/{schedule_id}"
            f"/self-enrollment/student/{student_id}/confirm/{session_id}"
        )
        cookie_str = "; ".join(f"{k}={v}" for k, v in self.s.cookies.get_dict().items())
        xsrf = self.s.cookies.get("XSRF-TOKEN") or ""
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "buildid": "8527",
            "cache-control": "no-cache",
            "content-length": "0",
            "origin": "https://www.rtischeduler.com",
            "pragma": "no-cache",
            "priority": "u=1, i",
            "referer": referer,
            "rti-entity-id": str(student_id),
            "rti-entity-type": "Student",
            "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Linux"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "time-zone": "America/Denver",
            "time-zone-offset-minutes": "360",
            "user-agent": self.HEADERS["User-Agent"],
            "x-xsrf-token": xsrf,
            "Cookie": cookie_str,
        }
        r = self.s.post(
            f"https://www.rtischeduler.com/self-enrollment-api/operations/self-enrollment/student/{student_id}/session/{session_id}/logged-in-self-enrollment",
            headers=headers,
        )
        if r.status_code == 200:
            return r.text.strip() or "Enrolled."
        if r.status_code in (400, 403):
            try:
                msg = r.json().get("message") or r.json().get("error")
            except Exception:
                msg = None
            raise RTIError(msg or f"Enrollment rejected (HTTP {r.status_code}).")
        raise RTIError(f"Enrollment failed (HTTP {r.status_code}).")
