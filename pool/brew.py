"""A cooperative brew routine using public CLI operations, not patched formulae."""
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .actions import ActionRequired, classify_command_failure
from .artifacts import compatible, obtain
from .client import Lease, Unavailable, local_lock
from .common import PoolError, canonical, digest, validate, version_order
from .jobs import Job, step
from .preflight import Preflight, executable_candidate
from .processes import JobStopped, check_stop, run_command

MAC_TAGS = {11: "big_sur", 12: "monterey", 13: "ventura", 14: "sonoma", 15: "sequoia", 26: "tahoe"}


class Brew:
    def __init__(self, client, executable=None):
        self.client = client
        self.executable = executable or client.config.get("brew") or shutil.which("brew", path=self.normalized_path(os.environ.get("PATH", "")))
        if not self.executable and Path("/usr/local/Homebrew/bin/brew").is_file():
            self.executable = "/usr/local/bin/brew"
        if not self.executable:
            raise PoolError("Homebrew not found; configure brew or add it to PATH")
        self.executable = executable_candidate(self.executable)
        self.env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_INSTALL_CLEANUP="1",
                        HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK="1", HOMEBREW_NO_ASK="1")
        self.env["PATH"] = self.normalized_path(self.env.get("PATH", ""))
        self.prefix = self.run("--prefix")
        self.cellar = self.run("--cellar")
        self.cache = Path(self.run("--cache"))
        if platform.system() != "Darwin" or platform.machine() != "x86_64":
            raise PoolError("This brew adapter requires a macOS x86_64 process (Intel)")
        major = int(self.run_system("sw_vers", "-productVersion").split(".")[0])
        self.tag = MAC_TAGS.get(major)
        if not self.tag:
            raise PoolError("Unreviewed macOS version; add its bottle tag before building")
        self.major = major
        self.seen = set()
        self.synced_taps = set()
        self.casks_seen = set()
        self.casks_active = set()
        self.force_targets = set()

    @staticmethod
    def normalized_path(existing):
        """Preserve the launch environment and add the standard Intel Brew paths."""
        values = [x for x in existing.split(os.pathsep) if x]
        for required in ("/usr/local/bin", "/usr/local/sbin"):
            if required not in values:
                values.append(required)
        return os.pathsep.join(values)

    @staticmethod
    def run_system(*args):
        return run_command(list(args))

    def run(self, *args, cwd=None, capture=True, env_extra=None):
        argv = [self.executable, *args]
        env = dict(self.env, **(env_extra or {}))
        try:
            return run_command(argv, env=env, cwd=cwd, stream=not capture)
        except subprocess.CalledProcessError as error:
            action = classify_command_failure((error.output or "") + (error.stderr or ""), args[-1] if args else "")
            if action:
                raise action from error
            raise

    @staticmethod
    def package_lines(output, taps=False):
        """Diagnostics are never arguments. stderr is separate; stdout is allowlisted."""
        clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output)
        pattern = r"[a-z0-9][a-z0-9_+@.-]*(?:/[a-z0-9][a-z0-9_+@.-]*){0,2}"
        values = []
        for line in clean.splitlines():
            name = line.strip()
            if not re.fullmatch(pattern, name) or any(x in (".", "..") for x in name.split("/")):
                if name:
                    print("Ignored Homebrew diagnostic: " + name, flush=True)
                continue
            if taps and name.count("/") != 1:
                raise PoolError("Invalid tap name in Homebrew output: " + name)
            if name not in values:
                values.append(name)
        return values

    def preflight(self):
        Preflight(self).run()

    def info_without_api(self, name):
        items = json.loads(
            self.run(
                "info", "--json=v2", "--formula", name,
                env_extra={"HOMEBREW_NO_INSTALL_FROM_API": "1"},
            )
        )["formulae"]
        if len(items) != 1:
            raise PoolError("Expected one local-tap formula: " + name)
        return items[0]

    def verify_tap_formula(self, info):
        local = self.info_without_api(info["full_name"])

        api_version = self.pkg_version(info)
        local_version = self.pkg_version(local)
        if local_version != api_version:
            raise PoolError(
                "Tap/API version mismatch after sync: "
                + info["full_name"]
                + " API=" + api_version
                + " tap=" + local_version
            )

        if local.get("version_scheme", 0) != info.get("version_scheme", 0):
            raise PoolError(
                "Tap/API version_scheme mismatch after sync: "
                + info["full_name"]
            )

        api_sha = (info.get("ruby_source_checksum") or {}).get("sha256")
        local_sha = (local.get("ruby_source_checksum") or {}).get("sha256")
        if api_sha and local_sha and api_sha != local_sha:
            raise PoolError(
                "Tap/API formula checksum mismatch after sync: "
                + info["full_name"]
            )

    def sync_tap_for_build(self, info):
        tap = info.get("tap") or "homebrew/core"
        if tap not in self.package_lines(self.run("tap"), taps=True):
            self.run("tap", "--force", tap, capture=False)
        repo = Path(self.run("--repository", tap))
        Preflight(self).sync(repo, tap)
        self.verify_tap_formula(info)
        self.synced_taps.add(tap)
        print("Bottle tap synchronized: " + tap, flush=True)
        self.synced_taps.add(tap)
        print("Bottle tap synchronized: " + tap, flush=True)

    def pour(self, path, as_dependency=False):
        if self.env.get("HOMEBREW_FORBID_PACKAGES_FROM_PATHS"):
            raise PoolError("Explicit Homebrew policy forbids local packages; pool pour is unavailable")
        flags = ["--as-dependency"] if as_dependency else []
        # Current Homebrew requires developer mode for installation from file paths.
        # Enable it only in this verified bottle's subprocess, not the user's shell.
        self.run("install", "--formula", *flags, str(path), capture=False,
                 env_extra={"HOMEBREW_DEVELOPER": "1"})

    def info(self, name):
        items = json.loads(self.run("info", "--json=v2", "--formula", name))["formulae"]
        if len(items) != 1:
            raise PoolError("Expected one formula: " + name)
        return items[0]

    @staticmethod
    def pkg_version(info):
        stable = info["versions"]["stable"]
        if not stable:
            raise PoolError("HEAD-only formulae cannot be pooled")
        return stable + ("_" + str(info["revision"]) if info.get("revision") else "")

    def check_options(self, info):
        for installed in info.get("installed", []):
            if installed.get("used_options") or installed.get("version", "").startswith("HEAD"):
                raise ActionRequired("Custom options or a HEAD build need a separately reviewed variant.",
                                     category="unsafe_formula", subject=info["full_name"])

    def up_to_date(self, info):
        return not info.get("outdated") and any(x["version"] == self.pkg_version(info) for x in info.get("installed", []))

    def context(self, info):
        deps = {}
        names = self.package_lines(self.run("deps", "--full-name", info["full_name"]))
        for name in names:
            dep = self.info(name)
            self.check_options(dep)
            if not self.up_to_date(dep):
                raise PoolError("Runtime dependency not current: " + name)
            deps[dep["full_name"]] = {"version": self.pkg_version(dep), "source": self.source_hash(dep)}
        return {"formula_sha256": self.source_hash(info), "dependencies": deps,
                "prefix": self.prefix, "cellar": self.cellar, "options": []}

    def source_hash(self, info):
        checksum = (info.get("ruby_source_checksum") or {}).get("sha256")
        return checksum or hashlib.sha256(self.run("cat", info["full_name"]).encode()).hexdigest()

    def manifest(self, info, kind="brew-local-bottle", tag=None, expected_sha=None):
        context = self.context(info)
        variant = hashlib.sha256(canonical({"prefix": self.prefix, "cellar": self.cellar,
                                           "cpu": "homebrew-baseline", "options": [],
                                           "runtime_abi": context["dependencies"]})).hexdigest()
        rebuild = info.get("bottle", {}).get("stable", {}).get("rebuild", 0)
        m = {"schema": 1, "kind": kind, "name": (info.get("tap") or "homebrew/core") + "/" + info["name"],
             "version": self.pkg_version(info), "platform": "macos-x86_64-" + (tag or self.tag),
             "variant": variant,
             "version_order": [info.get("version_scheme", 0)] + version_order(info["versions"]["stable"], info.get("revision", 0), rebuild),
             "filename": info["name"] + "--" + self.pkg_version(info) + "." + (tag or self.tag) + ".bottle.tar.gz",
             "size": 1, "sha256": expected_sha or "0" * 64,
             "metadata": {"publisher": "StefanAlMare", "context": context, "bottle_rebuild": rebuild}}
        return validate(m)

    def official_bottle(self, info):
        if info.get("pour_bottle_only_if"):
            return None
        files = info.get("bottle", {}).get("stable", {}).get("files", {})
        candidates = [MAC_TAGS[n] for n in sorted(MAC_TAGS, reverse=True) if n <= self.major] + ["all"]
        for tag in candidates:
            entry = files.get(tag)
            if entry and entry.get("cellar") in (":any", ":any_skip_relocation", "any", "any_skip_relocation", self.cellar):
                return tag, entry
        return None

    def consume_local(self, m, as_dependency=False):
        local = self.client.local_match(m)
        try:
            found = self.client.lookup(m)
        except Unavailable:
            found = None
        with tempfile.TemporaryDirectory(prefix="pour-", dir=str(self.client.state)) as work:
            # A reviewed pool rebuild may be newer than the upstream bottle rank,
            # but formula version/revision, source and ABI must still match exactly.
            matching = found and (
                found["version"] == m["version"]
                and found["metadata"].get("context") == m["metadata"].get("context")
                and len(found["version_order"]) == len(m["version_order"])
                and found["version_order"][:-1] == m["version_order"][:-1]
                and found["version_order"][-1] >= m["version_order"][-1]
            )
            if matching:
                path = Path(work) / found["filename"]
                self.client.fetch(found, path)
            elif local:
                path = Path(work) / local[0]["filename"]
                shutil.copyfile(local[1], path)
            else:
                return False
            print("Pool bottle: " + m["name"], flush=True)
            # Bottle contains the original formula; Homebrew performs relocation/postinstall.
            self.pour(path, as_dependency)
            if not self.up_to_date(self.info(m["name"])):
                raise PoolError("Pool bottle did not install the requested current version")
            return True

    def ensure(self, name, allow_build=True, as_dependency=False):
        job = getattr(self, "active_job", None)
        previous = job.data.get("active_package", "") if job else ""
        if job:
            job.data["active_package"] = name
            job.save()
        try:
            result = self._ensure(name, allow_build, as_dependency)
            if job:
                job.data["active_package"] = previous
                job.save()
            return result
        except (PoolError, JobStopped, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
            if not isinstance(error, ActionRequired) and not getattr(error, "pool_failed_package", None):
                error.pool_failed_package = name
            raise

    def _ensure(self, name, allow_build=True, as_dependency=False):
        check_stop()
        info = self.info(name)
        name = info["full_name"]
        if name in self.seen:
            return
        self.check_options(info)
        installed = info.get("installed", [])
        if installed:
            as_dependency = not any(x.get("installed_on_request", True) for x in installed)
        if info.get("pinned"):
            raise ActionRequired("Pinned dependency/formula needs manual review.",
                                 category="unsafe_formula", subject=name,
                                 choices=[{"id": "skip", "label": "Skip"},
                                          {"id": "cancel", "label": "Cancel Upgrade"}])
        # Validate/install the runtime graph even when the requested formula itself
        # is current.  Otherwise a long build can finish with an outdated keg (for
        # example openssl@3) and only fail during bottle-context validation.
        deps = self.package_lines(self.run("deps", "--topological", "--full-name", name))
        for dep in deps:
            self.ensure(dep, allow_build, as_dependency=True)
        if self.up_to_date(info) and name not in self.force_targets:
            self.seen.add(name)
            return
        info = self.info(name)
        local_manifest = self.manifest(info)
        if self.consume_local(local_manifest, as_dependency):
            self.seen.add(name)
            return
        official = self.official_bottle(info)
        if official:
            self.install_official(info, *official, as_dependency=as_dependency)
            self.seen.add(name)
            return
        if not allow_build:
            raise PoolError("Build deferred for this run: " + name)

        # brew bottle resolves formulae from the local tap checkout
        # (without the API). Keep that checkout aligned with the formula
        # Homebrew is about to build, but only by a clean fast-forward.
        self.sync_tap_for_build(info)
        info = self.info(name)
        self.sync_tap_for_build(info)

        # On a miss, build dependencies also participate in the same pool protocol.
        build_deps = self.package_lines(self.run("deps", "--include-build", "--include-test", "--topological", "--full-name", name))
        for dep in build_deps:
            self.ensure(dep, allow_build, as_dependency=True)

        info = self.info(name)
        self.sync_tap_for_build(info)
        local_manifest = self.manifest(info)
        try:
            with Lease(self.client, local_manifest, self.client.config.get("lock_wait_seconds", 600)) as lease:
                if not lease.token:
                    raise PoolError("Build still busy; retry later: " + name)
                # Another Mac may have finished while this one waited for the lease.
                if not self.consume_local(local_manifest, as_dependency):
                    self.build(info, local_manifest, lease, as_dependency)
        except Unavailable:
            print("Pool offline; building into the local spool: " + name, flush=True)
            self.build(info, local_manifest, None, as_dependency)
        self.seen.add(name)

    def repair_dependency(self, name, allow_build=True):
        """Repair one dependency while preserving any paused durable queue."""
        self.validate_name(name)
        self.preflight()
        self.run("update", capture=False)
        self.ensure(name, allow_build=allow_build, as_dependency=True)
        repaired = self.info(name)
        if not self.up_to_date(repaired):
            raise PoolError("Dependency is still not current after repair: " + name)
        # Recheck the entire installed graph.  A non-zero result is deliberately
        # surfaced before Retry can publish a dependent bottle.
        self.run("missing", capture=False)
        self.run("linkage", "--test", repaired["full_name"], capture=False)
        return repaired["full_name"]

    def install_official(self, info, tag, entry, as_dependency=False):
        m = self.manifest(info, "brew-upstream-bottle", tag, entry["sha256"])
        cache = Path(self.run("--cache", "--bottle-tag=" + tag, info["full_name"]))
        cache.parent.mkdir(parents=True, exist_ok=True)
        # Preserve original cache naming; Brew still verifies upstream checksums.
        hit = False
        try:
            found = self.client.lookup(m)
            if compatible(found, m) and found["sha256"] == entry["sha256"]:
                self.client.fetch(found, cache)
                hit = True
                print("Pool official bottle: " + info["full_name"], flush=True)
        except Unavailable:
            pass
        if not hit:
            self.run("fetch", "--formula", "--bottle-tag=" + tag, info["full_name"], capture=False)
        if not cache.is_file() or digest(cache) != entry["sha256"]:
            raise PoolError("Official bottle missing or checksum mismatch: " + info["full_name"])
        m.update(filename=cache.name, size=cache.stat().st_size)
        spool = self.client.enqueue(m, cache)
        try:
            self.client.publish_entry(spool)
        except Unavailable:
            pass
        rebuild = info.get("bottle", {}).get("stable", {}).get("rebuild", 0)
        filename = info["name"] + "--" + self.pkg_version(info) + "." + tag + ".bottle" + ("." + str(rebuild) if rebuild else "") + ".tar.gz"
        with tempfile.TemporaryDirectory(prefix="upstream-pour-", dir=str(self.client.state)) as work:
            local_bottle = Path(work) / filename
            shutil.copyfile(cache, local_bottle)
            self.pour(local_bottle, as_dependency)
        # If Homebrew ignored this bottle and built source, never claim that keg is bottled.
        installed = self.info(info["full_name"])
        if not self.up_to_date(installed):
            raise PoolError("Homebrew did not install requested current version")

    def build(self, info, manifest, lease, as_dependency=False):
        name = info["full_name"]
        # No architecture-specific tuning: use Homebrew's portable CPU baseline.
        if any(os.environ.get(k) for k in ("HOMEBREW_OPTFLAGS", "HOMEBREW_ARCH", "CFLAGS", "CXXFLAGS", "LDFLAGS")):
            raise PoolError("Unset custom compiler/CPU flags before producing shared bottles")
        tap = info.get("tap")
        if tap and tap not in self.package_lines(self.run("tap"), taps=True):
            self.run("tap", "--force", tap, capture=False)
        flags = ["--as-dependency"] if as_dependency else []
        action = "reinstall" if self.up_to_date(info) and name in self.force_targets else "install"
        self.run(action, "--formula", "--build-bottle", *flags, name, capture=False)
        postinstalled = False
        try:
            with tempfile.TemporaryDirectory(prefix="bottle-", dir=str(self.client.state)) as work:
                self.sync_tap_for_build(info)
                bottle_args = ["bottle", "--json", "--keep-old"]
                root_url = (info.get("bottle", {}).get("stable", {}) or {}).get("root_url")
                # Homebrew/core owns its canonical root selection. External taps must
                # retain their declared bottle host instead of silently switching to
                # ghcr.io/v2/homebrew/core during bottle generation.
                if root_url and (info.get("tap") or "homebrew/core") != "homebrew/core":
                    bottle_args.extend(["--root-url", root_url])
                self.run(*bottle_args, name, cwd=work, capture=False)
                bottles = list(Path(work).glob("*.bottle*.tar.gz"))
                records = list(Path(work).glob("*.json"))
                if len(bottles) != 1 or len(records) != 1:
                    raise PoolError("Unexpected brew bottle output")
                output = bottles[0]
                record = json.loads(records[0].read_text())
                data = next(iter(record.values()))
                tags = data["bottle"]["tags"]
                tag_data = tags.get(self.tag) or tags.get("all")
                if not tag_data or tag_data["sha256"] != digest(output):
                    raise PoolError("Brew bottle JSON/tag/SHA-256 mismatch")
                # Keep generated filename/rebuild; consume only exact formula context.
                manifest.update(filename=output.name, sha256=tag_data["sha256"], size=output.stat().st_size)
                manifest["metadata"]["bottle_json"] = {"cellar": data["bottle"].get("cellar"), "tag": self.tag,
                                                         "rebuild": data["bottle"].get("rebuild", 0)}
                self.run("postinstall", name, capture=False)
                postinstalled = True
                self.run("test", name, capture=False)
                # Detect metadata/dependency changes during long builds.
                after = self.info(name)
                if self.pkg_version(after) != manifest["version"] or self.context(after) != manifest["metadata"]["context"]:
                    raise PoolError("Formula/dependency context changed during build; artifact not published")
                queued = self.client.enqueue(manifest, output)
                if lease and not lease.lost:
                    try:
                        self.client.publish_entry(queued, lease)
                    except Unavailable:
                        pass
        finally:
            # --build-bottle skips this; the building Mac also needs usable software.
            if not postinstalled:
                self.run("postinstall", name, capture=False)

    @staticmethod
    def validate_name(name):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_+@.-]*(?:/[A-Za-z0-9][A-Za-z0-9_+@.-]*){0,2}", name):
            raise PoolError("Enter one Homebrew package name, not a path, URL, or command option")
        if any(part in (".", "..") for part in name.split("/")):
            raise PoolError("Invalid package name")

    def resolve(self, name, kind="auto"):
        self.validate_name(name)
        if kind not in ("auto", "formula", "cask"):
            raise PoolError("Choose Auto, Formula, or Cask")
        matches = []
        for candidate in (["formula", "cask"] if kind == "auto" else [kind]):
            try:
                record = json.loads(self.run("info", "--json=v2", "--" + candidate, name))
            except subprocess.CalledProcessError:
                if kind != "auto":
                    raise PoolError("Package not found as " + candidate + ": " + name)
                continue
            items = record.get("formulae" if candidate == "formula" else "casks", [])
            if len(items) == 1:
                matches.append((candidate, items[0]))
        if len(matches) > 1:
            raise ActionRequired("This name exists as both Formula and Cask.",
                                 category="package_type", subject=name,
                                 choices=[{"id": "formula", "label": "Use Formula"},
                                          {"id": "cask", "label": "Use Cask"},
                                          {"id": "cancel", "label": "Cancel"}])
        if not matches:
            raise PoolError("Package not found: " + name)
        return matches[0]

    def install(self, name, kind="auto", allow_build=True, update=True, allow_mutable_cask=False, mode="start"):
        with local_lock(self.client.state):
            self.validate_name(name)
            job = Job(self.client.state)
            if mode == "resume" and not job.data:
                mode = "start"
            if mode == "start":
                steps = ([step("preflight"), step("update")] if update else [])
                steps += [step("sync"), step("install", name, package_type=kind, mutable=allow_mutable_cask),
                          step("sync"), step("missing")]
                job.start("install", steps, dict(allow_build=allow_build))
            if kind != "auto" and job.data:
                for item in job.data["steps"]:
                    if item["kind"] == "install":
                        item["options"]["package_type"] = kind
                        item["options"]["mutable"] = allow_mutable_cask
            self._run_job(job, mode)

    def cask(self, name, install=False, allow_mutable=False):
        self.validate_name(name)
        if name in self.casks_seen:
            return
        if name in self.casks_active:
            raise PoolError("Cyclic cask dependency: " + name)
        self.casks_active.add(name)
        try:
            self._cask(name, install, allow_mutable)
            self.casks_seen.add(name)
        finally:
            self.casks_active.remove(name)

    def _cask(self, name, install=False, allow_mutable=False):
        records = json.loads(self.run("info", "--json=v2", "--cask", name))["casks"]
        if len(records) != 1:
            raise PoolError("Expected one cask: " + name)
        info = records[0]
        if info.get("pinned"):
            raise ActionRequired("Pinned cask needs manual review.", category="unsafe_formula",
                                 subject=name,
                                 choices=[{"id": "skip", "label": "Skip"},
                                          {"id": "cancel", "label": "Cancel Upgrade"}])
        action = "install" if install and not info.get("installed") else "upgrade"
        checksum, version = info.get("sha256"), info.get("version")
        mutable = not checksum or checksum == "no_check" or version == "latest"
        if mutable and not allow_mutable:
            raise ActionRequired("This cask has no fixed version/checksum and cannot be pooled safely.",
                                 category="unsafe_formula", subject=name,
                                 detail="Enable upstream-only casks explicitly to install it without publication.",
                                 choices=[{"id": "skip", "label": "Skip"},
                                          {"id": "cancel", "label": "Cancel"}])
        # A cask can have formula dependencies. Process them through the pool too.
        for dependency in (info.get("depends_on") or {}).get("formula", []):
            self.ensure(dependency, as_dependency=True)
        for dependency in (info.get("depends_on") or {}).get("cask", []):
            self.cask(dependency, install=True, allow_mutable=allow_mutable)
        if mutable:
            print("Upstream only — not reproducible, not published: " + name, flush=True)
            self.run(action, "--cask", name, capture=False)
            return
        cache = Path(self.run("--cache", "--cask", name))
        cache.parent.mkdir(parents=True, exist_ok=True)
        try:
            rank = version_order(version)
        except PoolError as e:
            raise PoolError("Cask version needs explicit adapter rank: " + name) from e
        m = {"schema": 1, "kind": "brew-cask", "name": info.get("full_token", name), "version": version,
             "version_order": rank, "platform": "macos-x86_64-" + self.tag,
             "variant": hashlib.sha256(canonical({"language": info.get("language", []), "arch": "x86_64"})).hexdigest(),
             "filename": cache.name, "sha256": checksum, "size": 1,
             "metadata": {"publisher": "StefanAlMare", "context": {"url": info["url"], "sha256": checksum}}}
        validate(m)
        hit = False
        try:
            found = self.client.lookup(m)
            if compatible(found, m) and found["sha256"] == checksum:
                self.client.fetch(found, cache)
                hit = True
                print("Pool cask: " + name, flush=True)
        except Unavailable:
            pass
        if not hit:
            self.run("fetch", "--cask", name, capture=False)
        if not cache.is_file() or digest(cache) != checksum:
            raise PoolError("Cask checksum mismatch")
        after = json.loads(self.run("info", "--json=v2", "--cask", name))["casks"][0]
        if any(after.get(field) != info.get(field) for field in ("version", "sha256", "url")):
            raise PoolError("Cask metadata changed during download; retry: " + name)
        m["size"] = cache.stat().st_size
        spool = self.client.enqueue(m, cache)
        try:
            self.client.publish_entry(spool)
        except Unavailable:
            pass
        # Ensure metadata did not change during download/publication. Brew consumes
        # this verified cache entry using its usual quarantine/installer handling.
        self.run(action, "--cask", name, capture=False)

    def upgrade(self, names=(), allow_build=True, update=True, casks=True, skip=(), mode="start"):
        with local_lock(self.client.state):
            job = Job(self.client.state)
            if mode == "resume" and not job.data:
                mode = "start"
            if mode == "start":
                steps = ([step("preflight"), step("update")] if update else [])
                steps += [step("discover"), step("sync"), step("sync"), step("missing")]
                job.start("upgrade", steps, dict(names=list(names), allow_build=allow_build, casks=casks))
            self._run_job(job, mode, skip)

    def _run_job(self, job, mode, skip=()):
        self.active_job = job
        if mode == "retry":
            self.force_targets = {s["name"] for s in job.failures}
            self.force_targets.update(s["failed_package"] for s in job.failures if s.get("failed_package"))
        interrupted = [s for s in job.remaining if s.get("interrupted") or s["status"] == "running"]
        self.force_targets.update(s["name"] for s in interrupted)
        self.force_targets.update(s["failed_package"] for s in interrupted if s.get("failed_package"))
        if job.data and job.data.get("active_package"):
            self.force_targets.add(job.data["active_package"])
        job.run(self._execute_step, "retry" if mode == "retry" else "resume", skip)

    def _execute_step(self, item, job):
        kind, name = item["kind"], item["name"]
        allow_build = job.data["options"]["allow_build"]
        if kind == "preflight":
            self.preflight()
        elif kind in ("update", "missing"):
            self.run(kind, capture=False)
        elif kind == "discover":
            outdated = json.loads(self.run("outdated", "--json=v2"))
            requested = job.data["options"].get("names", [])
            names = requested or [x["name"] for x in outdated["formulae"] if not x.get("pinned")]
            packages = [step("formula", x) for x in names]
            if job.data["options"].get("casks") and not requested:
                packages += [step("cask", x["name"]) for x in outdated.get("casks", []) if not x.get("pinned")]
            packages += [step("adapter", x["name"]) for x in self.client.config.get("artifacts", [])]
            index = job.data["steps"].index(item)
            job.data["steps"][index + 2:index + 2] = packages
        elif kind == "sync":
            results = self.client.sync()
            print("Spool sync: " + str(results), flush=True)
            errors = [x for x in results if x.startswith("retained:")]
            if errors:
                raise PoolError("; ".join(errors))
        elif kind == "formula":
            self.ensure(name, allow_build)
        elif kind == "cask":
            self.cask(name)
        elif kind == "install":
            resolved, info = self.resolve(name, item["options"]["package_type"])
            if resolved == "formula":
                if name in self.force_targets:
                    self.force_targets.add(info["full_name"])
                self.ensure(info["full_name"], allow_build)
            else:
                self.cask(name, install=True, allow_mutable=item["options"]["mutable"])
        elif kind == "adapter":
            recipe = next((x for x in self.client.config.get("artifacts", []) if x["name"] == name), None)
            if recipe is None:
                raise PoolError("Saved adapter no longer exists: " + name)
            result = obtain(self.client, recipe, allow_build)
            if result == "deferred":
                raise PoolError("Adapter build deferred: " + name)
            print("External adapter: " + name + ": " + result, flush=True)
        else:
            raise PoolError("Unknown saved step: " + kind)
