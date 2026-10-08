"""Conservative recovery of existing kegs. Never bottle the live installation."""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path

from .common import PoolError, atomic_json, canonical, digest
from .imports import BottleImporter, normalize_cpu_features
from .processes import JobStopped, check_stop, run_command

Q9300_FEATURES = {"MMX", "SSE", "SSE2", "SSE3", "SSSE3", "SSE4_1", "CX16"}

# Use Homebrew's real sandbox launcher. It passes its authenticated inheritance
# descriptor itself, allowing its workers to retain the SAME outer confinement
# without attempting a second macOS sandbox. Never fake a descriptor or disable
# Homebrew's security checks. Missing API => review, not unsandboxed fallback.
SANDBOX_RUNNER = """
require "json"
require "sandbox"
data = JSON.parse(ARGV.fetch(0))
Sandbox.ensure_sandbox_available!
raise "Required isolated capture API unavailable" unless Sandbox.respond_to?(:for_operation)
root = Pathname(data.fetch("root")).realpath
policy = Sandbox.for_operation(read_paths: [root], write_paths: [root], network_access: false)
policy.capture(data.fetch("brew"), args: data.fetch("args"),
  print_stdout: true, print_stderr: true, must_succeed: true,
  chdir: data.fetch("cwd"), temporary_directory: root/"tmp")
"""


def normalized_features(values):
    return normalize_cpu_features(values)


def tree_hash(directory):
    """Hash bytes, relative paths, modes and links without following links."""
    directory = Path(directory)
    result = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        check_stop()
        mode = path.lstat().st_mode
        item = [str(path.relative_to(directory)), stat.S_IMODE(mode)]
        if path.is_symlink():
            item += ["link", os.readlink(path)]
        elif path.is_file():
            item += ["file", digest(path)]
        elif path.is_dir():
            item += ["dir"]
        else:
            raise PoolError("Unsupported special file in installed keg")
        result.update(canonical(item))
    return result.hexdigest()


def inspect_keg(keg, formula, version):
    keg = Path(keg)
    receipt_path = keg / "INSTALL_RECEIPT.json"
    recipe_path = keg / ".brew" / (formula.split("/")[-1] + ".rb")
    for path in (keg, receipt_path, recipe_path.parent, recipe_path):
        if path.is_symlink() or not path.exists():
            raise PoolError("Installed receipt/recipe is missing or linked")
    receipt = json.loads(receipt_path.read_text())
    if not isinstance(receipt, dict):
        raise PoolError("Installed receipt is not an object")
    return {"formula": formula, "version": version, "keg": str(keg),
            "receipt": receipt, "receipt_sha256": digest(receipt_path),
            "recipe_sha256": digest(recipe_path),
            "arch": receipt.get("arch"), "compiler": receipt.get("compiler"),
            "built_on": receipt.get("built_on") if isinstance(receipt.get("built_on"), dict) else {},
            "built_as_bottle": receipt.get("built_as_bottle") is True,
            "runtime_dependencies": receipt.get("runtime_dependencies"),
            "classification": "requires_review",
            "reason": "No artifact exists yet; explicit producer proof and isolated validation are required"}


