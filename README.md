# ops-witness — Unified Audit Surface

**Bookend log + cross-plane witness.**

> **Status**: **Parked (Non-shippable)**
> `ops-witness` is an internal audit surface and reconciliation layer for tri-plane scheduler logs. It is not a product-facing component and carries no deployment or end-user release artifact path.

This repository is the **reconciliation layer** for the tri-plane scheduler. It does not run
scheduled work itself (beyond its own keepalive) — it *watches* the planes that do, and
records whether they actually fired and finished.

Where [`ops`](https://github.com/a-organvm/ops) is plane (i) — the always-on GitHub Actions
cron backbone that emits work and bookends — `ops-witness` reads those bookends back and
flags any expected run that left a gap. It is the single place to answer the question
**"did everything that should have run, run?"**

---

## The three-plane model (recap)

| Plane | Carrier | Liveness |
|-------|---------|----------|
| **(i) GitHub cron** | GitHub Actions `schedule:` ([`ops`](https://github.com/a-organvm/ops)) | Always-on (cloud) |
| **(ii) Local dispatcher** | machine-local cron / launchd | Awake-only (host) |
| **(iii) claude.ai routines** | scheduled claude.ai agent routines | Account-resident |

No single plane is trusted to attest to its own liveness — a plane that is down cannot
report that it is down. `ops-witness` is the **independent observer**: it reads the durable
bookend artifacts the planes leave behind and reconciles them against what *should* have
happened.

---

## The bookend contract

Every scheduled job across the planes writes a `start` line when it begins and an `end` line
when it finishes, appended to a daily TSV in this shared shape:

```
ts<TAB>job<TAB>-<TAB>-<TAB>start|end<TAB>status
```

The witness uses these to distinguish three states per job per day:

| Observed | Meaning |
|----------|---------|
| `start` **and** `end` | healthy run |
| `start` **without** `end` | fired but died mid-run — **flag** |
| neither | never fired — **flag** |

**A silent gap is a failure, not a non-event.** The whole point of the witness is that an
absence is information.

---

## What the weekly witness does

`weekly-witness.yml` runs once a week and:

1. Reads this repo's `audit/` directory (its own running record).
2. Reads the `ops` repo's `bookends/` directory via the GitHub REST API (public, no token
   beyond `GITHUB_TOKEN`).
3. For each of the last 7 days, checks whether `org-hygiene-report` produced a paired
   bookend (a `start` and a matching `end`). Any day missing that pairing is flagged.
4. Writes a witness report to `audit/YYYY-MM-DD-witness.md` and commits it (`[skip ci]`).

The witness flags both **missing-entirely** days and **start-without-end** days, so a job
that crashed is as visible as a job that never ran.

---

## Keepalive

Like `ops`, this repo carries its own `keepalive.yml` (weekly, Mondays 06:11 UTC) to keep
the repo active past GitHub's 60-day scheduled-workflow auto-disable threshold and to
re-enable any workflow GitHub auto-disabled for inactivity. The witness watching the planes
must itself stay alive — the keepalive is its dead-man's-switch reset.

---

## The stagger rule

Never schedule on the hour. House offsets are **:11, :17, :23, :36, :49**; no two workflows
share a minute.

| Workflow | Cron | When (UTC) |
|----------|------|------------|
| `weekly-witness` | `49 12 * * 0` | Sundays 12:49 |
| `keepalive` | `11 6 * * 1` | Mondays 06:11 |

---

## Nothing here is deleted

Witness reports accumulate in `audit/` and are never pruned — the historical record of which
days were healthy and which were flagged is the asset. Workflows are disabled, never
removed. Archive, disable, or rename-with-breadcrumb — never delete.

---

## Layout

```
.
├── README.md                            # this charter
├── .keepalive                           # touched weekly by keepalive.yml
├── audit/                               # YYYY-MM-DD-witness.md (committed with [skip ci])
│   └── .keep
└── .github/workflows/
    ├── keepalive.yml                    # weekly: touch + re-enable auto-disabled workflows
    └── weekly-witness.yml               # weekly: reconcile ops bookends, flag gaps
```

---

## Sibling

- [`ops`](https://github.com/a-organvm/ops) — plane (i), the always-on GitHub Actions cron
  backbone whose `bookends/` this witness reads.
