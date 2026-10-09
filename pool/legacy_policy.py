"""Offline reference gate. No Homebrew, network, repository or live config writes.

Trust inputs: administrator policy, authenticated transport session, freshly
collected enrolled hardware facts, and an independently pinned install plan.
This module does NOT collect hardware, authenticate sessions or integrate Pool.
An administrator's review ledger pins the WHOLE manifest, not reviewed=True.
"""
import hashlib
import json
import os
import re
import stat

CHANNEL = "core2-legacy"
BASE = frozenset({"SSE2", "SSE3", "SSSE3", "CX16"})
COMMON = BASE | {"FPU", "MMX", "SSE", "FXSR", "CMOV", "CX8", "LAHF_SAHF"}
TARGETS = {
    "conroe-merom": (15, BASE, COMMON),
    "penryn": (23, BASE | {"SSE4_1"}, COMMON | {"SSE4_1"}),
}
OPERATIONS = {
    "lease": "publish",
    "lookup": "consume", "fetch": "consume", "select": "consume",
    "server-read": "consume", "enqueue": "publish", "upload": "publish",
    "server-commit": "publish",
}
PAYLOAD_OPERATIONS = {"select", "enqueue", "upload", "server-commit"}


class Denied(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Denied(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def is_hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def features(values):
    require(isinstance(values, list) and bool(values), "missing ISA evidence")
    require(all(isinstance(x, str) and re.fullmatch(r"[A-Za-z0-9_.]+", x)
                for x in values), "malformed ISA evidence")
    aliases = {"AVX1_0": "AVX", "AVX2_0": "AVX2", "AESNI": "AES",
               "PCLMUL": "PCLMULQDQ", "CMPXCHG16B": "CX16"}
    return {aliases.get(x.upper().replace(".", "_"), x.upper().replace(".", "_"))
            for x in values}


def formula_name(value):
    return (isinstance(value, str) and
            re.fullmatch(r"[a-z0-9][a-z0-9_+@.-]*/[a-z0-9][a-z0-9_+@.-]*/[a-z0-9][a-z0-9_+@.-]*", value)
            is not None and all(x not in (".", "..") for x in value.split("/")))


def manifest_digest(manifest):
    return sha(manifest)


def artifact_key(manifest):
    """Immutable, channel-scoped identity; includes ISA and complete provenance."""
    require(manifest.get("schema") == 2 and manifest.get("channel") == CHANNEL,
            "legacy identity requires schema 2 and explicit channel")
    return sha({"domain": "homebrew-pool-core2-v2", "manifest": manifest})


def reject_legacy_on_global(manifest):
    """New global boundary: old/unlabelled manifests require manual migration."""
    require(manifest.get("schema") == 2 and manifest.get("channel") == "global",
            "global boundary rejects legacy/unlabelled manifests")
    metadata = manifest.get("metadata", {})
    require(isinstance(metadata, dict), "malformed metadata")
    context = metadata.get("context", {})
    require(isinstance(context, dict), "malformed context")
    require(not any(k in manifest or k in metadata for k in
                    ("cpu_target", "legacy_provenance", "core2_legacy")),
            "legacy payload cannot be relabelled global")
    require(context.get("cpu_requirement") not in ("core2", "penryn", "x86_64-v1"),
            "old legacy CPU marker requires review")


def verify_payload(path, manifest):
    """Read only a regular, unlinked final component, checking change during read.

    Integration must consume an immutable staged copy and verify it again just
    before pour. This check cannot freeze a caller's writable pathname.
    """
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode), "payload must be a regular file")
        require(before.st_size == manifest["size"], "payload size mismatch")
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        after = os.fstat(stream.fileno())
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                 before.st_ctime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                 after.st_ctime_ns), "payload changed during verification")
        require(digest.hexdigest() == manifest["sha256"], "payload checksum mismatch")


