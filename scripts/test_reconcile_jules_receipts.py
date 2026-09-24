#!/usr/bin/env python3
"""
scripts/test_reconcile_jules_receipts.py

Unit and integration tests for reconcile_jules_receipts.py.
Covers all required regression acceptance scenarios.
"""

from datetime import datetime, timezone
import json
import os
import subprocess
import sys
import tempfile
import unittest

from reconcile_jules_receipts import parse_iso_timestamp, reconcile


class TestReconcileJulesReceipts(unittest.TestCase):

    def setUp(self):
        self.as_of = "2026-09-24T12:00:00Z"
        self.base_envelope = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "events": []
        }

    def test_stale_carried_counts_ignored(self):
        """Stale carried count in input envelope is ignored and derived strictly from events."""
        envelope = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "carried_total_active": 13,
            "events": [
                {
                    "evidence_id": "ev-1",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "accepted",
                    "occurred_at": "2026-09-24T10:00:00Z",
                    "source_ref": "ref-1",
                    "provider_task_id": "task-1"
                },
                {
                    "evidence_id": "ev-2",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "provider_completed",
                    "occurred_at": "2026-09-24T11:00:00Z",
                    "source_ref": "ref-2",
                    "provider_task_id": "task-1"
                }
            ]
        }
        res = reconcile(envelope, self.as_of)
        self.assertEqual(res["holding_execution_count"], 0)
        self.assertEqual(res["holding_execution_provider_ids"], [])
        self.assertEqual(res["completed_not_merged_provider_ids"], ["task-1"])
        self.assertIsNone(res["account_wide_usage"])
        self.assertIsNone(res["current_provider_execution"])

    def test_repeated_snapshots_deduplicate(self):
        """Identical repeated evidence is idempotent and deduplicated."""
        ev = {
            "evidence_id": "ev-1",
            "work_key": "repo:org/repo#1",
            "request_id": "req-1",
            "kind": "accepted",
            "occurred_at": "2026-09-24T10:00:00Z",
            "source_ref": "ref-1",
            "provider_task_id": "task-1"
        }
        envelope = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "events": [ev, dict(ev), dict(ev)]
        }
        res = reconcile(envelope, self.as_of)
        self.assertEqual(res["evidence_summary"]["total_events"], 3)
        self.assertEqual(res["evidence_summary"]["unique_evidence_count"], 1)
        self.assertEqual(res["holding_execution_provider_ids"], ["task-1"])

    def test_input_order_independence(self):
        """Sorting by timestamp guarantees order independence."""
        ev1 = {
            "evidence_id": "ev-1",
            "work_key": "repo:org/repo#1",
            "request_id": "req-1",
            "kind": "requested",
            "occurred_at": "2026-09-24T09:00:00Z",
            "source_ref": "ref-1"
        }
        ev2 = {
            "evidence_id": "ev-2",
            "work_key": "repo:org/repo#1",
            "request_id": "req-1",
            "kind": "accepted",
            "occurred_at": "2026-09-24T10:00:00Z",
            "source_ref": "ref-2",
            "provider_task_id": "task-1"
        }
        ev3 = {
            "evidence_id": "ev-3",
            "work_key": "repo:org/repo#1",
            "request_id": "req-1",
            "kind": "provider_completed",
            "occurred_at": "2026-09-24T11:00:00Z",
            "source_ref": "ref-3",
            "provider_task_id": "task-1"
        }

        res_forward = reconcile({"schema": "jules-native-events/v1", "coverage": "partial", "events": [ev1, ev2, ev3]}, self.as_of)
        res_reverse = reconcile({"schema": "jules-native-events/v1", "coverage": "partial", "events": [ev3, ev1, ev2]}, self.as_of)

        self.assertEqual(res_forward["holding_execution_provider_ids"], res_reverse["holding_execution_provider_ids"])
        self.assertEqual(res_forward["completed_not_merged_provider_ids"], res_reverse["completed_not_merged_provider_ids"])
        self.assertEqual(res_forward["unresolved_request_ids"], res_reverse["unresolved_request_ids"])

    def test_request_then_accept_single_hold(self):
        """Request followed by accept counts 1 execution hold, not 2."""
        envelope = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "events": [
                {
                    "evidence_id": "ev-1",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "requested",
                    "occurred_at": "2026-09-24T09:00:00Z",
                    "source_ref": "ref-1"
                },
                {
                    "evidence_id": "ev-2",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "accepted",
                    "occurred_at": "2026-09-24T10:00:00Z",
                    "source_ref": "ref-2",
                    "provider_task_id": "task-1"
                }
            ]
        }
        res = reconcile(envelope, self.as_of)
        self.assertEqual(res["holding_execution_count"], 1)
        self.assertEqual(res["holding_execution_provider_ids"], ["task-1"])
        self.assertEqual(res["unresolved_request_count"], 0)

    def test_terminal_open_pr_frees_execution_retains_delivery_wip(self):
        """Terminal provider completion frees execution hold but retains delivery WIP when PR is unmerged."""
        envelope = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "events": [
                {
                    "evidence_id": "ev-1",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "accepted",
                    "occurred_at": "2026-09-24T10:00:00Z",
                    "source_ref": "ref-1",
                    "provider_task_id": "task-1"
                },
                {
                    "evidence_id": "ev-2",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "provider_completed",
                    "occurred_at": "2026-09-24T11:00:00Z",
                    "source_ref": "ref-2",
                    "provider_task_id": "task-1"
                }
            ]
        }
        res = reconcile(envelope, self.as_of)
        self.assertEqual(res["holding_execution_provider_ids"], [])
        self.assertEqual(res["completed_not_merged_provider_ids"], ["task-1"])

    def test_later_correction_reacquires_hold_and_completion_releases_it(self):
        """Correction request reacquires execution hold without counting as new start; completion releases it."""
        envelope = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "events": [
                {
                    "evidence_id": "ev-1",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "accepted",
                    "occurred_at": "2026-09-24T08:00:00Z",
                    "source_ref": "ref-1",
                    "provider_task_id": "task-1"
                },
                {
                    "evidence_id": "ev-2",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "provider_completed",
                    "occurred_at": "2026-09-24T09:00:00Z",
                    "source_ref": "ref-2",
                    "provider_task_id": "task-1"
                },
                {
                    "evidence_id": "ev-3",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "correction_requested",
                    "occurred_at": "2026-09-24T10:00:00Z",
                    "source_ref": "ref-3",
                    "provider_task_id": "task-1"
                }
            ]
        }
        res1 = reconcile(envelope, self.as_of)
        self.assertEqual(res1["holding_execution_provider_ids"], ["task-1"])
        self.assertEqual(res1["completed_not_merged_provider_ids"], [])
        self.assertEqual(res1["accepted_provider_count_24h"], 1)

        # Complete correction
        envelope["events"].append({
            "evidence_id": "ev-4",
            "work_key": "repo:org/repo#1",
            "request_id": "req-1",
            "kind": "correction_completed",
            "occurred_at": "2026-09-24T11:00:00Z",
            "source_ref": "ref-4",
            "provider_task_id": "task-1"
        })
        res2 = reconcile(envelope, self.as_of)
        self.assertEqual(res2["holding_execution_provider_ids"], [])
        self.assertEqual(res2["completed_not_merged_provider_ids"], ["task-1"])
        self.assertEqual(res2["accepted_provider_count_24h"], 1)

    def test_explicit_creation_failure_releases_only_that_request(self):
        """Creation failure releases only the specific failed request."""
        envelope = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "events": [
                {
                    "evidence_id": "ev-1",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "requested",
                    "occurred_at": "2026-09-24T09:00:00Z",
                    "source_ref": "ref-1"
                },
                {
                    "evidence_id": "ev-2",
                    "work_key": "repo:org/repo#2",
                    "request_id": "req-2",
                    "kind": "requested",
                    "occurred_at": "2026-09-24T09:30:00Z",
                    "source_ref": "ref-2"
                },
                {
                    "evidence_id": "ev-3",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "creation_failed",
                    "occurred_at": "2026-09-24T10:00:00Z",
                    "source_ref": "ref-3"
                }
            ]
        }
        res = reconcile(envelope, self.as_of)
        self.assertEqual(res["unresolved_request_ids"], ["req-2"])

    def test_creation_failed_cannot_undo_accepted_request(self):
        """creation_failed cannot undo or override an accepted request."""
        envelope = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "events": [
                {
                    "evidence_id": "ev-1",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "accepted",
                    "occurred_at": "2026-09-24T09:00:00Z",
                    "source_ref": "ref-1",
                    "provider_task_id": "task-1"
                },
                {
                    "evidence_id": "ev-2",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "creation_failed",
                    "occurred_at": "2026-09-24T10:00:00Z",
                    "source_ref": "ref-2"
                }
            ]
        }
        with self.assertRaises(ValueError):
            reconcile(envelope, self.as_of)

    def test_aged_unresolved_requests_remain(self):
        """Old unresolved request outside the 24h rolling window remains unresolved."""
        envelope = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "events": [
                {
                    "evidence_id": "ev-old",
                    "work_key": "repo:org/repo#old",
                    "request_id": "req-old",
                    "kind": "requested",
                    "occurred_at": "2026-08-01T00:00:00Z",
                    "source_ref": "ref-old"
                }
            ]
        }
        res = reconcile(envelope, self.as_of)
        self.assertEqual(res["unresolved_request_ids"], ["req-old"])
        self.assertEqual(res["accepted_provider_ids_24h"], [])

    def test_rolling_24h_boundaries_and_timezone_equivalence(self):
        """Rolling 24h window (start exclusive, end inclusive) and timezone offset equivalence."""
        # Window: (2026-09-23T12:00:00Z, 2026-09-24T12:00:00Z]
        envelope = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "events": [
                # Exact 24h start boundary (exclusive -> should NOT be included in 24h count)
                {
                    "evidence_id": "ev-start-boundary",
                    "work_key": "repo:org/repo#b1",
                    "request_id": "req-b1",
                    "kind": "accepted",
                    "occurred_at": "2026-09-23T12:00:00Z",
                    "source_ref": "ref-b1",
                    "provider_task_id": "task-b1"
                },
                # Equivalent timezone instant: 2026-09-24T08:00:00-04:00 == 2026-09-24T12:00:00Z (end inclusive -> INCLUDED)
                {
                    "evidence_id": "ev-end-boundary-tz",
                    "work_key": "repo:org/repo#b2",
                    "request_id": "req-b2",
                    "kind": "accepted",
                    "occurred_at": "2026-09-24T08:00:00-04:00",
                    "source_ref": "ref-b2",
                    "provider_task_id": "task-b2"
                }
            ]
        }
        res = reconcile(envelope, self.as_of)
        self.assertNotIn("task-b1", res["accepted_provider_ids_24h"])
        self.assertIn("task-b2", res["accepted_provider_ids_24h"])
        self.assertEqual(res["accepted_provider_count_24h"], 1)

    def test_multiple_tasks_per_work_diagnostic(self):
        """Multiple distinct provider tasks for one work_key produce duplicate_work_detected diagnostic."""
        envelope = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "events": [
                {
                    "evidence_id": "ev-1",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "accepted",
                    "occurred_at": "2026-09-24T08:00:00Z",
                    "source_ref": "ref-1",
                    "provider_task_id": "task-1"
                },
                {
                    "evidence_id": "ev-2",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-2",
                    "kind": "accepted",
                    "occurred_at": "2026-09-24T09:00:00Z",
                    "source_ref": "ref-2",
                    "provider_task_id": "task-2"
                }
            ]
        }
        res = reconcile(envelope, self.as_of)
        self.assertTrue(res["diagnostics"]["duplicate_work_detected"])
        self.assertEqual(res["diagnostics"]["duplicate_work_details"]["repo:org/repo#1"], ["task-1", "task-2"])
        self.assertEqual(res["holding_execution_count"], 2)

    def test_duplicate_evidence_conflict(self):
        """Conflicting payload for same evidence_id raises error."""
        envelope = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "events": [
                {
                    "evidence_id": "ev-dup",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "requested",
                    "occurred_at": "2026-09-24T08:00:00Z",
                    "source_ref": "ref-1"
                },
                {
                    "evidence_id": "ev-dup",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "accepted",  # Conflicting kind
                    "occurred_at": "2026-09-24T08:00:00Z",
                    "source_ref": "ref-1",
                    "provider_task_id": "task-1"
                }
            ]
        }
        with self.assertRaises(ValueError):
            reconcile(envelope, self.as_of)

    def test_task_work_request_contradiction(self):
        """Same provider_task_id bound to different request_ids or work_keys raises error."""
        envelope = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "events": [
                {
                    "evidence_id": "ev-1",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "accepted",
                    "occurred_at": "2026-09-24T08:00:00Z",
                    "source_ref": "ref-1",
                    "provider_task_id": "task-1"
                },
                {
                    "evidence_id": "ev-2",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-2",  # Contradicting request_id for same task-1
                    "kind": "provider_completed",
                    "occurred_at": "2026-09-24T09:00:00Z",
                    "source_ref": "ref-2",
                    "provider_task_id": "task-1"
                }
            ]
        }
        with self.assertRaises(ValueError):
            reconcile(envelope, self.as_of)

    def test_missing_acceptance_for_terminal(self):
        """Terminal observation without prior acceptance raises error."""
        envelope = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "events": [
                {
                    "evidence_id": "ev-1",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "provider_completed",
                    "occurred_at": "2026-09-24T08:00:00Z",
                    "source_ref": "ref-1",
                    "provider_task_id": "task-never-accepted"
                }
            ]
        }
        with self.assertRaises(ValueError):
            reconcile(envelope, self.as_of)

    def test_malformed_future_naive_timestamps_and_types(self):
        """Naive timestamp, future timestamp, or wrong field types raise error."""
        # Naive timestamp
        envelope_naive = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "events": [
                {
                    "evidence_id": "ev-1",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "requested",
                    "occurred_at": "2026-09-24T08:00:00",  # No timezone
                    "source_ref": "ref-1"
                }
            ]
        }
        with self.assertRaises(ValueError):
            reconcile(envelope_naive, self.as_of)

        # Future timestamp relative to as_of
        envelope_future = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "events": [
                {
                    "evidence_id": "ev-1",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "requested",
                    "occurred_at": "2026-09-24T13:00:00Z",  # after 12:00:00Z as_of
                    "source_ref": "ref-1"
                }
            ]
        }
        with self.assertRaises(ValueError):
            reconcile(envelope_future, self.as_of)

        # Bool as string coercion attempt
        envelope_bool = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "events": [
                {
                    "evidence_id": True,  # Bool instead of str
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "requested",
                    "occurred_at": "2026-09-24T08:00:00Z",
                    "source_ref": "ref-1"
                }
            ]
        }
        with self.assertRaises(ValueError):
            reconcile(envelope_bool, self.as_of)

    def test_merge_alone_does_not_release_provider_hold(self):
        """Merged event alone does not release execution hold."""
        envelope = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "events": [
                {
                    "evidence_id": "ev-1",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "accepted",
                    "occurred_at": "2026-09-24T08:00:00Z",
                    "source_ref": "ref-1",
                    "provider_task_id": "task-1"
                },
                {
                    "evidence_id": "ev-2",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "merged",
                    "occurred_at": "2026-09-24T09:00:00Z",
                    "source_ref": "ref-2",
                    "provider_task_id": "task-1"
                }
            ]
        }
        res = reconcile(envelope, self.as_of)
        self.assertEqual(res["holding_execution_provider_ids"], ["task-1"])
        self.assertEqual(res["completed_not_merged_provider_ids"], [])

    def test_cli_malformed_input_and_bytes_unchanged(self):
        """CLI returns nonzero exit code on malformed input; input file remains unchanged."""
        valid_envelope = {
            "schema": "jules-native-events/v1",
            "coverage": "partial",
            "events": [
                {
                    "evidence_id": "ev-1",
                    "work_key": "repo:org/repo#1",
                    "request_id": "req-1",
                    "kind": "requested",
                    "occurred_at": "2026-09-24T08:00:00Z",
                    "source_ref": "ref-1"
                }
            ]
        }
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as tf:
            tf_path = tf.name
            json.dump(valid_envelope, tf)

        try:
            with open(tf_path, "rb") as f:
                initial_bytes = f.read()

            script_path = os.path.join(os.path.dirname(__file__), "reconcile_jules_receipts.py")
            child_env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

            # Run valid CLI call
            proc = subprocess.run(
                [sys.executable, script_path, tf_path, "--as-of", self.as_of],
                capture_output=True,
                text=True,
                env=child_env
            )
            self.assertEqual(proc.returncode, 0)
            out_data = json.loads(proc.stdout)
            self.assertEqual(out_data["status"], "derived")

            # Verify file bytes unchanged
            with open(tf_path, "rb") as f:
                post_bytes = f.read()
            self.assertEqual(initial_bytes, post_bytes)

            # Run invalid CLI call (bad as-of)
            proc_bad = subprocess.run(
                [sys.executable, script_path, tf_path, "--as-of", "invalid-timestamp"],
                capture_output=True,
                text=True,
                env=child_env
            )
            self.assertNotEqual(proc_bad.returncode, 0)

        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_no_network_or_credential_imports(self):
        """Script contains no network or credential access imports."""
        script_path = os.path.join(os.path.dirname(__file__), "reconcile_jules_receipts.py")
        with open(script_path, "r", encoding="utf-8") as f:
            code = f.read()

        forbidden = ["urllib", "requests", "socket", "http.client", "subprocess", "GITHUB_TOKEN"]
        for term in forbidden:
            self.assertNotIn(f"import {term}", code)
            self.assertNotIn(f"from {term}", code)


if __name__ == "__main__":
    unittest.main()
