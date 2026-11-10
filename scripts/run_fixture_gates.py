"""Run exactly the fixture catalog selectors and fail on missing/skipped tests."""
import json
from pathlib import Path
import unittest


def main():
    manifest=json.loads(Path('scripts/fixtures/release/manifest.json').read_text())
    names=list(dict.fromkeys(name for case in manifest['cases'] for name in case['tests']))
    suite=unittest.defaultTestLoader.loadTestsFromNames(names)
    root=Path('data/release-gates');root.mkdir(parents=True,exist_ok=True)
    with (root/'fixtures.log').open('w',encoding='utf-8') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    report={'fixture_version':manifest['version'],'case_categories':len(manifest['cases']),'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'passed':result.wasSuccessful() and not result.skipped,'selectors':names,'limits':manifest['limits']}
    (root/'fixtures.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))
    raise SystemExit(0 if report['passed'] else 1)


if __name__=='__main__':main()
