import argparse
import csv
import datetime as dt
import importlib.util
import pathlib
import time

import requests

REPO = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_START_TOLERANCE_SECONDS = 180
DEFAULT_DURATION_TOLERANCE_SECONDS = 120


def parse_duration(value):
    hours, minutes, seconds = [int(part) for part in value.split(":")]
    return hours * 3600 + minutes * 60 + seconds


def format_seconds(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds:
        parts.append(f"{seconds}s")
    return " ".join(parts) or "0s"


def load_jira_session():
    jira_link_path = REPO / "tools" / "jira_link.py"
    spec = importlib.util.spec_from_file_location("jira_link", jira_link_path)
    jira_link = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(jira_link)
    return jira_link.get_jira_session()


def matches_filters(description, include_filters):
    if not include_filters:
        return True
    return any(filter_text in description for filter_text in include_filters)


def load_toggl_rows(csv_path, include_filters):
    rows = []
    ignored = []
    with csv_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for row_number, row in enumerate(reader, start=2):
            description = row["Description"].strip()
            seconds = parse_duration(row["Duration"].strip())
            started = dt.datetime.fromisoformat(
                f"{row['Start date']}T{row['Start time']}"
            )
            item = {
                "row": row_number,
                "description": description,
                "seconds": seconds,
                "started": started,
            }
            if matches_filters(description, include_filters):
                rows.append(item)
            else:
                ignored.append(item)
    return rows, ignored


def jira_started_to_naive(value):
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z").replace(tzinfo=None)


def load_existing_worklogs(base_url, headers, issue_key):
    worklogs = []
    start_at = 0
    while True:
        response = requests.get(
            f"{base_url}/rest/api/3/issue/{issue_key}/worklog",
            headers=headers,
            params={"startAt": start_at, "maxResults": 100},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        batch = payload.get("worklogs", [])
        worklogs.extend(batch)
        start_at += len(batch)
        if start_at >= payload.get("total", 0) or not batch:
            break
    return worklogs


def find_duplicate(
    row,
    existing_worklogs,
    start_tolerance_seconds,
    duration_tolerance_seconds,
):
    for worklog in existing_worklogs:
        started_raw = worklog.get("started")
        seconds = worklog.get("timeSpentSeconds")
        if not started_raw or seconds is None:
            continue

        started = jira_started_to_naive(started_raw)
        start_delta = abs((row["started"] - started).total_seconds())
        duration_delta = abs(row["seconds"] - seconds)
        if (
            start_delta <= start_tolerance_seconds
            and duration_delta <= duration_tolerance_seconds
        ):
            return {
                "id": worklog.get("id"),
                "started": started_raw,
                "seconds": seconds,
                "start_delta": int(start_delta),
                "duration_delta": int(duration_delta),
            }
    return None


def format_jira_started(started, timezone_offset):
    return started.strftime(f"%Y-%m-%dT%H:%M:%S.000{timezone_offset}")


def create_worklog(base_url, headers, issue_key, row, timezone_offset, max_retries):
    payload = {
        "started": format_jira_started(row["started"], timezone_offset),
        "timeSpentSeconds": row["seconds"],
        "comment": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": row["description"]}],
                }
            ],
        },
    }

    for attempt in range(1, max_retries + 1):
        response = requests.post(
            f"{base_url}/rest/api/3/issue/{issue_key}/worklog",
            headers=headers,
            json=payload,
            timeout=30,
        )
        if response.status_code == 201:
            return response.json()
        if response.status_code == 429 or 500 <= response.status_code <= 599:
            retry_after = response.headers.get("Retry-After")
            wait_seconds = int(retry_after) if retry_after else attempt * 5
            print(
                f"RETRY row {row['row']}: HTTP {response.status_code}; "
                f"waiting {wait_seconds}s"
            )
            time.sleep(wait_seconds)
            continue

        response.raise_for_status()

    response.raise_for_status()
    raise RuntimeError(f"Failed to create worklog for row {row['row']}")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Import Toggl CSV rows into Jira worklogs."
    )
    parser.add_argument("--csv", required=True, help="Path to Toggl CSV export.")
    parser.add_argument("--issue", required=True, help="Target Jira issue key.")
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Description substring to include. Can be used multiple times.",
    )
    parser.add_argument("--apply", action="store_true", help="Write worklogs to Jira.")
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.75,
        help="Delay between successful Jira POST requests.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Retry count for HTTP 429 and 5xx responses.",
    )
    parser.add_argument(
        "--timezone-offset",
        default="+0400",
        help="Timezone offset used for Jira started timestamps.",
    )
    parser.add_argument(
        "--start-tolerance",
        type=int,
        default=DEFAULT_START_TOLERANCE_SECONDS,
        help="Duplicate detection tolerance for start time, in seconds.",
    )
    parser.add_argument(
        "--duration-tolerance",
        type=int,
        default=DEFAULT_DURATION_TOLERANCE_SECONDS,
        help="Duplicate detection tolerance for duration, in seconds.",
    )
    return parser


