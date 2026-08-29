#!/usr/bin/env python3
"""CLI wrapper: fetch and print the schedule for a given ClassLink account.

Usage:
    python3 get_schedule.py EMAIL PASSWORD
"""
import argparse
import json
import sys

from rti_client import RTIClient, RTIError


def main():
    parser = argparse.ArgumentParser(description="Fetch an RTI Scheduler schedule.")
    parser.add_argument("email")
    parser.add_argument("password")
    args = parser.parse_args()

    client = RTIClient(args.email, args.password)
    try:
        client.login()
        schedule = client.get_schedule()
    except RTIError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"{schedule['student'].get('firstName')} {schedule['student'].get('lastName')} - {schedule['school'].get('name')}")
    for day in schedule["days"]:
        status = "Past" if day.get("past") else (day["status"] or "")
        sessions = "; ".join(
            f"{s['name']} ({s['instructor'].get('lastName', '')} / {s['room']})" for s in day["sessions"]
        )
        print(f"[{day['week_label']}] {day['name']} ({status}) | {sessions or 'no sessions'}")


if __name__ == "__main__":
    main()
