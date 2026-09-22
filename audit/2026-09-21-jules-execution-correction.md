# Jules execution-path correction — 2026-09-21

Owner: 4444J99/limen#2680. Companion implementation: 4444J99/limen#2687. Credential custody: Limen #320.

## Verified source defect

At ops-witness main 6dfdf2fa1d19381662610201bc987d9060c0c233, scripts/jules-orchestrator.mjs generates proposed technical debt from repository names and creates jules-labelled issues during the discovery branch. Its two dispatch-hour branches only log Running Jules Dispatch Batch and a Future expansion comment. The script has no actual capacity reconciliation, accepted-session identity, complete receipt handling or authorized integration cycle. A printed dispatch banner is not a dispatch.

The old implementation also interpolates model-authored titles into a shell command. The replacement makes no LLM request, shell interpolation, issue mutation or PR mutation. It is a read-only witness, consistent with this repository's documented role; Limen retains execution and custody.

## Replacement and provenance

The legacy filename remains an entry point so historical invocation paths are not silently abandoned. It executes only the exact SHA-256-verified bytes of Limen's read-only API observer, pinned to a concrete source commit in the workflow. An isolated Python subprocess receives the Jules key via environment, never argv. Output is a strict aggregate whitelist. Missing or malformed evidence, timeout, inconsistent counts and missing credentials exit nonzero with null counts. Provider-completed is explicitly not merged. The witness writes a start/end result envelope and CI stores it as an artifact; it does not claim a Markdown filename is an immutable receipt.

The historical four UTC workflow opportunities are retained as diagnostic observations, NOT the user's seven Eastern dispatch windows. No second dispatcher is introduced. Those actual execution cadences must be reconciled and activated through the existing Limen scheduler/broker after provider authentication and asynchronous-lifecycle admission are verified. No native Gemini timer was edited by this source PR.

Existing historical audit files are preserved unchanged. Their earlier totals and merge claims must not be treated as provider truth until matched to actual session IDs, target PR states and accepted-branch evidence. This correction does not claim those historical files were deleted or repaired, or that a missing read means zero activity.

## Verification and activation

Twelve local Node tests passed. An actual invocation of the pinned observer in the Chat container returned jules_api_key_missing_or_invalid, exit 2 and null usage. The companion Limen workflow also ran on a hosted runner: 65 unit tests passed against the actual framework, but the account probe returned the same unavailable-key classification. That says nothing about key presence in other runtimes.

Store the existing Jules-specific API key in approved secret custody, bind JULES_API_KEY to the real executor and this witness, and re-run the read-only probe. A Gemini API key or GitHub token cannot replace it. Do not put literal secrets in source, chat, or receipts. No task has been launched by this repair.

Primary API: https://developers.google.com/jules/api
