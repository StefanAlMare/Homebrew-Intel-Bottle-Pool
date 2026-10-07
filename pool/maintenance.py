"""Explicit user-launched maintenance commands with serialization and safe stdin."""
import os
import re
import shlex
import subprocess

from .client import local_lock, local_read_lock
from .common import PoolError
from .processes import run_command


READ_ONLY_BREW = {
    "doctor", "outdated", "missing", "list", "info", "config", "environment",
    "--version", "--prefix", "--cellar", "--cache", "linkage", "deps", "uses",
}


def command_is_read_only(command):
    try:
        words = shlex.split(command)
    except ValueError as error:
        raise PoolError("Invalid command quoting: " + str(error)) from error
    if not words:
        raise PoolError("Enter a command")
    executable = os.path.basename(words[0])
    return executable == "brew" and len(words) > 1 and words[1] in READ_ONLY_BREW


def needs_destructive_confirmation(command):
    return bool(re.search(
        r"(^|[;&|]\s*)(?:sudo\s+)?(?:rm|rmdir|diskutil|dd|mkfs|shutdown|reboot)\b|"
        r"\bbrew\s+(?:uninstall|remove|cleanup|autoremove)\b|\bgit\s+reset\s+--hard\b",
        command, re.I,
    ))


def _administrator_command(command, env):
    # Apple owns the credential dialog.  The command text is passed as AppleScript
    # data; the app never reads or stores an administrator password.
    escaped = command.replace("\\", "\\\\").replace('"', '\\"')
    script = 'do shell script "' + escaped + '" with administrator privileges'
    return run_command(["/usr/bin/osascript", "-e", script], env=env, stream=True)


def run_maintenance(command, state, *, administrator=False, confirmed=False, env=None):
    if any(character in command for character in ("\x00", "\r", "\n")):
        raise PoolError("Run one explicit command at a time")
    if needs_destructive_confirmation(command) and not confirmed:
        raise PoolError("Destructive command requires GUI confirmation")
    environment = dict(os.environ if env is None else env)
    environment.pop("HOMEBREW_POOL_TOKEN", None)
    environment["HOMEBREW_NO_ASK"] = "1"

    def execute():
        if administrator:
            return _administrator_command(command, environment)
        return run_command(["/bin/zsh", "-lc", command], env=environment, stream=True)

    lock = local_read_lock if command_is_read_only(command) and not administrator else local_lock
    with lock(state):
        return execute()
