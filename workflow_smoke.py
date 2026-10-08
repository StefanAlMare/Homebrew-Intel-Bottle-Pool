"""Exercise the compiled GUI with a disposable Brew fixture and real child processes."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

FIXTURE = r'''#!/usr/bin/env python3
import hashlib,json,os,pathlib,subprocess,sys,time
root=pathlib.Path(os.environ["POOL_FIXTURE_ROOT"])
args=sys.argv[1:]
payload=b"isolated official bottle fixture"
if args == ["--prefix"]: print(root/"prefix")
elif args == ["--cellar"]: print(root/"prefix/Cellar")
elif args[0] == "--cache": print(root/"cache/alpha.bottle.tar.gz" if len(args)>1 else root/"cache")
elif args[0] == "--repository": print(root/"repo")
elif args[0] == "tap": print("homebrew/core")
elif args[0] == "outdated": print(json.dumps({"formulae":[{"name":"alpha"},{"name":"beta"}],"casks":[]}))
elif args[0] == "deps": print("Warning: `brew deps` is not the actual runtime dependencies",file=sys.stderr)
elif args[0] == "info":
    name=args[-1]
    if name == "alpha" and (root/"fail").exists():
        print("compiler fixture error",file=sys.stderr); sys.exit(1)
    if name == "beta": (root/"beta-visited").touch()
    if name == "alpha" and (root/"block").exists():
        child="import pathlib,sys,time;\ntry:\n pathlib.Path(sys.argv[2]).touch(); time.sleep(60)\nexcept KeyboardInterrupt: pathlib.Path(sys.argv[1]).write_text('clean exit')"
        p=subprocess.Popen([sys.executable,"-c",child,str(root/"stop-clean"),str(root/"child-ready")],start_new_session=True)
        while not (root/"child-ready").exists(): time.sleep(0.01)
        (root/"child-pid").write_text(str(p.pid))
        try: time.sleep(60)
        except KeyboardInterrupt: p.wait(); sys.exit(0)
    installed=name == "beta" or (root/"installed-alpha").exists()
    if installed:
        recipe=root/"prefix/Cellar"/name/"2026-09-25/.brew"/(name+".rb")
        recipe.parent.mkdir(parents=True,exist_ok=True); recipe.write_text("fixture "+name+" recipe")
    record={"name":name,"full_name":name,"tap":"homebrew/core","versions":{"stable":"2026-09-25"},
        "revision":0,"version_scheme":0,"ruby_source_checksum":{"sha256":"a"*64},
        "outdated":not installed,"installed":[{"version":"2026-09-25","used_options":[]}] if installed else [],
        "bottle":{"stable":{"rebuild":0,"files":{"tahoe":{"cellar":":any","sha256":hashlib.sha256(payload).hexdigest()}}}}}
    print(json.dumps({"formulae":[record]}))
elif args[0] == "fetch":
    (root/"cache").mkdir(exist_ok=True); (root/"cache/alpha.bottle.tar.gz").write_bytes(payload)
elif args[0] == "install":
    if (root/"safe-pause").exists():
        (root/"safe-install-ready").touch()
        while not (root/"safe-install-release").exists(): time.sleep(0.02)
    recipe=root/"prefix/Cellar/alpha/2026-09-25/.brew/alpha.rb"
    recipe.parent.mkdir(parents=True,exist_ok=True); recipe.write_text("fixture alpha recipe")
    (root/"installed-alpha").touch()
elif args[0] in ("update","missing"): pass
else: sys.exit("unhandled fixture command: "+repr(args))
'''


def main():
    app = ROOT / "dist/Homebrew Pool.app/Contents/MacOS/HomebrewPoolMenu"
    with tempfile.TemporaryDirectory(prefix="pool-gui-workflow-") as temporary:
        root = Path(temporary).resolve()
        (root / "test-fixture").touch()
        (root / "fail").touch()
        repo = root / "repo"
        (repo / "bin").mkdir(parents=True)
        script = repo / "bin/brew"
        script.write_text(FIXTURE)
        script.chmod(0o755)
        subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "bin/brew"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "Fixture"], check=True)
        origin = root / "origin.git"
        subprocess.run(["git", "clone", "--bare", "--quiet", str(repo), str(origin)], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(origin)], check=True)
        subprocess.run(["git", "-C", str(repo), "push", "--quiet", "-u", "origin", "HEAD"], check=True)
        (root / "prefix/bin").mkdir(parents=True)
        brew = root / "prefix/bin/brew"
        brew.symlink_to(script)
        (root / "token").write_text("isolated-fixture-token")
        config = root / "config/intel-bottle-pool/config.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps(dict(url="http://127.0.0.1:9", token_file=str(root / "token"),
            state_dir=str(root / "state"), brew=str(brew), timeout=0.1, artifacts=[], python=sys.executable)))
        support = root / "support"
        support.mkdir()
        # Exact reboot/cold-launch regression: GUI cache says stopped while the
        # authoritative backend has no job.json and therefore reports idle.
        (support / "pending-run.json").write_text(json.dumps({
            "state": {"status": "stopped", "failed_count": 0, "remaining_count": 0,
                      "failures": [], "current": "", "command": "upgrade",
                      "resume_command": ["upgrade"]},
            "command": ["upgrade"], "activity": "Busy/Resuming"
        }))
        env = dict(os.environ, XDG_CONFIG_HOME=str(root / "config"), POOL_PYTHON=sys.executable,
                   POOL_FIXTURE_ROOT=str(root), HOMEBREW_NO_AUTO_UPDATE="1")
        result = subprocess.run([str(app), "--workflow-smoke", str(root)], env=env,
                                capture_output=True, text=True, timeout=140)
        if result.returncode or not (root / "workflow-smoke.json").exists():
            print((root / "agent.log").read_text() if (root / "agent.log").exists() else "No agent log")
            raise RuntimeError("GUI workflow failed: " + result.stdout + result.stderr)
        report = json.loads((root / "workflow-smoke.json").read_text())
        assert all(report.values())
        validation = ROOT / "validation"
        validation.mkdir(exist_ok=True)
        (validation / "workflow-smoke.json").write_text(json.dumps(report, indent=2) + "\n")
        (validation / "workflow-agent.log").write_bytes((root / "agent.log").read_bytes())
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
