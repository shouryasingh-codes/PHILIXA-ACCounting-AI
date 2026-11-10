"""Render reproducible evidence notes, preserving unrun/failed cases."""
import json
from pathlib import Path

def main():
    offline=json.loads(Path('data/agent-prompt-evaluation.json').read_text(encoding='utf-8'))
    live_path=Path('data/agent-prompt-evaluation-live.json')
    live=json.loads(live_path.read_text(encoding='utf-8')) if live_path.exists() else None
    lines=['# Agent prompt evaluation — 4 November 2026','',
        'Scope: synthetic single next-decision comparisons. No domain tools or Tally writes executed.',
        'This is not a real-accountant accuracy or time-saving study.','',
        '## Offline contract replay','',
        '12 held-out fixture replays validate schema/grounding/grader contracts under both prompt packages.',
        'Both replays passing does not measure model intelligence. No provider calls were made.',
        'Dataset SHA256: '+offline['dataset_sha256'], '']
    if live:
        rows=[r for r in live['rows'] if 'decision' in r]
        paired=set.intersection(*[{r['case_id'] for r in rows if r['version']==v} for v in ('baseline','v2')])
        lines+=['## Live provider decisions','',f'Completed paired scenarios: {len(paired)} / 12.',
            'Provider: existing Groq GPT-OSS 20B, confirmed free-tier configuration; temperature 0, 2,048 completion ceiling.',
            'Prompts were frozen before evaluation; no held-out tuning. Completed calls are not repeated on resume.','']
        for version in ('baseline','v2'):
            subset=[r for r in rows if r['version']==version and r['case_id'] in paired]
            used=[r['usage'] for r in subset if r.get('usage')]
            lines += [f"- {version}: {sum(r['passed'] for r in subset)} / {len(subset)} paired next-decision checks passed; "
                f"prompt tokens {sum(u.get('prompt_tokens',0) for u in used)}, completion tokens {sum(u.get('completion_tokens',0) for u in used)}."]
        lines+=['','Failures are preserved:']
        failures=[r for r in rows if not r.get('passed')]
        lines += ['- '+r['case_id']+' / '+r['version']+': '+', '.join(r.get('errors',[])) for r in failures] or ['- No failed checks among evaluated decisions.']
        lines+=['','Rubric limits: unit checks compare explicit source values; a singular/plural rewrite can fail this extraction check even where a separately validated native alias exists.',
            'The offline-snapshot rubric demands answering the supplied saved snapshot. Proposing a fresh read instead fails that preference; it is not proof of fabricated stock or an unauthorised write.']
        blocked=[r for r in live['rows'] if 'decision' not in r]
        if blocked:
            lines+=['','Pending/unverified:']+['- '+r['case_id']+' / '+r['version']+': '+r.get('reason',r.get('error_type','not run')) for r in blocked]
        lines+=['',f"Recorded admission wait events: {len(live.get('wait_events',[]))}. See JSON for provider reset times.",
            'Actual provider usage and latency are stored per decision; actual billed cost is unavailable.',
            'No percentage time savings or token savings is asserted. Offline reservation estimates include output headroom and do not equal actual usage.','']
    lines+=['## Separate integration checks','',
        'Prompt/model/runtime, task selection, situation routing and UI regression suites passed.',
        'GST, duplicates, receipt linkage, stock reads, quota and process recovery were tested with scoped synthetic fixtures/mocked transports.',
        'One context-refresh regression exposed by expanded worker tests was repaired; provider errors remain visible above stale domain cards.',
        'Some existing async PostgreSQL tests emit connection ResourceWarnings during teardown.','',
        '## Rollout limitations','',
        'Default prompt version remains baseline. v2 is opt-in through PHILIXA_AGENT_PROMPT_VERSION; rollback requires setting baseline.',
        'Fresh browser visual/reload acceptance was attempted but the IAB tool returned browser.user is unavailable.',
        'Live Tally stock timeout and broad real-world accounting/agent reliability remain unverified work.',
        'No automation policy or real-company posting gate was enabled.','',
        'Reproduce: python -m scripts.evaluate_agent_prompts; optional --live / --live --resume; then python -m scripts.render_agent_prompt_report.']
    target=Path('AGENT_PROMPT_EVALUATION_REPORT.md');target.write_text('\n'.join(lines)+'\n',encoding='utf-8');print(target)

if __name__=='__main__':main()
