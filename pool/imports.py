"""Discover and publish existing Homebrew bottles without trusting filenames alone."""
import hashlib
import json
import os
import re
import tarfile
import time
import gzip
import posixpath
from pathlib import Path, PurePosixPath

from .client import Lease, RemoteError, Unavailable
from .common import PoolError, atomic_json, canonical, digest
from .processes import check_stop


CPU_LEVELS = {
    "x86_64-v1": set(),
    "x86_64-v2": {"SSE4.2", "SSSE3", "POPCNT", "CX16"},
    "x86_64-v3": {"AVX", "AVX2", "BMI1", "BMI2", "FMA", "MOVBE"},
    "x86_64-v4": {"AVX512F", "AVX512BW", "AVX512CD", "AVX512DQ", "AVX512VL"},
}


def homebrew_baseline_features(tag):
    # Current Homebrew extend/os/mac/hardware.rb: Nehalem before Ventura,
    # Westmere from Ventura on. Neither is safe on a Core 2 Quad Q9300.
    required = {"SSE2", "SSE3", "SSSE3", "SSE4_1", "SSE4_2", "POPCNT", "CX16"}
    if tag in ("ventura", "sonoma", "sequoia", "tahoe"):
        required |= {"AES", "PCLMULQDQ"}
    return required


def normalize_cpu_features(values):
    aliases = {"AVX1_0": "AVX", "AVX2_0": "AVX2", "AESNI": "AES", "PCLMUL": "PCLMULQDQ"}
    normalized = {str(x).upper().replace(".", "_") for x in values}
    return {aliases.get(x, x) for x in normalized}


def cpu_level(features):
    values = normalize_cpu_features(features)
    level = "x86_64-v1"
    accumulated = set()
    for candidate in ("x86_64-v2", "x86_64-v3", "x86_64-v4"):
        accumulated |= CPU_LEVELS[candidate]
        normalized = {value.replace(".", "_") for value in accumulated}
        if normalized <= values:
            level = candidate
        else:
            break
    return level


def supported_cpu_levels(features):
    current = cpu_level(features)
    names = list(CPU_LEVELS)
    return names[:names.index(current) + 1]


