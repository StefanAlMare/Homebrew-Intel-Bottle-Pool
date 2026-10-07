"""Cancellable subprocesses with isolated groups and a bounded shutdown."""
import contextlib
import os
import selectors
import signal
import subprocess
import sys
import threading
import time


class JobStopped(Exception):
    pass


STOP = threading.Event()


def check_stop():
    if STOP.is_set():
        raise JobStopped("Stopped by user; queue retained")


def install_stop_handlers():
    def request_stop(signum, frame):
        STOP.set()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, request_stop)


def _signal_group(pid, signum):
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pid, signum)


def _group_exists(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _process_table():
    try:
        text = subprocess.check_output(["/bin/ps", "-axo", "pid=,ppid=,pgid=,lstart="],
                                       text=True, stderr=subprocess.DEVNULL, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return {}
    records = {}
    for line in text.splitlines():
        fields = line.split(None, 3)
        if len(fields) == 4:
            records[int(fields[0])] = (int(fields[1]), int(fields[2]), fields[3])
    return records


def _remember_children(root, tracked, table):
    parents = {root} | {pid for pid, born in tracked.items() if pid in table and table[pid][2] == born}
    while True:
        added = {pid for pid, (parent, group, born) in table.items() if parent in parents and pid not in parents}
        if not added:
            break
        for pid in added:
            tracked[pid] = table[pid][2]
        parents.update(added)


def _signal_children(tracked, signum, table):
    for pid, born in tracked.items():
        if pid in table and table[pid][2] == born:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signum)


def _tracked_exists(tracked):
    table = _process_table()
    return any(pid in table and table[pid][2] == born for pid, born in tracked.items())


def run_command(argv, *, env=None, cwd=None, stream=False, interrupt_timeout=8, terminate_timeout=4):
    """All Brew/Git/producer children inherit a private session, never the GUI's."""
    check_stop()
    process = subprocess.Popen(argv, env=env, cwd=cwd, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                               start_new_session=True)
    if os.environ.get("HOMEBREW_POOL_GUI") == "1":
        print("HOMEBREW_POOL_PROCESS_GROUP=" + str(process.pid), flush=True)
    stdout, stderr = [], []
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, (stdout, sys.stdout))
    selector.register(process.stderr, selectors.EVENT_READ, (stderr, sys.stderr))
    stopping = None
    stage = 0
    tracked = {}
    checked_at = time.monotonic()
    groups = {process.pid}
    try:
        while selector.get_map() or process.poll() is None or (stopping is not None and (_group_exists(process.pid) or _tracked_exists(tracked))):
            if STOP.is_set() and stopping is None:
                table = _process_table()
                _remember_children(process.pid, tracked, table)
                for pid, born in tracked.items():
                    if pid in table and table[pid][1] == pid and pid not in groups:
                        groups.add(pid)
                        if os.environ.get("HOMEBREW_POOL_GUI") == "1":
                            print("HOMEBREW_POOL_PROCESS_GROUP=" + str(pid), flush=True)
                stopping = time.monotonic()
                _signal_group(process.pid, signal.SIGINT)
                _signal_children(tracked, signal.SIGINT, table)
            elif time.monotonic() - checked_at > 0.5:
                table = _process_table()
                _remember_children(process.pid, tracked, table)
                checked_at = time.monotonic()
                for pid, born in tracked.items():
                    if pid in table and table[pid][1] == pid and pid not in groups:
                        groups.add(pid)
                        if os.environ.get("HOMEBREW_POOL_GUI") == "1":
                            print("HOMEBREW_POOL_PROCESS_GROUP=" + str(pid), flush=True)
            if stopping is not None:
                elapsed = time.monotonic() - stopping
                if stage == 0 and elapsed >= interrupt_timeout:
                    _signal_group(process.pid, signal.SIGTERM)
                    _signal_children(tracked, signal.SIGTERM, _process_table())
                    stage = 1
                if stage == 1 and elapsed >= interrupt_timeout + terminate_timeout:
                    _signal_group(process.pid, signal.SIGKILL)
                    _signal_children(tracked, signal.SIGKILL, _process_table())
                    stage = 2
                # A reparented zombie can keep a group visible briefly. All members
                # have received KILL; do not let an unreaped zombie block the UI.
                if stage == 2 and elapsed >= interrupt_timeout + terminate_timeout + 2:
                    break
            for key, _ in selector.select(0.1):
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                output, target = key.data
                output.append(data)
                if stream:
                    while len(output) > 1 and sum(map(len, output)) > 262144:
                        output.pop(0)
                    target.write(data.decode("utf-8", errors="replace"))
                    target.flush()
        process.wait()
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
        if process.poll() is None:
            _signal_group(process.pid, signal.SIGKILL)
            process.wait()
        if os.environ.get("HOMEBREW_POOL_GUI") == "1":
            for group in groups:
                print("HOMEBREW_POOL_PROCESS_GROUP_DONE=" + str(group), flush=True)
    out = b"".join(stdout).decode("utf-8", errors="replace")
    err = b"".join(stderr).decode("utf-8", errors="replace")
    check_stop()
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, argv, output=out, stderr=err)
    if not stream and err:
        print(err, end="" if err.endswith("\n") else "\n", file=sys.stderr, flush=True)
    return out.strip()
