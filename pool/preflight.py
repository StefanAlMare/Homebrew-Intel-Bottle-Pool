"""Conservative Homebrew migrations; no resets, deletion, or guessed tap URLs."""
import os
import re
import subprocess
from pathlib import Path

from .actions import ActionRequired
from .common import PoolError
from .processes import run_command

OFFICIAL = {
    "brew": "https://github.com/Homebrew/brew",
    "homebrew/core": "https://github.com/Homebrew/homebrew-core",
    "homebrew/cask": "https://github.com/Homebrew/homebrew-cask",
}
LEGACY = {
    "brew": {"homebrew/brew", "homebrew/homebrew", "mxcl/homebrew", "linuxbrew/brew"},
    "homebrew/core": {"homebrew/homebrew-core", "linuxbrew/homebrew-core", "homebrew/linuxbrew-core"},
    "homebrew/cask": {"homebrew/homebrew-cask", "caskroom/homebrew-cask", "phinze/homebrew-cask"},
}


def canonical_official(name, url):
    """Only exact, allowlisted GitHub paths are migrations. Custom mirrors survive."""
    match = re.fullmatch(r"(?:https?://github\.com/|git://github\.com/|ssh://git@github\.com/|git@github\.com:)([^?#]+)", url, re.I)
    if match:
        path = match[1].rstrip("/").removesuffix(".git").lower()
        if path in LEGACY.get(name, ()):
            return OFFICIAL[name]
    return url


