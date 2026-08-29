#!/usr/bin/env python3
import getpass
import time
from rti_client import RTIClient, RTIError


def fmt_time(iso):
    if not iso:
        return ""
    if len(iso) <= 10:
        return ""
    try:
        return time.strftime("%I:%M %p", time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return iso


def main():
    import sys

    if len(sys.argv) >= 3:
        email, password = sys.argv[1], sys.argv[2]
    else:
        email = input("Email: ")
        password = getpass.getpass("Password: ")

    client = RTIClient(email, password)
    print("[+] Logging in...")
    try:
        client.login()
    except RTIError as e:
        print(f"[-] {e}")
        sys.exit(1)
    print("[+] Logged in, fetching schedule...")

    schedule = client.get_schedule()
    student = schedule["student"]
    print(f"[+] Student: {student.get('firstName')} {student.get('lastName')} ({schedule['school'].get('name')})")

    print("\n" + "=" * 60)
    print("MY SCHEDULE (RTI)")
    print("=" * 60)

    if not schedule["days"]:
        print("  No upcoming schedules found.")

    for day in schedule["days"]:
        time_range = fmt_time(day["start"])
        if day["end"]:
            time_range += f" - {fmt_time(day['end'])}"
        print(f"\n  {day['name']}  ({time_range})  [{day['status']}]")
        if not day["sessions"]:
            print("    (no sessions for you)")
        for sess in day["sessions"]:
            teacher = f"{sess['instructor'].get('firstName', '')} {sess['instructor'].get('lastName', '')}".strip()
            detail = [p for p in [sess["name"], sess["type"], teacher, sess["room"]] if p]
            print(f"    - {' | '.join(detail)}")


if __name__ == "__main__":
    main()