class IsolatedBrew:
    """Offline copy; OS policy denies all network and all writes outside root."""
    def __init__(self, root, original):
        self.root = Path(root).resolve()
        self.prefix = self.root / "prefix"
        # Homebrew supports repository == prefix. This keeps its repository
        # root writable for install diagnostics while its real sandbox still
        # protects Library, .git and bin/brew. Never relax those protections.
        self.repository = self.prefix
        self.executable = self.prefix / "bin/brew"
        self.original = original
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("HOMEBREW_")}
        self.env.update(HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_INSTALL_FROM_API="1",
                        HOMEBREW_NO_ANALYTICS="1", HOMEBREW_NO_INSTALL_CLEANUP="1",
                        HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK="1",
                        HOMEBREW_NO_BOTTLE_SOURCE_FALLBACK="1", HOMEBREW_NO_ASK="1",
                        HOMEBREW_CACHE=str(self.root / "cache"), HOMEBREW_LOGS=str(self.root / "logs"),
                        HOMEBREW_TEMP=str(self.root / "tmp"), XDG_CONFIG_HOME=str(self.root / "config"),
                        TMPDIR=str(self.root / "tmp"))
        self.policy = SANDBOX_RUNNER

    def run(self, *args, cwd=None, stream=False, env_extra=None):
        if not Path("/usr/bin/sandbox-exec").is_file():
            raise PoolError("Isolated capture requires the macOS write/network sandbox")
        payload = json.dumps(dict(root=str(self.root), brew=str(self.executable),
                                  args=list(args), cwd=str(cwd or self.root)))
        environment = dict(self.env, **(env_extra or {}))
        return run_command([str(self.executable), "ruby", "-e", SANDBOX_RUNNER, "--", payload],
                           env=environment, cwd=cwd, stream=stream)

    def prepare(self, formulae):
        repository = Path(self.original.run("--repository")).resolve()
        self.prefix.mkdir()
        (self.root / "tmp").mkdir()
        # Local filesystem clone ONLY. Never clone/fetch a GitHub URL.
        run_command(["git", "clone", "--quiet", "--no-hardlinks", "--dissociate", str(repository), str(self.repository)])
        vendor = repository / "Library/Homebrew/vendor"
        bundled = vendor / "bundle"
        if bundled.is_dir():
            shutil.copytree(bundled, self.repository / "Library/Homebrew/vendor/bundle", symlinks=True, dirs_exist_ok=True)
        ruby = vendor / "portable-ruby/current"
        if not ruby.is_dir():
            raise PoolError("Existing portable Ruby is required; no downloads permitted")
        target = self.repository / "Library/Homebrew/vendor/portable-ruby"
        target.mkdir(parents=True, exist_ok=True)
        ruby_version = (vendor / "portable-ruby-version").read_text().strip()
        if ruby.resolve().name != ruby_version:
            raise PoolError("Local portable Ruby does not match Homebrew; no automatic download")
        (target / ruby_version).symlink_to(ruby.resolve(), target_is_directory=True)
        (target / "current").symlink_to(ruby_version, target_is_directory=True)
        if self.run("--prefix") != str(self.prefix) or self.run("--cellar") != str(self.prefix / "Cellar"):
            raise PoolError("Isolated Homebrew prefix verification failed")
        taps = self.repository / "Library/Taps"
        for tap in sorted({x.get("tap") or "homebrew/core" for x in formulae}):
            self.original.validate_name(tap)
            source = Path(self.original.run("--repository", tap)).resolve()
            if not source.is_dir():
                raise PoolError("Required tap is not local; no automatic download")
            owner, name = tap.split("/")
            destination = taps / owner.lower() / ("homebrew-" + name.lower())
            if not destination.exists():
                shutil.copytree(source, destination, symlinks=True)
        core = taps / "homebrew/homebrew-core"
        core.mkdir(parents=True, exist_ok=True)
        if not (core / ".git").exists():
            run_command(["git", "init", "--quiet", str(core)])
        for info in formulae:
            source = Path(self.original.cellar) / info["name"] / self.original.pkg_version(info)
            target = self.prefix / "Cellar" / info["name"] / self.original.pkg_version(info)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target, symlinks=True)
            self.run("trust", "--formula", info["full_name"], stream=True)
            self.run("link", "--formula", info["full_name"], stream=True)