class Preflight:
    def __init__(self, brew):
        self.brew = brew
        for key, name in (("HOMEBREW_BREW_GIT_REMOTE", "brew"), ("HOMEBREW_CORE_GIT_REMOTE", "homebrew/core")):
            if brew.env.get(key):
                normalized = canonical_official(name, brew.env[key])
                if normalized != brew.env[key]:
                    brew.env[key] = normalized
                    print("Self-heal: normalized inherited " + key, flush=True)
        self.env = dict(brew.env, GIT_TERMINAL_PROMPT="0")

    def official_url(self, name):
        key = {"brew": "HOMEBREW_BREW_GIT_REMOTE", "homebrew/core": "HOMEBREW_CORE_GIT_REMOTE"}.get(name)
        return self.env.get(key) or OFFICIAL[name]

    def git(self, repo, *args):
        return run_command(["/usr/bin/git", "-C", str(repo), *args], env=self.env)

    def optional(self, repo, *args):
        try:
            return self.git(repo, *args)
        except subprocess.CalledProcessError as error:
            if error.returncode == 1:
                return ""
            raise

    def unsafe(self, name, reason, detail=""):
        raise ActionRequired(reason, category="unsafe_tap", subject=name, detail=detail,
                             choices=[{"id": "continue", "label": "Continue after repair"},
                                      {"id": "cancel", "label": "Cancel"}])

    def guard(self, repo, name):
        if not repo.is_dir() or not (repo / ".git").exists():
            self.unsafe(name, "Repository is not a Git checkout; automatic replacement is unsafe.")
        if self.git(repo, "rev-parse", "--show-toplevel") != str(repo.resolve()):
            self.unsafe(name, "Repository path points inside another checkout.")
        dirty = self.git(repo, "status", "--porcelain")
        if dirty:
            self.unsafe(name, "The modified checkout has local changes; they will be preserved.", dirty)
        branch = self.git(repo, "symbolic-ref", "--quiet", "--short", "HEAD") if self.optional(repo, "symbolic-ref", "--quiet", "HEAD") else ""
        if not branch:
            self.unsafe(name, "The checkout is detached and cannot be updated safely.")
        return branch

    def sync(self, repo, name):
        repo = Path(repo)
        branch = self.guard(repo, name)
        remotes = self.git(repo, "remote").splitlines()
        remote = self.optional(repo, "config", "--get", "branch." + branch + ".remote")
        merge = self.optional(repo, "config", "--get", "branch." + branch + ".merge")
        if remote == ".":
            self.unsafe(name, "A local-only upstream needs manual review.")
        if remote and remote not in remotes:
            if name not in OFFICIAL or remote != "origin":
                self.unsafe(name, "The configured upstream remote is missing.")
            remotes.append(remote)
            self.git(repo, "remote", "add", remote, self.official_url(name))
            print("Self-heal: restored official remote for " + name, flush=True)
        if not remote:
            if "origin" in remotes:
                remote = "origin"
            elif not remotes and name in OFFICIAL:
                remote = "origin"
                self.git(repo, "remote", "add", remote, self.official_url(name))
                print("Self-heal: added official origin for " + name, flush=True)
            elif len(remotes) == 1:
                remote = remotes[0]
            else:
                self.unsafe(name, "No unambiguous canonical remote; review the repository configuration.")
        # Inspect every remote, not only origin. Never change an arbitrary mirror.
        for candidate in self.git(repo, "remote").splitlines():
            urls = self.optional(repo, "config", "--get-all", "remote." + candidate + ".url").splitlines()
            if len(urls) > 1:
                self.unsafe(name, "Remote has multiple fetch URLs; choose its canonical URL manually.")
            url = urls[0] if urls else ""
            if not url:
                if candidate == remote and name in OFFICIAL:
                    self.git(repo, "config", "remote." + candidate + ".url", self.official_url(name))
                    print("Self-heal: restored missing official URL for " + name, flush=True)
                elif candidate == remote:
                    self.unsafe(name, "Third-party tap has no canonical remote URL; do not guess a replacement.")
                continue
            normalized = canonical_official(name, url)
            if normalized != url:
                self.git(repo, "remote", "set-url", candidate, normalized)
                print("Self-heal: normalized official remote for " + name + " (" + candidate + ")", flush=True)
        if not self.optional(repo, "config", "--get-all", "remote." + remote + ".fetch"):
            self.git(repo, "config", "remote." + remote + ".fetch", "+refs/heads/*:refs/remotes/" + remote + "/*")
            print("Self-heal: restored missing fetch refspec for " + name, flush=True)
        self.git(repo, "fetch", "--prune", remote)
        refs = self.git(repo, "for-each-ref", "--format=%(refname:short)", "refs/remotes/" + remote + "/").splitlines()
        target = remote + "/" + merge.removeprefix("refs/heads/") if merge.startswith("refs/heads/") else ""
        stable_tag = ""
        if name == "brew" and branch == "stable" and not merge:
            tags = self.git(repo, "tag", "--list", "--sort=-version:refname").splitlines()
            stable_tag = next((x for x in tags if re.fullmatch(r"\d+\.\d+\.\d+", x)), "")
            if not stable_tag:
                self.unsafe(name, "The stable checkout has no release tag; review its upstream manually.")
            target = "refs/tags/" + stable_tag
        if not stable_tag and target not in refs:
            same = remote + "/" + branch
            default = self.optional(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/" + remote + "/HEAD")
            choices = [ref for ref in (remote + "/main", remote + "/master") if ref in refs]
            target = same if same in refs else default if default in refs else choices[0] if len(choices) == 1 else ""
            if not target:
                self.unsafe(name, "The upstream branch is missing or ambiguous; choose it manually.")
        ahead, behind = map(int, self.git(repo, "rev-list", "--left-right", "--count", "HEAD..." + target).split())
        if ahead:
            self.unsafe(name, "The checkout has local or divergent commits; they will be preserved.", str(ahead) + " commit(s) ahead")
        self.guard(repo, name)
        if behind:
            self.git(repo, "merge", "--ff-only", target)
            print("Self-heal: fast-forwarded " + name, flush=True)
        if not stable_tag and (not merge or remote + "/" + merge.removeprefix("refs/heads/") != target):
            self.git(repo, "branch", "--set-upstream-to=" + target, branch)
            print("Self-heal: repaired upstream for " + name, flush=True)
        self.guard(repo, name)
        print("Preflight: " + name + " clean and synchronized", flush=True)

    def repair_launcher(self, repo):
        """Repair only Brew's own launcher; never replace a regular user file."""
        link = Path(self.brew.prefix) / "bin/brew"
        target = repo / "bin/brew"
        if not target.is_file() or not os.access(target, os.X_OK):
            raise PoolError("Canonical Homebrew launcher missing: " + str(target))
        if link.exists() and link.resolve() == target.resolve():
            return
        if link.is_symlink():
            old = Path(os.path.abspath(link.parent / os.readlink(link)))
            legacy = {Path(self.brew.prefix) / "Library/Homebrew/bin/brew",
                      Path(self.brew.prefix) / "Library/bin/brew"}
            if old not in legacy:
                self.unsafe("brew launcher", "Existing brew symlink has an unknown target; review it manually.")
        elif link.exists():
            self.unsafe("brew launcher", "A regular file occupies bin/brew; it will not be overwritten.")
        if link.parent.is_dir():
            staging = link.parent / (".brew-pool-link-" + str(os.getpid()))
            try:
                staging.symlink_to(os.path.relpath(target, link.parent))
                os.replace(staging, link)
            finally:
                if staging.is_symlink():
                    staging.unlink()
            print("Self-heal: repaired Homebrew launcher symlink", flush=True)

    def run(self):
        repo = Path(self.brew.run("--repository"))
        self.sync(repo, "brew")
        taps = self.brew.package_lines(self.brew.run("tap"), taps=True)
        for tap in taps:
            self.sync(Path(self.brew.run("--repository", tap)), tap)
        for official in ("homebrew/core", "homebrew/cask"):
            if official not in taps:
                # Some old checkouts exist without being listed by API mode.
                path = repo / "Library/Taps/homebrew" / ("homebrew-" + official.split("/")[1])
                if path.exists():
                    self.sync(path, official)
                else:
                    print("Preflight: " + official + " uses API; no checkout created", flush=True)
        self.repair_launcher(repo)


def executable_candidate(executable):
    path = Path(executable)
    if os.access(path, os.X_OK):
        return str(path)
    # An absent/stale launcher can still be recovered from the known prefix.
    candidate = path.parent.parent / "Homebrew/bin/brew" if path.parent.name == "bin" else None
    if candidate and os.access(candidate, os.X_OK):
        return str(candidate)
    return str(path)
