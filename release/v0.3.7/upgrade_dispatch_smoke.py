"""Exercise the real GUI with a disposable interpreter stub; no Brew/Git/repos."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
FAKE_PYTHON = r'''#!/usr/bin/python3
import json, pathlib, sys
args=sys.argv[1:]
config=pathlib.Path(args[args.index('--config')+1])
root=config.parents[2]
assert (root/'test-fixture').is_file()
flag='--authorize-repository-access'
if 'status' in args:
 assert flag not in args
 print(json.dumps(dict(connected=True,spool_entries=0,state='healthy',job=None)))
elif 'upgrade' in args:
 assert args.count(flag)==1 and args.index(flag)<args.index('upgrade'), repr(args)
 pending=root/'pending-run.json'
 assert flag not in pending.read_text()
 with (root/'upgrade-calls.jsonl').open('a') as f: f.write(json.dumps(args)+'\n')
 if (root/'fail-upgrade').exists():
  print('Error: fixture update failure',file=sys.stderr);sys.exit(1)
 print('HOMEBREW_POOL_RUN_STATE='+json.dumps(dict(command='upgrade',current='',failed_count=0,remaining_count=0,failures=[],status='completed')))
else:
 raise SystemExit('unexpected fixture invocation: '+repr(args))
'''


def main():
    app = ROOT / "dist/Homebrew Pool.app/Contents/MacOS/HomebrewPoolMenu"
    with tempfile.TemporaryDirectory(prefix="pool-upgrade-dispatch-") as temporary:
        root = Path(temporary).resolve()
        (root / "test-fixture").touch()
        python = root / "fixture-python"
        python.write_text(FAKE_PYTHON)
        python.chmod(0o755)
        config = root / "config/intel-bottle-pool/config.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"python": str(python), "fixture": True}))
        env = dict(os.environ)
        for key in ("HOMEBREW_POOL_APP_ROOT", "HOMEBREW_POOL_TEST_ROOT", "POOL_FIXTURE_ROOT", "XDG_CONFIG_HOME"):
            env.pop(key, None)
        env.update(HOMEBREW_POOL_TEST_ROOT=str(root), POOL_PYTHON=str(python))
        result = subprocess.run([str(app), "--upgrade-dispatch-smoke", str(root)], env=env,
                                capture_output=True, text=True, timeout=40)
        report_path = root / "upgrade-dispatch-smoke.json"
        if result.returncode or not report_path.is_file():
            log = (root / "logs/agent.log").read_text() if (root / "logs/agent.log").is_file() else "No fixture log"
            raise RuntimeError(result.stdout + result.stderr + log)
        report = json.loads(report_path.read_text())
        assert all(report.values())
        invocations = [json.loads(x) for x in (root / "upgrade-calls.jsonl").read_text().splitlines()]
        assert len(invocations) == 2
        report.update(approved_child_invocations=2, repositories_used=False, homebrew_executed=False)
        (ROOT / "upgrade-dispatch-smoke.json").write_text(json.dumps(report, indent=2) + "\n")
        (ROOT / "upgrade-dispatch-agent.log").write_bytes((root / "logs/agent.log").read_bytes())
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