class LegacyGate:
    def __init__(self, policy):
        # A private JSON copy prevents caller-side mutation of trusted inputs.
        self.policy = json.loads(canonical(policy))

    def _machine(self, machine_id, role, host=None, session=None):
        p = self.policy
        enrolled = p["machines"].get(machine_id)
        require(isinstance(enrolled, dict) and enrolled.get("enabled") is True,
                "machine is not explicitly enrolled")
        require(role in enrolled.get("roles", []), "machine role denied")
        require(enrolled.get("platform_kind") == "hackintosh" and
                is_hash(enrolled.get("native_evidence_sha256")),
                "reviewed native Hackintosh evidence required")
        target = enrolled.get("cpu_target")
        require(target in TARGETS, "unreviewed CPU family")
        model, minimum, ceiling = TARGETS[target]
        cpu = enrolled["cpu"]
        require(cpu == {"vendor": "GenuineIntel", "family": 6, "model": model},
                "enrolled CPU identity contradicts target")
        native = features(enrolled["native_features"])
        require(minimum <= native, "native ISA evidence incomplete")
        # Extra/emulated instructions never expand the reviewed Core 2 ceiling.
        safe = native & ceiling
        require(enrolled["context"]["arch"] == "x86_64", "non-Intel enrollment")
        if session is not None:
            require(session.get("machine_id") == machine_id and
                    session.get("key_id") == enrolled["key_id"],
                    "authenticated session does not match enrollment")
        if host is not None:
            require(host["machine_id"] == machine_id and host["cpu"] == cpu,
                    "observed hardware differs from enrollment")
            require(host["cpu_target"] == target, "observed CPU target differs")
            require(host["context"] == enrolled["context"], "host context changed")
            # Hardware and process must both be native Intel, never Rosetta.
            require(host["native_arch"] == "x86_64" and host["process_arch"] == "x86_64",
                    "native/process architecture mismatch")
            require(host["translated"] is False, "translated process denied")
            safe &= features(host["observed_features"])
            require(minimum <= safe, "observed ISA incomplete")
        return enrolled, safe

    def _dependencies(self, dependencies, available):
        require(isinstance(dependencies, dict) and
                set(dependencies) == {"runtime", "build", "test"},
                "complete dependency scopes required")
        for graph in dependencies.values():
            require(isinstance(graph, dict), "invalid dependency graph")
            for name, dep in graph.items():
                require(formula_name(name), "invalid dependency name")
                require(isinstance(dep, dict) and isinstance(dep["version"], str)
                        and bool(dep["version"]), "invalid dependency version")
                for key in ("recipe_sha256", "keg_tree_sha256", "abi_sha256",
                            "artifact_key", "review_sha256"):
                    require(is_hash(dep[key]), "missing dependency identity: " + key)
                require(dep["channel"] in ("global", CHANNEL), "unknown dependency channel")
                require(features(dep["required_cpu_features"]) <= available,
                        "dependency ISA exceeds this host")

    def authorize(self, manifest, host, session, operation, expected, payload=None):
        """A denial returns no key. No fallback to the global Pool is permitted."""
        try:
            return self._authorize(manifest, host, session, operation, expected, payload)
        except Denied:
            raise
        except (KeyError, TypeError, ValueError, OSError, AttributeError,
                OverflowError, RecursionError) as error:
            raise Denied("missing, malformed or unreadable evidence") from error

    def _authorize(self, m, host, session, operation, expected, payload):
        p = self.policy
        require(p.get("schema") == 2 and p.get("channel") == CHANNEL and
                p.get("enabled") is True, "legacy channel is disabled")
        require(p.get("auto_import_verified_bottles") is False,
                "automatic imports must remain explicitly OFF")
        require(operation in OPERATIONS, "unknown operation")
        require(isinstance(p["pool_id"], str) and bool(p["pool_id"]), "missing pool ID")
        require(type(p["revision"]) is int and p["revision"] > 0, "invalid policy revision")
        enrolled, available = self._machine(session["machine_id"], OPERATIONS[operation], host, session)
        require(m.get("schema") == 2 and m.get("channel") == CHANNEL and
                m.get("pool_id") == p["pool_id"], "wrong schema/channel/pool")
        require(m["policy_revision"] == p["revision"], "stale policy revision")
        require(m["kind"] == "brew-local-bottle", "only rebuilt formula bottles accepted")
        require(formula_name(m["name"]), "fully qualified formula name required")
        require(isinstance(m["version"], str) and bool(m["version"]), "missing version")
        require(type(m["revision"]) is int and m["revision"] >= 0 and
                type(m["rebuild"]) is int and m["rebuild"] >= 0, "invalid revision/rebuild")
        require(is_hash(m["sha256"]) and m["sha256"] != "0" * 64 and
                type(m["size"]) is int and m["size"] > 0, "missing artifact checksum/size")
        require(m["context"] == host["context"] and set(m["context"]) ==
                {"arch", "macos_version", "macos_build", "prefix", "cellar"},
                "exact macOS/prefix/Cellar context required")
        for field in ("prefix", "cellar"):
            value = m["context"][field]
            require(isinstance(value, str) and value.startswith("/") and
                    os.path.normpath(value) == value, "invalid absolute context path")
        for field in ("macos_version", "macos_build"):
            require(isinstance(m["context"][field], str) and bool(m["context"][field])
                    and m["context"][field] != "all", "missing exact macOS identity")
        require(m["cpu_target"] in TARGETS, "unknown artifact CPU target")
        _, minimum, ceiling = TARGETS[m["cpu_target"]]
        required = features(m["required_cpu_features"])
        require(minimum <= required <= ceiling and required <= available,
                "artifact ISA/CPU target incompatible")
        self._dependencies(m["dependencies"], available)
        # expected is an independent local plan, not reconstructed from m.
        fields = ("name", "version", "revision", "rebuild", "context", "dependencies",
                  "recipe_sha256", "embedded_recipe_sha256")
        require(isinstance(expected, dict) and set(expected) == set(fields),
                "independent pinned plan required")
        require(all(m[k] == expected[k] for k in fields), "recipe/dependency plan differs")
        for key in ("recipe_sha256", "embedded_recipe_sha256"):
            require(is_hash(m[key]), "missing recipe hash")
        proof = m["provenance"]
        producer, producer_isa = self._machine(proof["producer_machine_id"], "publish")
        require(proof["producer_key_id"] == producer["key_id"], "producer key differs")
        require(producer["context"] == m["context"] and required <= producer_isa,
                "producer context/ISA differs")
        require(proof["producer_target"] == producer["cpu_target"], "producer target differs")
        if OPERATIONS[operation] == "publish":
            require(proof["producer_machine_id"] == session["machine_id"],
                    "publication must authenticate the producer")
        for key in ("source_sha256", "build_log_sha256", "sdk_sha256",
                    "toolchain_sha256", "receipt_sha256", "keg_tree_sha256"):
            require(is_hash(proof[key]), "missing provenance hash: " + key)
        require(proof["recipe_sha256"] == m["recipe_sha256"] and
                proof["embedded_recipe_sha256"] == m["embedded_recipe_sha256"],
                "producer recipe differs")
        require(proof["dependency_digest"] == sha(m["dependencies"]), "producer graph differs")
        require(isinstance(proof["patches_sha256"], list) and
                all(is_hash(x) for x in proof["patches_sha256"]), "invalid patch evidence")
        require(isinstance(proof["compiler"], str) and bool(proof["compiler"]), "missing compiler identity")
        require(isinstance(proof["build_argv"], list) and
                all(isinstance(x, str) for x in proof["build_argv"]) and
                "--build-bottle" in proof["build_argv"], "missing source-build evidence")
        require(isinstance(proof["flags"], dict) and set(proof["flags"]) ==
                {"cflags", "cxxflags", "ldflags"}, "missing exact compiler flags")
        for flags in proof["flags"].values():
            require(isinstance(flags, list) and all(isinstance(x, str) for x in flags),
                    "invalid compiler flags")
            require(not any(x in ("-march=native", "-mtune=native", "-mpopcnt", "-msse4.2")
                            or x.startswith("-mavx") for x in flags), "unsafe Core 2 flags")
        validation = m["validation"]
        for key in ("isolated_pour", "formula_test", "linkage_test", "isa_review"):
            require(validation[key] is True, "validation incomplete: " + key)
        tester, tester_isa = self._machine(validation["machine_id"], "test")
        require(tester["context"] == m["context"] and
                tester["cpu_target"] == m["cpu_target"] and required <= tester_isa,
                "validation lacks a machine at the declared CPU target")
        require(is_hash(validation["report_sha256"]), "missing validation report hash")
        review = p["reviews"].get(manifest_digest(m))
        require(isinstance(review, dict) and review.get("status") == "approved" and
                review.get("policy_revision") == p["revision"] and
                review.get("reviewer_key_id") in p["reviewer_keys"],
                "whole manifest lacks an administrator-pinned approval")
        if operation in PAYLOAD_OPERATIONS:
            require(payload is not None, "verified payload required")
            verify_payload(payload, m)
        return artifact_key(m)