class BottleImporter:
    REPORT_SCHEMA = 1
    MAX_ARCHIVES = 5000
    MAX_MEMBERS = 50000
    MAX_METADATA = 2 * 1024 * 1024

    def __init__(self, client, brew):
        self.client = client
        self.brew = brew
        self.report_path = client.state / "imports.json"

    def _host_features(self):
        configured = getattr(self.brew, "cpu_features", None)
        if configured is not None:
            return {str(value).upper() for value in configured}
        output = ""
        for key in ("machdep.cpu.features", "machdep.cpu.leaf7_features"):
            try:
                output += " " + self.brew.run_system("sysctl", "-n", key)
            except Exception:
                pass
        return {value.upper() for value in output.split()}

    @staticmethod
    def _safe_member(member):
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            return False
        if member.issym() or member.islnk():
            target = member.linkname if member.islnk() else posixpath.join(str(path.parent), member.linkname)
            normalized = posixpath.normpath(target)
            return not member.linkname.startswith("/") and normalized != ".." and not normalized.startswith("../")
        return True

    def _archive_evidence(self, path):
        try:
            with tarfile.open(path, "r:gz") as archive:
                members = []
                for member in archive:
                    check_stop()
                    members.append(member)
                    if len(members) > self.MAX_MEMBERS:
                        raise PoolError("oversized archive table")
                if not members or len(members) > self.MAX_MEMBERS or any(not self._safe_member(x) for x in members):
                    raise PoolError("unsafe or oversized archive table")
                receipts = [x for x in members if x.isfile() and x.name.endswith("/INSTALL_RECEIPT.json")]
                recipes = [x for x in members if x.isfile() and "/.brew/" in x.name and x.name.endswith(".rb")]
                if len(receipts) != 1 or len(recipes) != 1:
                    raise PoolError("expected one Homebrew receipt and one embedded formula")
                if receipts[0].size > self.MAX_METADATA or recipes[0].size > self.MAX_METADATA:
                    raise PoolError("archive metadata is too large")
                receipt_stream = archive.extractfile(receipts[0])
                recipe_stream = archive.extractfile(recipes[0])
                if receipt_stream is None or recipe_stream is None:
                    raise PoolError("archive metadata cannot be read")
                receipt = json.loads(receipt_stream.read(self.MAX_METADATA + 1))
                if not isinstance(receipt, dict):
                    raise PoolError("Homebrew receipt must be an object")
                recipe = recipe_stream.read(self.MAX_METADATA + 1)
                parts = PurePosixPath(receipts[0].name).parts
                if len(parts) < 3:
                    raise PoolError("unexpected Homebrew bottle layout")
                root = "/".join(parts[:-1])
                if any(not (x.name.rstrip("/") in (parts[0], root) or x.name.startswith(root + "/")) for x in members):
                    raise PoolError("archive contains files outside its formula keg")
                if not recipes[0].name.startswith(root + "/.brew/"):
                    raise PoolError("embedded recipe is outside the formula keg")
                # Read through the gzip trailer as well: tar headers alone do not
                # verify truncated payloads or gzip CRC integrity.
                with gzip.open(path, "rb") as compressed:
                    total = 0
                    while True:
                        check_stop()
                        chunk = compressed.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > 32 * 1024**3:
                            raise PoolError("uncompressed bottle exceeds verification limit")
                return {"name": parts[-3], "version": parts[-2], "receipt": receipt,
                        "recipe_sha256": hashlib.sha256(recipe).hexdigest()}
        except (tarfile.TarError, OSError, EOFError, ValueError) as error:
            raise PoolError("invalid Homebrew bottle archive: " + str(error)) from error

    def _local_provenance(self, path, evidence, info, checksum, tag, rebuild):
        # Homebrew receipts do not record compiler flags, full CPU requirements,
        # original prefix/Cellar or dependency recipe hashes. Never substitute
        # the scanner's hardware or current graph for those producer facts.
        proof_path = Path(str(path) + ".pool-provenance.json")
        if proof_path.is_symlink() or not proof_path.is_file() or proof_path.stat().st_size > self.MAX_METADATA:
            raise PoolError("Local bottle needs reviewed producer provenance (.pool-provenance.json); CPU/prefix/dependency evidence is incomplete")
        proof = json.loads(proof_path.read_text())
        if not isinstance(proof, dict) or proof.get("schema") != 1 or proof.get("reviewed") is not True:
            raise PoolError("Producer provenance has not been reviewed")
        expected = {"sha256": checksum, "formula": info["full_name"], "version": self.brew.pkg_version(info),
                    "arch": "x86_64", "tag": tag, "rebuild": rebuild,
                    "prefix": self.brew.prefix, "cellar": self.brew.cellar,
                    "recipe_sha256": evidence["recipe_sha256"]}
        if any(proof.get(key) != value for key, value in expected.items()):
            raise PoolError("Producer provenance is incompatible with archive/formula/prefix/Cellar")
        features = proof.get("required_cpu_features")
        if not isinstance(features, list) or not features or any(not isinstance(x, str) or not re.fullmatch(r"[A-Za-z0-9_.]+", x) for x in features):
            raise PoolError("Producer CPU requirements are missing")
        if proof.get("compiler_flags") != [] or not isinstance(proof.get("producer"), str) or not proof["producer"]:
            raise PoolError("Custom compiler flags or unknown producer require separate review")
        required = normalize_cpu_features(features)
        available = normalize_cpu_features(self._host_features())
        if not required <= available:
            raise PoolError("Producer CPU instructions are incompatible with this Mac")
        manifest = self.brew.manifest(info, tag=tag, cpu_requirement=cpu_level(features))
        context = manifest["metadata"]["context"]
        if proof.get("dependencies") != context["dependencies"]:
            raise PoolError("Producer dependency recipe/version context differs from current installed graph")
        receipt = evidence["receipt"]
        runtime = receipt.get("runtime_dependencies")
        if not isinstance(runtime, list):
            raise PoolError("Archive has no runtime dependency evidence")
        archived = {x.get("full_name"): x.get("pkg_version") for x in runtime if isinstance(x, dict)}
        if archived != {name: value["version"] for name, value in context["dependencies"].items()}:
            raise PoolError("Archive dependency versions differ from verified producer context")
        manifest["version_order"][-1] = rebuild
        manifest["metadata"]["bottle_rebuild"] = rebuild
        manifest["metadata"]["bottle_json"] = {"cellar": proof["cellar"], "tag": tag,
                                                  "rebuild": rebuild, "relocatable": False}
        manifest["metadata"]["required_cpu_features"] = sorted(required)
        manifest["metadata"]["producer_provenance"] = proof
        if proof.get("capture_validation"):
            manifest["metadata"]["capture_validation"] = proof["capture_validation"]
        return manifest

    @staticmethod
    def _tag_and_rebuild(filename):
        match = re.search(r"\.([A-Za-z0-9_]+)\.bottle(?:\.(\d+))?\.tar\.gz$", filename)
        if not match:
            raise PoolError("filename has no recognized Homebrew bottle tag")
        return match.group(1), int(match.group(2) or 0)

    def _pool_state(self, manifest):
        try:
            found = self.client.lookup(manifest)
        except Unavailable:
            return "unknown", "Pool unavailable; import can be staged locally"
        if not found:
            return "missing", "Not present in pool"
        if (found["version_order"] == manifest["version_order"]
                and found["sha256"] == manifest["sha256"]
                and found.get("metadata", {}).get("context") == manifest.get("metadata", {}).get("context")):
            return "identical", "Identical verified artifact already present"
        if found["version_order"] == manifest["version_order"]:
            return "conflict", "Same version rank has different bytes or context"
        return "different-version", "Pool contains a different version rank"

    def analyze_archive(self, path):
        path = Path(path)
        result = {"id": "archive:" + hashlib.sha256(str(path).encode()).hexdigest()[:20],
                  "path": str(path), "filename": path.name, "classification": "requires_review"}
        if path.is_symlink() or not path.is_file():
            result["reason"] = "Candidate is not a regular cache file"
            return result
        try:
            check_stop()
            checksum = digest(path)
            evidence = self._archive_evidence(path)
            if digest(path) != checksum:
                raise PoolError("Bottle changed while verifying archive")
            self.brew.validate_name(evidence["name"])
            tag, rebuild = self._tag_and_rebuild(path.name)
            source = evidence["receipt"].get("source")
            if not isinstance(source, dict) or not isinstance(source.get("tap"), str):
                raise PoolError("Archive has no formula tap provenance")
            tap = source["tap"]
            self.brew.validate_name(tap)
            query = evidence["name"] if tap == "homebrew/core" else tap + "/" + evidence["name"]
            self.brew.validate_name(query)
            info = self.brew.info(query)
            self.brew.check_options(info)
            version = self.brew.pkg_version(info)
            if evidence["version"] != version:
                raise PoolError("archive version does not match current formula metadata")
            known_tags = {"big_sur": 11, "monterey": 12, "ventura": 13, "sonoma": 14,
                          "sequoia": 15, "tahoe": 26, "all": 0}
            if tag not in known_tags or known_tags[tag] > self.brew.major:
                result.update(classification="incompatible", reason="Bottle macOS tag is not compatible with this scanner")
                return result
            if evidence["receipt"].get("arch") != "x86_64":
                result.update(classification="incompatible", reason="Archive does not prove Intel x86_64 architecture")
                return result
            if evidence["receipt"].get("used_options") or tap != (info.get("tap") or "homebrew/core"):
                raise PoolError("Archive tap/options do not match current formula")
            official = ((info.get("bottle") or {}).get("stable") or {}).get("files", {}).get(tag)
            if official and official.get("sha256") == checksum:
                available = normalize_cpu_features(self._host_features())
                if tag != "all" and not homebrew_baseline_features(tag) <= available:
                    result.update(classification="incompatible", reason="Official Intel bottle requires Nehalem/Westmere CPU instructions; not Q9300 compatible")
                    return result
                manifest = self.brew.manifest(info, "brew-upstream-bottle", tag, checksum)
                cellar = official.get("cellar")
                if cellar not in (":any", ":any_skip_relocation", "any", "any_skip_relocation", self.brew.cellar):
                    result.update(classification="incompatible", reason="Official bottle Cellar is incompatible")
                    return result
                manifest["metadata"]["bottle_json"] = {
                    "cellar": cellar, "tag": tag,
                    "rebuild": info.get("bottle", {}).get("stable", {}).get("rebuild", 0),
                    "relocatable": cellar in (":any", ":any_skip_relocation", "any", "any_skip_relocation"),
                }
                provenance = "homebrew-official-checksum"
            else:
                if evidence["receipt"].get("built_as_bottle") is not True:
                    result.update(classification="local_source_no_bottle",
                                  reason="Receipt does not confirm a --build-bottle build")
                    return result
                if evidence["recipe_sha256"] != self.brew.planned_installed_recipe_hash(info):
                    result.update(classification="requires_review",
                                  reason="Embedded formula does not match the pinned local recipe")
                    return result
                manifest = self._local_provenance(path, evidence, info, checksum, tag, rebuild)
                provenance = "verified-external-local-bottle"
            manifest.update(filename=path.name, sha256=checksum, size=path.stat().st_size)
            manifest["metadata"]["provenance"] = {
                "kind": provenance, "archive_recipe_sha256": evidence["recipe_sha256"],
                "receipt_built_as_bottle": evidence["receipt"].get("built_as_bottle") is True,
                "arch": evidence["receipt"]["arch"], "tap": tap,
                "scanned_at": int(time.time()),
            }
            state, reason = self._pool_state(manifest)
            classification = "already_present" if state == "identical" else (
                "requires_review" if state == "conflict" else "bottle_valid_importable")
            result.update(classification=classification, reason=reason, sha256=checksum,
                          formula=info["full_name"], version=version, tag=tag,
                          revision=info.get("revision", 0), arch="x86_64",
                          prefix=manifest["metadata"]["context"]["prefix"],
                          cellar=manifest["metadata"]["bottle_json"]["cellar"],
                          cpu_requirement=manifest["metadata"]["context"].get("cpu_requirement", "homebrew-baseline"),
                          relocatable=manifest["metadata"].get("bottle_json", {}).get("cellar") in
                                      (":any", ":any_skip_relocation", "any", "any_skip_relocation"),
                          manifest=manifest)
        except (PoolError, KeyError, OSError, ValueError, TypeError) as error:
            result.update(classification="requires_review", reason=str(error))
        return result

    def scan(self):
        candidates = []
        installed = json.loads(self.brew.run("info", "--json=v2", "--installed")).get("formulae", [])
        for info in installed:
            check_stop()
            for receipt in info.get("installed", []):
                bottled = bool(receipt.get("poured_from_bottle"))
                candidates.append({"id": "installed:" + info["full_name"] + ":" + receipt["version"],
                                   "formula": info["full_name"], "version": receipt["version"],
                                   "classification": "requires_review" if bottled else "local_source_no_bottle",
                                   "reason": "Installed keg has a bottle receipt; a separate verified archive is still required" if bottled else
                                             "Installed from source; no separate verified bottle archive is claimed"})
        cache = Path(self.brew.cache).resolve()
        if cache.is_dir():
            paths = []
            for path in cache.rglob("*.bottle*.tar.gz"):
                check_stop()
                if len(paths) >= self.MAX_ARCHIVES:
                    break
                try:
                    path.resolve().relative_to(cache)
                except (OSError, ValueError):
                    continue
                paths.append(path)
            candidates.extend(self.analyze_archive(path) for path in sorted(paths))
        captures = self.client.state / "captures"
        if captures.is_dir():
            for directory in sorted(captures.iterdir()):
                if directory.is_dir() and not directory.is_symlink() and re.fullmatch(r"[0-9a-f]{64}", directory.name):
                    candidates.extend(self.analyze_archive(path) for path in sorted(directory.glob("*.bottle*.tar.gz")))
        report = {"schema": self.REPORT_SCHEMA, "scanned_at": int(time.time()),
                  "auto_import": bool(self.client.config.get("auto_import_verified_bottles", False)),
                  "candidates": candidates}
        atomic_json(self.report_path, report)
        return report

    def review(self):
        if not self.report_path.exists():
            return self.scan()
        report = json.loads(self.report_path.read_text())
        if report.get("schema") != self.REPORT_SCHEMA:
            raise PoolError("Unsupported import review schema; rescan")
        return report

    @staticmethod
    def format_report(report):
        labels = {"bottle_valid_importable": "Verified — ready to import",
                  "already_present": "Already present in pool",
                  "local_source_no_bottle": "Source installation — no confirmed bottle",
                  "incompatible": "Incompatible", "requires_review": "Needs verification"}
        lines = ["Existing bottles review", "Automatic import: " + ("On" if report.get("auto_import") else "Off"), ""]
        for candidate in report["candidates"]:
            lines += [candidate.get("formula", candidate.get("filename", "Unknown candidate")) + " " + candidate.get("version", ""),
                      labels.get(candidate["classification"], candidate["classification"]),
                      candidate.get("reason", ""), candidate.get("path", ""), ""]
        if not report["candidates"]:
            lines.append("No bottle candidates found.")
        return "\n".join(lines)

    def import_verified(self, identifiers=()):
        report = self.review()
        selected = set(identifiers)
        results = []
        for recorded in report["candidates"]:
            check_stop()
            if selected and recorded["id"] not in selected:
                continue
            if recorded.get("classification") != "bottle_valid_importable":
                continue
            fresh = self.analyze_archive(recorded["path"])
            if fresh.get("classification") == "already_present":
                results.append({"id": fresh["id"], "status": "already_present"})
                continue
            if (fresh.get("classification") != "bottle_valid_importable"
                    or fresh.get("sha256") != recorded.get("sha256")
                    or fresh.get("manifest", {}).get("metadata", {}).get("context") != recorded.get("manifest", {}).get("metadata", {}).get("context")
                    or fresh.get("manifest", {}).get("metadata", {}).get("producer_provenance") != recorded.get("manifest", {}).get("metadata", {}).get("producer_provenance")):
                results.append({"id": recorded["id"], "status": "rejected", "reason": fresh.get("reason", "changed")})
                continue
            manifest = fresh["manifest"]
            entry = self.client.enqueue(manifest, fresh["path"])
            try:
                with Lease(self.client, manifest, wait_seconds=0) as lease:
                    if not lease.token:
                        results.append({"id": fresh["id"], "status": "spooled_busy"})
                        continue
                    outcome = self.client.publish_entry(entry, lease)
                    results.append({"id": fresh["id"], "status": outcome["status"]})
            except Unavailable:
                results.append({"id": fresh["id"], "status": "spooled_offline"})
            except RemoteError as error:
                results.append({"id": fresh["id"], "status": "rejected", "reason": str(error)})
        return results
