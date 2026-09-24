#!/usr/bin/env python3
"""
scripts/reconcile_jules_receipts.py

Derived Native Receipt Occupancy Witness Reconciler for Jules.

Input / Output Contract:
------------------------
Input:
  - Positional argument: path to a normalized JSON event-ledger file.
  - Required argument `--as-of`: explicit timezone-qualified ISO 8601 timestamp (e.g. 2026-09-24T12:00:00Z).

Input Event Envelope (schema: jules-native-events/v1):
  {
    "schema": "jules-native-events/v1",
    "coverage": "partial",
    "events": [
      {
        "evidence_id": str (nonempty, unique per event payload),
        "work_key": str (nonempty),
        "request_id": str (nonempty),
        "kind": str (one of requested, accepted, provider_completed, provider_failed,
                     creation_failed, correction_requested, correction_completed, merged),
        "occurred_at": str (ISO 8601 timezone-qualified timestamp),
        "source_ref": str (nonempty),
        "provider_task_id": optional str for requested/creation_failed; required nonempty str for all others
      }
    ]
  }

Output (Derived Observation JSON emitted to stdout):
  {
    "schema": "jules-derived-observation/v1",
    "status": "derived",
    "as_of": str,
    "window_start": str,
    "accepted_provider_ids_24h": list[str],
    "accepted_provider_count_24h": int,
    "holding_execution_provider_ids": list[str],
    "holding_execution_count": int,
    "unresolved_request_ids": list[str],
    "unresolved_request_count": int,
    "completed_not_merged_provider_ids": list[str],
    "completed_not_merged_count": int,
    "account_wide_usage": null,
    "current_provider_execution": null,
    "quota_remaining": null,
    "max_concurrency": null,
    "diagnostics": {
      "duplicate_work_detected": bool,
      "duplicate_work_details": dict[str, list[str]]
    },
    "evidence_summary": {
      "total_events": int,
      "unique_evidence_count": int,
      "first_event_at": str or null,
      "last_event_at": str or null
    },
    "identities_summary": {
      "work_keys": list[str],
      "request_ids": list[str],
      "provider_task_ids": list[str],
      "work_to_provider_tasks": dict[str, list[str]]
    }
  }

Exit Codes:
  0: Reconciliation succeeded, derived observation written to stdout.
  1 or 2: Validation failure, malformed JSON, or invalid arguments.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

SUPPORTED_KINDS = {
    "requested",
    "accepted",
    "provider_completed",
    "provider_failed",
    "creation_failed",
    "correction_requested",
    "correction_completed",
    "merged",
}

PROVIDER_REQUIRED_KINDS = {
    "accepted",
    "provider_completed",
    "provider_failed",
    "correction_requested",
    "correction_completed",
    "merged",
}

ISO_REGEX = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$"
)


def parse_iso_timestamp(ts_str: Any) -> datetime:
    if not isinstance(ts_str, str) or isinstance(ts_str, bool):
        raise ValueError("Timestamp must be a string")
    match = ISO_REGEX.match(ts_str)
    if not match:
        raise ValueError(f"Invalid or naive ISO 8601 timestamp format: {ts_str!r}")
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception as e:
        raise ValueError(f"Invalid calendar timestamp: {ts_str!r}") from e
    if dt.tzinfo is None:
        raise ValueError(f"Naive timestamp without timezone offset: {ts_str!r}")
    return dt.astimezone(timezone.utc)


def format_iso_timestamp(dt: datetime) -> str:
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def validate_nonempty_string(val: Any, field_name: str) -> str:
    if not isinstance(val, str) or isinstance(val, bool) or not val:
        raise ValueError(f"Field '{field_name}' must be a non-empty string, got {val!r}")
    return val


def reconcile(data: Any, as_of_str: str) -> Dict[str, Any]:
    as_of_dt = parse_iso_timestamp(as_of_str)
    window_start_dt = as_of_dt - timedelta(hours=24)

    if not isinstance(data, dict) or isinstance(data, bool):
        raise ValueError("Envelope must be a JSON object")

    if data.get("schema") != "jules-native-events/v1":
        raise ValueError(f"Unsupported schema: {data.get('schema')!r}")

    if data.get("coverage") != "partial":
        raise ValueError(f"Unsupported coverage: {data.get('coverage')!r}")

    raw_events = data.get("events")
    if not isinstance(raw_events, list) or isinstance(raw_events, bool):
        raise ValueError("'events' must be a list")

    total_raw_events = len(raw_events)

    # 1. Deduplicate identical evidence, validate individual fields
    evidence_by_id: Dict[str, Dict[str, Any]] = {}
    parsed_events: List[Dict[str, Any]] = []

    for idx, item in enumerate(raw_events):
        if not isinstance(item, dict) or isinstance(item, bool):
            raise ValueError(f"Event at index {idx} is not a dict")

        evidence_id = validate_nonempty_string(item.get("evidence_id"), f"events[{idx}].evidence_id")
        work_key = validate_nonempty_string(item.get("work_key"), f"events[{idx}].work_key")
        request_id = validate_nonempty_string(item.get("request_id"), f"events[{idx}].request_id")
        source_ref = validate_nonempty_string(item.get("source_ref"), f"events[{idx}].source_ref")
        kind = validate_nonempty_string(item.get("kind"), f"events[{idx}].kind")

        if kind not in SUPPORTED_KINDS:
            raise ValueError(f"Unsupported event kind: {kind!r}")

        provider_task_id_raw = item.get("provider_task_id")
        if kind in PROVIDER_REQUIRED_KINDS:
            provider_task_id = validate_nonempty_string(
                provider_task_id_raw, f"events[{idx}].provider_task_id"
            )
        else:
            if provider_task_id_raw is not None:
                provider_task_id = validate_nonempty_string(
                    provider_task_id_raw, f"events[{idx}].provider_task_id"
                )
            else:
                provider_task_id = None

        occurred_at_raw = item.get("occurred_at")
        occurred_at_dt = parse_iso_timestamp(occurred_at_raw)

        if occurred_at_dt > as_of_dt:
            raise ValueError(f"Event occurred_at {occurred_at_raw!r} is after as_of {as_of_str!r}")

        canonical_event = {
            "evidence_id": evidence_id,
            "work_key": work_key,
            "request_id": request_id,
            "kind": kind,
            "occurred_at": occurred_at_raw,
            "occurred_at_dt": occurred_at_dt,
            "source_ref": source_ref,
            "provider_task_id": provider_task_id,
        }

        if evidence_id in evidence_by_id:
            existing = evidence_by_id[evidence_id]
            # Compare canonical representations (excluding parsed datetime object)
            ex_comp = {k: v for k, v in existing.items() if k != "occurred_at_dt"}
            curr_comp = {k: v for k, v in canonical_event.items() if k != "occurred_at_dt"}
            if ex_comp != curr_comp:
                raise ValueError(f"Conflicting duplicate evidence for evidence_id: {evidence_id}")
            # Idempotent repeated snapshot -> skip duplicate
            continue

        evidence_by_id[evidence_id] = canonical_event
        parsed_events.append(canonical_event)

    # 2. Identity binding consistency checks
    request_to_work: Dict[str, str] = {}
    task_to_work: Dict[str, str] = {}
    task_to_request: Dict[str, str] = {}

    for ev in parsed_events:
        r_id = ev["request_id"]
        w_key = ev["work_key"]
        p_id = ev["provider_task_id"]

        if r_id in request_to_work and request_to_work[r_id] != w_key:
            raise ValueError(
                f"Contradiction: Request ID {r_id!r} bound to conflicting work keys ({request_to_work[r_id]!r} vs {w_key!r})"
            )
        request_to_work[r_id] = w_key

        if p_id is not None:
            if p_id in task_to_work and task_to_work[p_id] != w_key:
                raise ValueError(
                    f"Contradiction: Provider task ID {p_id!r} bound to conflicting work keys ({task_to_work[p_id]!r} vs {w_key!r})"
                )
            task_to_work[p_id] = w_key

            if p_id in task_to_request and task_to_request[p_id] != r_id:
                raise ValueError(
                    f"Contradiction: Provider task ID {p_id!r} bound to conflicting request IDs ({task_to_request[p_id]!r} vs {r_id!r})"
                )
            task_to_request[p_id] = r_id

    # 3. Sort by occurred_at_dt (timestamps, not file order)
    parsed_events.sort(key=lambda x: x["occurred_at_dt"])

    # Check for ambiguous conflicting state transitions at the exact same timestamp
    ts_groups: Dict[Tuple[datetime, str], List[Dict[str, Any]]] = {}
    for ev in parsed_events:
        entity_key = ev["provider_task_id"] or ev["request_id"]
        group_key = (ev["occurred_at_dt"], entity_key)
        ts_groups.setdefault(group_key, []).append(ev)

    for (ts, entity), group in ts_groups.items():
        if len(group) > 1:
            kinds = [g["kind"] for g in group]
            # Check if there are distinct kinds at the exact same timestamp
            if len(set(kinds)) > 1:
                raise ValueError(
                    f"Ambiguous conflicting state transitions at timestamp {ts.isoformat()} for entity {entity!r}: {kinds}"
                )

    # 4. Process State Machine Transitions
    request_has_accepted: Dict[str, bool] = {}
    request_has_creation_failed: Dict[str, bool] = {}
    request_has_requested: Dict[str, bool] = {}

    # Check if any request ever has an accepted event
    for ev in parsed_events:
        r_id = ev["request_id"]
        if ev["kind"] == "requested":
            request_has_requested[r_id] = True
        elif ev["kind"] == "accepted":
            request_has_accepted[r_id] = True

    # Validate creation_failed rules across history
    for ev in parsed_events:
        r_id = ev["request_id"]
        if ev["kind"] == "creation_failed":
            if request_has_accepted.get(r_id, False):
                raise ValueError(
                    f"creation_failed cannot undo or override an accepted request: {r_id!r}"
                )
            request_has_creation_failed[r_id] = True

    # Track Provider Tasks state step-by-step
    task_accepted_ever: Dict[str, bool] = {}
    task_accepted_24h: Dict[str, bool] = {}
    task_execution_holding: Dict[str, bool] = {}
    task_latest_terminal: Dict[str, Optional[str]] = {}
    task_is_merged: Dict[str, bool] = {}

    for ev in parsed_events:
        p_id = ev["provider_task_id"]
        kind = ev["kind"]
        dt = ev["occurred_at_dt"]

        if kind == "accepted":
            task_accepted_ever[p_id] = True
            task_execution_holding[p_id] = True
            task_latest_terminal[p_id] = None
            if window_start_dt < dt <= as_of_dt:
                task_accepted_24h[p_id] = True

        elif kind in ("provider_completed", "provider_failed", "correction_requested", "correction_completed", "merged"):
            if not task_accepted_ever.get(p_id, False):
                raise ValueError(
                    f"State transition {kind!r} for provider task {p_id!r} without prior 'accepted' event"
                )

            if kind == "correction_requested":
                task_execution_holding[p_id] = True
                task_latest_terminal[p_id] = None

            elif kind == "provider_completed":
                task_execution_holding[p_id] = False
                task_latest_terminal[p_id] = "completed"

            elif kind == "provider_failed":
                task_execution_holding[p_id] = False
                task_latest_terminal[p_id] = "failed"

            elif kind == "correction_completed":
                task_execution_holding[p_id] = False
                task_latest_terminal[p_id] = "completed"

            elif kind == "merged":
                task_is_merged[p_id] = True

    # 5. Derive Outputs
    accepted_provider_ids_24h = sorted([p_id for p_id in task_accepted_24h.keys()])

    holding_execution_provider_ids = sorted(
        [p_id for p_id, holding in task_execution_holding.items() if holding]
    )

    unresolved_request_ids = sorted(
        [
            r_id
            for r_id in request_has_requested.keys()
            if not request_has_accepted.get(r_id, False)
            and not request_has_creation_failed.get(r_id, False)
        ]
    )

    completed_not_merged_provider_ids = sorted(
        [
            p_id
            for p_id, terminal_status in task_latest_terminal.items()
            if terminal_status == "completed"
            and not task_execution_holding.get(p_id, False)
            and not task_is_merged.get(p_id, False)
        ]
    )

    # Work keys to provider tasks summary
    work_to_tasks: Dict[str, List[str]] = {}
    for p_id, w_key in task_to_work.items():
        work_to_tasks.setdefault(w_key, []).append(p_id)
    for w_key in work_to_tasks:
        work_to_tasks[w_key].sort()

    duplicate_work_details = {
        w_key: tasks for w_key, tasks in work_to_tasks.items() if len(tasks) > 1
    }
    duplicate_work_detected = len(duplicate_work_details) > 0

    all_work_keys = sorted(list(set(request_to_work.values()).union(set(task_to_work.values()))))
    all_request_ids = sorted(list(request_to_work.keys()))
    all_provider_task_ids = sorted(list(task_to_work.keys()))

    first_event_at = format_iso_timestamp(parsed_events[0]["occurred_at_dt"]) if parsed_events else None
    last_event_at = format_iso_timestamp(parsed_events[-1]["occurred_at_dt"]) if parsed_events else None

    output = {
        "schema": "jules-derived-observation/v1",
        "status": "derived",
        "as_of": format_iso_timestamp(as_of_dt),
        "window_start": format_iso_timestamp(window_start_dt),
        "accepted_provider_ids_24h": accepted_provider_ids_24h,
        "accepted_provider_count_24h": len(accepted_provider_ids_24h),
        "holding_execution_provider_ids": holding_execution_provider_ids,
        "holding_execution_count": len(holding_execution_provider_ids),
        "unresolved_request_ids": unresolved_request_ids,
        "unresolved_request_count": len(unresolved_request_ids),
        "completed_not_merged_provider_ids": completed_not_merged_provider_ids,
        "completed_not_merged_count": len(completed_not_merged_provider_ids),
        "account_wide_usage": None,
        "current_provider_execution": None,
        "quota_remaining": None,
        "max_concurrency": None,
        "diagnostics": {
            "duplicate_work_detected": duplicate_work_detected,
            "duplicate_work_details": duplicate_work_details,
        },
        "evidence_summary": {
            "total_events": total_raw_events,
            "unique_evidence_count": len(parsed_events),
            "first_event_at": first_event_at,
            "last_event_at": last_event_at,
        },
        "identities_summary": {
            "work_keys": all_work_keys,
            "request_ids": all_request_ids,
            "provider_task_ids": all_provider_task_ids,
            "work_to_provider_tasks": work_to_tasks,
        },
    }
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile Jules native event receipts into a derived occupancy observation."
    )
    parser.add_argument("event_file", help="Path to normalized JSON event-ledger file")
    parser.add_argument(
        "--as-of",
        required=True,
        help="Explicit timezone-qualified ISO 8601 timestamp (e.g. 2026-09-24T12:00:00Z)",
    )

    args = parser.parse_args()

    try:
        with open(args.event_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        result = reconcile(data, args.as_of)
        print(json.dumps(result, indent=2))
        sys.exit(0)
    except Exception as e:
        error_output = {
            "schema": "jules-derived-observation/v1",
            "status": "validation_failed",
            "error": str(e),
        }
        sys.stderr.write(f"Reconciliation error: {e}\n")
        print(json.dumps(error_output, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
