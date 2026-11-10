# Release fixture catalog

`manifest.json` maps the requested edge cases to executable assertions. Source factories and fixed expectations live in the referenced tests; file/storage/DB fixtures are generated and cleaned up in isolated workspaces. No real Tally import, provider call or outgoing message is used.

Run the bounded catalog:

```powershell
docker compose exec -T -e LITELLM_LOCAL_MODEL_COST_MAP=True app python -m scripts.run_fixture_gates
```

The runner fails for missing selectors, failures, errors or skips and saves `data/release-gates/fixtures.json` and `fixtures.log`. The full synthetic regression runner also includes the new source-edge-case module.

The full runner records Python source fingerprints before/after execution and refuses a passing result if source changes during the run. Run against stable code. Customer helper queue fixtures hold their own synthetic endpoint lock so the running sync worker cannot inject unrelated read jobs into the contract assertion.

Coverage includes multiple lines with mixed intra/inter-state rates, line/header discounts, disclosed round-off, duplicate bytes and cross-format invoice identity, severe real local-OCR degradation, source pagination gaps, similar suppliers, wrong totals, untrusted document/model instructions, stale concurrent edits and workspace/user isolation.

Source pagination guard reads explicit `Page n of m` / `Page n / m` markers. Missing, repeated or out-of-order page evidence stays in the immutable source result, survives model omission and draft edits, and blocks preview. Automation's independent original-source read also sees the warning. Without printed pagination or other evidence, a physically absent page cannot be detected reliably; the app does not pretend otherwise.

The blur fixture severely downsamples and blurs a generated invoice, then exercises actual local OCR via the worker and verifies a visible failure with no fabricated draft/action. It does not establish universal thresholds for moderately blurred or varied phone photos.

The cross-format duplicate fixture supplies known extracted identity to isolate duplicate protection; actual clean PNG/JPEG OCR accuracy is measured separately by the unchanged Day 9 golden corpus. The malicious-input fixture appends hostile prose to an actual PDF and injects bogus approval/status/action/workspace/tool fields into structured extraction output. Only reviewable draft fields survive; no action is approved/dispatched. This validates authority boundaries, not universal cloud-model prompt-injection resistance.