def main():
    args = build_parser().parse_args()
    csv_path = pathlib.Path(args.csv)
    if not csv_path.is_absolute():
        csv_path = REPO / csv_path
    if not csv_path.exists():
        raise FileNotFoundError(f"Toggl CSV file not found: {csv_path}")

    rows, ignored = load_toggl_rows(csv_path, args.include)
    base_url, headers = load_jira_session()
    existing_worklogs = load_existing_worklogs(base_url, headers, args.issue)

    planned_rows = []
    skipped_rows = []
    for row in rows:
        duplicate = find_duplicate(
            row,
            existing_worklogs,
            args.start_tolerance,
            args.duration_tolerance,
        )
        if duplicate:
            skipped_rows.append((row, duplicate))
            continue
        planned_rows.append(row)

    print(f"MODE: {'APPLY' if args.apply else 'DRY_RUN'}")
    print(f"CSV_PATH: {csv_path}")
    print(f"ISSUE: {args.issue}")
    print(f"FILTERS: {', '.join(args.include) if args.include else '<ALL>'}")
    print(f"SELECTED_ROWS: {len(rows)}")
    print(f"IGNORED_ROWS: {len(ignored)}")
    print(f"SELECTED_TOTAL: {format_seconds(sum(row['seconds'] for row in rows))}")
    if rows:
        print(
            f"SELECTED_RANGE: {min(row['started'] for row in rows)} -> "
            f"{max(row['started'] for row in rows)}"
        )
    print(f"EXISTING_JIRA_WORKLOGS: {len(existing_worklogs)}")
    print(f"SKIPPED_DUPLICATES: {len(skipped_rows)}")
    for row, duplicate in skipped_rows:
        print(
            f"  skip row {row['row']}: {row['started']} "
            f"{format_seconds(row['seconds'])}; Jira id {duplicate['id']} "
            f"delta start {duplicate['start_delta']}s, "
            f"duration {duplicate['duration_delta']}s"
        )
    print(f"PLANNED_ROWS: {len(planned_rows)}")
    print(
        f"PLANNED_TOTAL: {format_seconds(sum(row['seconds'] for row in planned_rows))}"
    )
    print("FIRST_PLANNED_ROWS:")
    for row in planned_rows[:10]:
        print(
            f"  row {row['row']}: {row['started']} | "
            f"{format_seconds(row['seconds'])} | {row['description']}"
        )
    print(f"SLEEP_SECONDS: {args.sleep}")

    if not args.apply:
        print("DRY_RUN_COMPLETE: no Jira worklogs were created.")
        return

    created = []
    for index, row in enumerate(planned_rows, start=1):
        duplicate = find_duplicate(
            row,
            existing_worklogs,
            args.start_tolerance,
            args.duration_tolerance,
        )
        if duplicate:
            print(
                "SKIP_DUPLICATE_BEFORE_POST "
                f"row {row['row']}: Jira id {duplicate['id']}"
            )
            continue

        worklog = create_worklog(
            base_url,
            headers,
            args.issue,
            row,
            args.timezone_offset,
            args.max_retries,
        )
        existing_worklogs.append(worklog)
        created.append(worklog)
        print(
            f"CREATED {index}/{len(planned_rows)} row {row['row']}: "
            f"Jira id {worklog.get('id')} | {row['started']} | "
            f"{format_seconds(row['seconds'])}"
        )
        if index < len(planned_rows):
            time.sleep(args.sleep)

    print(f"CREATED_TOTAL: {len(created)}")


if __name__ == "__main__":
    main()
