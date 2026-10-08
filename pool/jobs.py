"""Durable queue: an error is a boundary, retry never starts the next item."""
import json
import subprocess
import time
from pathlib import Path

from .actions import ActionRequired
from .common import PoolError, atomic_json
from .processes import JobStopped, check_stop

RUN_MARKER = "HOMEBREW_POOL_RUN_STATE="


class SafePauseRequested(Exception):
    """The current safe unit finished; leave the durable queue at its checkpoint."""

    def __init__(self, completed_package=""):
        super().__init__("Safe pause requested")
        self.completed_package = completed_package


def pause_path(state):
    return Path(state) / "pause-request.json"


def pause_requested(state):
    return pause_path(state).is_file()


def request_pause(state):
    marker = pause_path(state)
    atomic_json(marker, {"schema": 1, "requested_at": int(time.time())})
    return marker


def clear_pause(state):
    marker = pause_path(state)
    try:
        marker.unlink()
    except FileNotFoundError:
        pass


def step(kind, name="", **options):
    return dict(kind=kind, name=name, status="pending", options=options)


class Job:
    def __init__(self, state):
        self.path = Path(state) / "job.json"
        self.data = json.loads(self.path.read_text()) if self.path.exists() else None
        if self.data and self.data.get("schema") != 1:
            raise PoolError("Unsupported saved job schema; preserve job.json and review it")

    def start(self, command, steps, options):
        if self.data and (self.remaining or self.failures or self.data["status"] == "action_required"):
            raise PoolError("A saved job needs Retry, Resume, or Cancel before starting a new operation")
        self.data = dict(schema=1, command=command, status="running", steps=steps,
                         options=options, reviewed=False)
        clear_pause(self.path.parent)
        self.save()

    @property
    def remaining(self):
        return [s for s in self.data["steps"] if s["status"] in ("pending", "running", "action")] if self.data else []

    @property
    def failures(self):
        return [s for s in self.data["steps"] if s["status"] == "failed"] if self.data else []

    def report(self):
        command = []
        if self.data:
            command = [self.data.get("command", "")]
            if command[0] == "install":
                target = next((s for s in self.data["steps"] if s["kind"] == "install"), None)
                if target:
                    command += ["--type", target["options"]["package_type"], target["name"]]
                    if target["options"]["mutable"]:
                        command += ["--allow-upstream-only-cask"]
        state = self.data["status"] if self.data else "idle"
        if state == "running" and pause_requested(self.path.parent):
            state = "pause_requested"
        return dict(schema=1, status=state,
                    failed_count=len(self.failures), remaining_count=len(self.remaining),
                    failures=[dict(name=s["name"] or s["kind"], kind=s["kind"], error=s.get("error", ""))
                              for s in self.failures],
                    current=self.data.get("current", "") if self.data else "",
                    command=self.data.get("command", "") if self.data else "", resume_command=command,
                    checkpoint=self.data.get("checkpoint") if self.data else None)

    def reconcile(self):
        """Normalize terminal records without discarding audit history or artifacts."""
        if not self.data:
            return False
        if not self.remaining and not self.failures and self.data.get("status") in (
                "paused", "paused_error", "stopped", "resolved", "completed"):
            changed = self.data.get("status") != "resolved" or bool(self.data.get("current"))
            self.data["status"] = "resolved"
            self.data["current"] = ""
            self.data["reviewed"] = True
            if changed:
                self.save()
            return changed
        return False

    def save(self):
        atomic_json(self.path, self.data)

    def safely_pause(self, item=None, completed_package=""):
        next_step = ""
        if item is not None:
            next_step = item.get("name") or item.get("kind", "")
        elif self.remaining:
            next_step = self.remaining[0].get("name") or self.remaining[0].get("kind", "")
        self.data["status"] = "safely_paused"
        self.data["active_package"] = ""
        self.data["current"] = completed_package or next_step
        self.data["checkpoint"] = {
            "schema": 1,
            "phase": "safe_boundary",
            "completed_package": completed_package,
            "next_step": next_step,
            "publication": self.data.get("publication", {"state": "not-applicable"}),
            "saved_at": int(time.time()),
        }
        self.save()
        clear_pause(self.path.parent)

    def emit(self):
        print(RUN_MARKER + json.dumps(self.report(), sort_keys=True), flush=True)

    def resolve(self, cancel=False):
        if not self.data:
            return
        if not cancel and any(s["kind"] in ("preflight", "update", "discover") for s in self.failures):
            raise PoolError("Retry the failed prerequisite or Cancel the saved job")
        for item in self.data["steps"]:
            if item["status"] == "failed" or (cancel and item["status"] in ("pending", "running", "action")):
                item["status"] = "resolved" if not cancel else "cancelled"
        self.data["reviewed"] = True
        self.data["status"] = "stopped" if self.remaining else "resolved"
        self.save()

    def run(self, execute, mode="resume", skip=()):
        if not self.data:
            raise PoolError("No saved queue to resume")
        if mode != "retry" and any(s["kind"] in ("preflight", "update", "discover") for s in self.failures):
            self.emit()
            raise PoolError("Retry the failed prerequisite before resuming packages")
        if self.data["status"] == "running":
            # Under the exclusive job lock a running record is a previous crash.
            for item in self.data["steps"]:
                if item["status"] == "running":
                    item["status"] = "pending"
                    item["interrupted"] = True
        skipped = set(skip)
        for item in self.data["steps"]:
            if item["name"] in skipped and item["status"] in ("pending", "action", "failed"):
                item["status"] = "skipped"
        selected = {"failed"} if mode == "retry" else {"pending", "action", "running"}
        if self.data["status"] != "running":
            clear_pause(self.path.parent)
        self.data["status"] = "running"
        self.data.pop("checkpoint", None)
        self.save()
        try:
            # Discovery may insert package steps while this loop is running.
            for item in self.data["steps"]:
                if item["name"] in skipped and item["status"] in ("pending", "action", "failed"):
                    item["status"] = "skipped"
                    self.save()
                if item["status"] not in selected:
                    continue
                if pause_requested(self.path.parent):
                    self.safely_pause(item)
                    return
                check_stop()
                self.data["current"] = item["name"] or item["kind"]
                item["status"] = "running"
                self.save()
                try:
                    execute(item, self)
                    check_stop()
                except SafePauseRequested as pause:
                    item["status"] = "pending" if item["status"] == "running" else item["status"]
                    self.safely_pause(item, pause.completed_package)
                    return
                except ActionRequired:
                    item["status"] = "action"
                    self.data["status"] = "action_required"
                    self.save()
                    raise
                except JobStopped as error:
                    item["status"] = "pending" if mode != "retry" else "failed"
                    item["interrupted"] = True
                    if getattr(error, "pool_failed_package", None):
                        item["failed_package"] = error.pool_failed_package
                    raise
                except (PoolError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
                    item["status"] = "failed"
                    detail = str(error)
                    if isinstance(error, subprocess.CalledProcessError):
                        detail += "\n" + (error.output or "") + (error.stderr or "")
                    item["error"] = detail[-8000:]
                    if getattr(error, "pool_failed_package", None):
                        item["failed_package"] = error.pool_failed_package
                    self.data["status"] = "paused_error"
                    self.data["reviewed"] = False
                    self.save()
                    raise PoolError("Paused — Error: " + self.data["current"] + ": " + str(error)) from error
                item["status"] = "done"
                item.pop("error", None)
                item.pop("interrupted", None)
                self.data["active_package"] = ""
                self.save()
                if pause_requested(self.path.parent):
                    self.safely_pause(completed_package=item["name"] or item["kind"])
                    return
            self.data["current"] = ""
            self.data["status"] = ("paused_error" if self.failures else
                                   "paused" if self.remaining else "completed")
            self.save()
        except JobStopped:
            self.data["status"] = "stopped"
            self.save()
            raise
        finally:
            self.emit()