class FormulaCapture:
    def __init__(self, client, brew):
        self.client, self.brew = client, brew

    def inspect(self, name):
        self.brew.validate_name(name)
        info = self.brew.info(name)
        self.brew.check_options(info)
        if not self.brew.up_to_date(info):
            raise PoolError("Capture requires the current installed keg; rebuild needs separate approval")
        for component in (info["name"], self.brew.pkg_version(info)):
            if not isinstance(component, str) or not component or component in (".", "..") or "/" in component:
                raise PoolError("Unsafe installed keg identity")
        keg = Path(self.brew.cellar) / info["name"] / self.brew.pkg_version(info)
        # Refuse linked ancestors before hashing or copying.
        current = keg
        cellar = Path(self.brew.cellar)
        while current != cellar:
            if current.is_symlink():
                raise PoolError("Installed keg has linked ancestry")
            current = current.parent
        evidence = inspect_keg(keg, info["full_name"], self.brew.pkg_version(info))
        evidence.update(prefix=self.brew.prefix, cellar=self.brew.cellar)
        if not evidence["built_as_bottle"]:
            evidence["reason"] = "Authentic receipt does not confirm --build-bottle; safe recovery is unavailable. Rebuild only with separate approval."
            return info, evidence
        if evidence["arch"] != "x86_64" or evidence["receipt"].get("used_options"):
            evidence["reason"] = "Architecture/options require review"
            return info, evidence
        evidence["context"] = self.brew.context(info)
        evidence["keg_tree_sha256"] = tree_hash(keg)
        evidence["reason"] = "Receipt permits bottling, but producer CPU/compiler proof and isolated pour/test are still required"
        return info, evidence

    def _proof(self, evidence, path):
        if not path:
            raise PoolError("Missing reviewed producer proof; receipt alone does not prove CPU/compiler safety")
        path = Path(path)
        if path.is_symlink() or path.stat().st_size > 2 * 1024 * 1024:
            raise PoolError("Invalid capture proof")
        proof = json.loads(path.read_text())
        if not isinstance(proof, dict):
            raise PoolError("Capture producer proof must be an object")
        if proof.get("schema") != 1 or proof.get("reviewed") is not True or not proof.get("producer"):
            raise PoolError("Producer capture proof has not been reviewed")
        for field in ("formula", "version", "prefix", "cellar", "receipt_sha256", "recipe_sha256", "keg_tree_sha256", "context"):
            if proof.get(field) != evidence.get(field):
                raise PoolError("Capture producer proof differs: " + field)
        features = proof.get("required_cpu_features")
        if not isinstance(features, list) or not features or any(not isinstance(x, str) for x in features):
            raise PoolError("Unknown CPU instructions; capture stays at review")
        if proof.get("compiler_flags") != []:
            raise PoolError("Unknown/custom compiler flags require review")
        required = normalized_features(features)
        if not required <= normalized_features(self.brew.host_cpu_features()):
            raise PoolError("Producer CPU requirements exceed this Mac")
        # Conservative minimum: a recent producer family can never be labelled
        # Core 2 compatible solely by supplying a short feature list.
        family = evidence["built_on"].get("cpu_family", "").lower()
        if family in ("haswell", "broadwell", "skylake", "kabylake", "icelake", "cometlake"):
            if not {"SSE4_2", "AVX", "AVX2"} <= required:
                raise PoolError("Modern producer family needs conservative SSE4.2/AVX/AVX2 requirements")
        elif family not in ("core2", "penryn", "nehalem", "westmere", "sandybridge", "ivybridge"):
            raise PoolError("Unknown producer CPU family; review required")
        elif family in ("nehalem", "westmere") and "SSE4_2" not in required:
            raise PoolError("Producer family requires SSE4.2")
        elif family in ("sandybridge", "ivybridge") and not {"SSE4_2", "AVX"} <= required:
            raise PoolError("Producer family requires SSE4.2 and AVX")
        return proof

    def capture(self, name, provenance=None):
        info, evidence = self.inspect(name)
        report = dict(evidence, captured_at=int(time.time()))
        report_path = self.client.state / "capture-review.json"
        report["reason"] = "Capture verification in progress; not importable or published"
        atomic_json(report_path, report)
        try:
            if getattr(self.brew, "env", {}).get("HOMEBREW_FORBID_PACKAGES_FROM_PATHS"):
                raise PoolError("Local policy forbids installing packages from paths; capture stays at review")
            if not evidence["built_as_bottle"] or evidence["arch"] != "x86_64":
                raise PoolError(evidence["reason"])
            proof = self._proof(evidence, provenance)
            if evidence["recipe_sha256"] != self.brew.planned_installed_recipe_hash(info):
                raise PoolError("Installed recipe differs from pinned formula; no capture")
            dependencies = [self.brew.info(x) for x in self.brew.declared_dependencies(
                info["full_name"], "--include-build", "--include-test", "--topological")]
            records = dependencies + [info]
            for record in records:
                self.brew.check_options(record)
                if not self.brew.up_to_date(record):
                    raise PoolError("Capture validation dependency is not current: " + record["full_name"])
            snapshots = {str(Path(self.brew.cellar) / x["name"] / self.brew.pkg_version(x)):
                         tree_hash(Path(self.brew.cellar) / x["name"] / self.brew.pkg_version(x)) for x in records}
            parent = self.client.state / "captures"
            parent.mkdir(exist_ok=True)
            # Homebrew's real test worker uses Unix sockets with short path
            # limits. A long Application Support path is not a usable prefix.
            # Only verified output is copied into the durable state directory.
            with tempfile.TemporaryDirectory(prefix="pool-capture-", dir="/private/tmp") as temporary:
                isolated = IsolatedBrew(temporary, self.brew)
                isolated.prepare(records)
                work = Path(temporary) / "bottle"
                work.mkdir()
                isolated.run("bottle", "--json", "--keep-old", info["full_name"], cwd=work, stream=True)
                bottles, metadata = list(work.glob("*.bottle*.tar.gz")), list(work.glob("*.json"))
                if len(bottles) != 1 or len(metadata) != 1:
                    raise PoolError("Unexpected Homebrew capture output")
                output = bottles[0]
                data = next(iter(json.loads(metadata[0].read_text()).values()))["bottle"]
                tag_data = data["tags"].get(self.brew.tag)
                if not tag_data or tag_data["sha256"] != digest(output):
                    raise PoolError("Captured bottle JSON/tag/checksum mismatch")
                cellar = tag_data.get("cellar", data.get("cellar"))
                if cellar not in (":any", ":any_skip_relocation", "any", "any_skip_relocation"):
                    raise PoolError("Capture is not relocatable; no safe cross-prefix validation")
                archive = BottleImporter(self.client, self.brew)._archive_evidence(output)
                if archive["recipe_sha256"] != evidence["recipe_sha256"] or archive["receipt"].get("built_as_bottle") is not True:
                    raise PoolError("Captured archive recipe/receipt changed")
                isolated.run("uninstall", "--ignore-dependencies", "--formula", info["full_name"], stream=True)
                isolated.run("trust", "--formula", info["full_name"])
                isolated.run("install", "--formula", "--force-bottle", str(output), stream=True,
                             env_extra={"HOMEBREW_DEVELOPER": "1"})
                installed = json.loads(isolated.run("info", "--json=v2", info["full_name"]))["formulae"][0]
                if not any(x.get("version") == evidence["version"] and x.get("poured_from_bottle") for x in installed.get("installed", [])):
                    raise PoolError("Validation did not actually install the captured bottle")
                isolated.run("test", info["full_name"], stream=True)
                isolated.run("linkage", "--test", info["full_name"], stream=True)
                # Byte/context revalidation happens BEFORE any durable/importable artifact.
                if any(tree_hash(path) != before for path, before in snapshots.items()):
                    raise PoolError("Source keg/dependency changed during capture; artifact rejected")
                if self.brew.context(self.brew.info(name)) != evidence["context"]:
                    raise PoolError("Dependency context changed during capture")
                destination = parent / digest(output)
                if destination.is_symlink():
                    raise PoolError("Captured artifact directory is linked")
                destination.mkdir(exist_ok=True)
                target = destination / output.name
                if target.is_symlink():
                    raise PoolError("Captured artifact path is linked")
                if target.exists():
                    if digest(target) != digest(output):
                        raise PoolError("Existing captured artifact differs; never overwrite")
                else:
                    descriptor, temporary_name = tempfile.mkstemp(prefix=".capture-", dir=str(destination))
                    try:
                        with os.fdopen(descriptor, "wb") as destination_stream, output.open("rb") as source_stream:
                            shutil.copyfileobj(source_stream, destination_stream)
                            destination_stream.flush()
                            os.fsync(destination_stream.fileno())
                        if digest(temporary_name) != digest(output):
                            raise PoolError("Capture changed during durable copy")
                        check_stop()
                        os.replace(temporary_name, target)
                    finally:
                        Path(temporary_name).unlink(missing_ok=True)
                tag, rebuild = BottleImporter._tag_and_rebuild(target.name)
                bottle_proof = dict(schema=1, reviewed=True, producer=proof["producer"],
                    sha256=digest(target), formula=info["full_name"], version=evidence["version"],
                    arch="x86_64", tag=tag, rebuild=rebuild, prefix=self.brew.prefix,
                    cellar=self.brew.cellar, recipe_sha256=evidence["recipe_sha256"],
                    dependencies=evidence["context"]["dependencies"], compiler_flags=[],
                    required_cpu_features=proof["required_cpu_features"])
                bottle_proof["capture_validation"] = {
                    "isolated_pour": True, "formula_test": True, "linkage_test": True,
                    "source_receipt_sha256": evidence["receipt_sha256"],
                    "source_keg_tree_sha256": evidence["keg_tree_sha256"],
                    "q9300_compatible": normalized_features(proof["required_cpu_features"]) <= Q9300_FEATURES}
                atomic_json(str(target) + ".pool-provenance.json", bottle_proof)
                candidate = BottleImporter(self.client, self.brew).analyze_archive(target)
                if candidate["classification"] not in ("bottle_valid_importable", "already_present"):
                    raise PoolError(candidate["reason"])
                candidate["manifest"]["metadata"]["capture_validation"] = bottle_proof["capture_validation"]
                # Persist only for explicit later Import to Pool. Never auto-publish capture.
                importer = BottleImporter(self.client, self.brew)
                imports = importer.review() if importer.report_path.exists() else {"schema": 1, "candidates": [], "auto_import": False}
                imports["candidates"] = [x for x in imports["candidates"] if x["id"] != candidate["id"]] + [candidate]
                atomic_json(importer.report_path, imports)
                report.update(classification=candidate["classification"], reason="Captured and validated in isolated Homebrew; not published",
                              artifact=str(target), sha256=digest(target),
                              validation=candidate["manifest"]["metadata"]["capture_validation"])
        except JobStopped:
            report.update(classification="requires_review", reason="Capture stopped before completion; no publication confirmed")
            atomic_json(report_path, report)
            raise
        except (PoolError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
            report.update(classification="requires_review", reason=str(error))
            if isinstance(error, subprocess.CalledProcessError):
                report["diagnostic_details"] = ((error.output or "") + (error.stderr or ""))[-6000:]
        if report["classification"] == "requires_review":
            report["next_steps"] = [
                "Use Compatibility Options to review Core 2 source builds or versioned formula candidates.",
                "A rebuild, a version change or a legacy-source patch needs separate user approval.",
                "Keep this candidate at review; do not edit its Homebrew receipt."]
        atomic_json(report_path, report)
        return report
