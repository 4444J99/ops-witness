"""Independent regression checks for native receipt accounting."""

import json
import unittest

from reconcile_jules_receipts import reconcile


class TestAcceptanceRepair(unittest.TestCase):
    """Adversarial checks for defects missed by the original provider suite."""

    def event(self, eid, kind, when, task="t", request="r", work="w"):
        return {"evidence_id": eid, "kind": kind, "occurred_at": when,
                "provider_task_id": task, "request_id": request,
                "work_key": work, "source_ref": "synthetic:" + eid}

    def observe(self, *events, as_of="2026-09-24T13:00:00Z"):
        return reconcile({"schema": "jules-native-events/v1", "coverage": "partial",
                          "events": list(events)}, as_of)

    def test_nanosecond_inside_window(self):
        result = self.observe(self.event("a", "accepted", "2026-09-23T13:00:00.000000002Z"),
                              as_of="2026-09-24T13:00:00.000000001Z")
        self.assertEqual(result["accepted_provider_count_24h"], 1)
        self.assertEqual(result["window_start"], "2026-09-23T13:00:00.000000001Z")

    def test_one_nanosecond_future_is_rejected(self):
        with self.assertRaises(ValueError):
            self.observe(self.event("a", "accepted", "2026-09-24T13:00:00.000000002Z"),
                         as_of="2026-09-24T13:00:00.000000001Z")

    def test_distinct_nanosecond_transitions_are_not_a_tie(self):
        result = self.observe(self.event("a", "accepted", "2026-09-24T12:00:00.000000001Z"),
                              self.event("b", "provider_completed", "2026-09-24T12:00:00.000000002Z"))
        self.assertEqual(result["holding_execution_count"], 0)
        self.assertEqual(result["completed_not_merged_count"], 1)

    def test_invalid_offset_components_are_not_normalized(self):
        for suffix in ("+00:99", "-01:60", "+24:00"):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                self.observe(self.event("a", "accepted", "2026-09-24T10:00:00" + suffix))

    def test_repeated_later_acceptance_is_contradictory_not_a_new_start(self):
        with self.assertRaises(ValueError):
            self.observe(self.event("a", "accepted", "2026-09-20T10:00:00Z"),
                         self.event("b", "provider_completed", "2026-09-20T11:00:00Z"),
                         self.event("c", "accepted", "2026-09-24T12:00:00Z"))

    def test_same_instant_acceptance_corroboration_is_idempotent(self):
        result = self.observe(self.event("a", "accepted", "2026-09-20T10:00:00Z"),
                              self.event("b", "provider_completed", "2026-09-20T11:00:00Z"),
                              self.event("c", "accepted", "2026-09-20T06:00:00-04:00"))
        self.assertEqual(result["accepted_provider_count_24h"], 0)
        self.assertEqual(result["holding_execution_count"], 0)
        self.assertEqual(result["completed_not_merged_count"], 1)

    def test_creation_failure_then_new_request_requires_new_attempt(self):
        with self.assertRaises(ValueError):
            self.observe(self.event("a", "creation_failed", "2026-09-24T09:00:00Z", task=None),
                         self.event("b", "requested", "2026-09-24T10:00:00Z", task=None))

    def test_request_after_acceptance_cannot_reuse_attempt(self):
        with self.assertRaises(ValueError):
            self.observe(self.event("a", "accepted", "2026-09-24T09:00:00Z"),
                         self.event("b", "requested", "2026-09-24T10:00:00Z", task=None))

    def test_conflicting_request_timestamps_are_rejected(self):
        with self.assertRaises(ValueError):
            self.observe(self.event("a", "requested", "2026-09-24T09:00:00Z", task=None),
                         self.event("b", "requested", "2026-09-24T10:00:00Z", task=None))

    def test_canonical_events_preserve_source_timestamps_and_history(self):
        a = self.event("a", "accepted", "2026-09-24T06:00:00.123456789-04:00")
        b = self.event("b", "provider_completed", "2026-09-24T11:00:00Z")
        result = self.observe(b, a)
        self.assertEqual(result["coverage"], "partial")
        self.assertEqual(result["events"], [a, b])
        self.assertEqual(result["identities_summary"]["provider_history"]["t"], ["a", "b"])
        self.assertEqual(result["identities_summary"]["request_history"]["r"], ["a", "b"])

    def test_equal_time_unrelated_events_have_deterministic_output(self):
        a = self.event("b", "accepted", "2026-09-24T10:00:00Z", "tb", "rb", "wb")
        b = self.event("a", "accepted", "2026-09-24T10:00:00Z", "ta", "ra", "wa")
        left = self.observe(a, b)
        right = self.observe(b, a)
        self.assertEqual(json.dumps(left), json.dumps(right))
        self.assertEqual([e["evidence_id"] for e in left["events"]], ["a", "b"])

    def test_whitespace_identity_is_invalid(self):
        for field in ("evidence_id", "request_id", "work_key", "source_ref", "provider_task_id"):
            a = self.event("a", "accepted", "2026-09-24T10:00:00Z")
            a[field] = "   "
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.observe(a)

    def test_many_completed_deliveries_do_not_fill_provider_capacity(self):
        events = []
        for i in range(100):
            events.extend([self.event(f"a{i}", "accepted", "2026-09-24T10:00:00Z", f"t{i}", f"r{i}", f"w{i}"),
                           self.event(f"c{i}", "provider_completed", "2026-09-24T11:00:00Z", f"t{i}", f"r{i}", f"w{i}")])
        result = self.observe(*events)
        self.assertEqual(result["accepted_provider_count_24h"], 100)
        self.assertEqual(result["holding_execution_count"], 0)
        self.assertEqual(result["completed_not_merged_count"], 100)
        self.assertIsNone(result["account_wide_usage"])
        self.assertIsNone(result["max_concurrency"])

    def test_input_event_objects_are_not_mutated(self):
        a = self.event("a", "accepted", "2026-09-24T10:00:00Z")
        before = json.dumps(a)
        self.observe(a)
        self.assertEqual(json.dumps(a), before)
if __name__ == "__main__":
    unittest.main()
