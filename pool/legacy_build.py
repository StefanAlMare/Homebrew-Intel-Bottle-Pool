"""Reviewed source-build requests on explicitly enrolled dedicated builders.

No builds are executed during packaging/testing. A build cannot approve itself:
the output requires isolated pour + ISA review + whole-manifest administrator
approval before the private client or server will accept it.
"""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .common import digest
from .legacy import (authenticate, load_policy, observe_host, plan_for, private_write,
                     require)
from .legacy_policy import (LegacyGate, TARGETS, canonical, features, formula_name,
                            is_hash, sha)


def review_request(client, request):
    p = load_policy(client.policy_file)
    session = authenticate(p, "Bearer " + client.token)
    require(session["machine_id"] == client.config["machine_id"], "wrong builder credential")
    host = client.host_provider(client.config)
    enrolled, available = LegacyGate(p)._machine(session["machine_id"], "build", host, session)
    require(enrolled.get("dedicated_build_host") is True and client.config.get("allow_builds") is True,
            "source builds require an explicitly enrolled dedicated builder")
    require(request.get("schema") == 1 and request.get("pool_id") == p["pool_id"] and
            request.get("machine_id") == session["machine_id"] and
            request.get("policy_revision") == p["revision"], "build request identity differs")
    require(formula_name(request["name"]), "fully qualified formula required")
    require(request["context"] == host["context"], "build context differs")
    require(request["cpu_target"] in TARGETS, "unreviewed build CPU target")
    required = features(request["required_cpu_features"])
    _, minimum, ceiling = TARGETS[request["cpu_target"]]
    require(minimum <= required <= ceiling and required <= available, "incompatible build ISA")
    LegacyGate(p)._dependencies(request["dependencies"], available)
    for key in ("version", "compiler"):
        require(isinstance(request[key], str) and bool(request[key]), "missing build identity")
    for key in ("revision", "rebuild"):
        require(type(request[key]) is int and request[key] >= 0, "invalid build version rank")
    files = {request["formula_file"]: request["formula_sha256"],
             request["toolchain_file"]: request["toolchain_sha256"],
             request["sdk_manifest_file"]: request["sdk_sha256"]}
    require(isinstance(request["source_files"], dict) and bool(request["source_files"]) and
            isinstance(request["patch_files"], dict), "source and patch inventory required")
    for inventory in (request["source_files"], request["patch_files"]):
        for path, checksum in inventory.items():
            require(path not in files or files[path] == checksum, "conflicting build input identity")
            files[path] = checksum
    for path, checksum in files.items():
        candidate = Path(path)
        require(candidate.is_absolute() and candidate.is_file() and not candidate.is_symlink() and
                is_hash(checksum) and digest(candidate) == checksum, "reviewed build input changed")
    require(Path(request["formula_file"]).suffix == ".rb", "local Ruby formula file required")
    flags = request["flags"]
    require(isinstance(flags, dict) and set(flags) == {"cflags", "cxxflags", "ldflags"}, "exact flags required")
    for values in flags.values():
        require(isinstance(values, list) and all(isinstance(x, str) for x in values), "invalid build flags")
        require(not any(x in ("-march=native", "-mtune=native", "-mpopcnt", "-msse4.2")
                        or x.startswith("-mavx") for x in values), "unsafe Core 2 flags")
    review = p.get("build_reviews", {}).get(sha(request))
    require(isinstance(review, dict) and review.get("status") == "approved" and
            review.get("reviewer_key_id") in p["reviewer_keys"] and
            review.get("policy_revision") == p["revision"], "exact build request lacks administrative approval")
    brew = Path(client.config["brew"])
    target = "core2" if request["cpu_target"] == "conroe-merom" else "penryn"
    commands = [[str(brew), "install", "--formula", "--ignore-dependencies", "--build-from-source",
                 "--build-bottle", "--bottle-arch=" + target, request["formula_file"]],
                [str(brew), "bottle", "--json", "--keep-old", request["name"]],
                [str(brew), "test", request["name"]],
                [str(brew), "linkage", "--test", request["name"]]]
    return {"commands": commands, "request_sha256": sha(request), "host": host,
            "requires_current_repository_authorization": True,
            "publication": "blocked until independent artifact review"}


def check_dependencies(client, request):
    from .capture import tree_hash
    for graph in request["dependencies"].values():
        for name, dep in graph.items():
            version = dep["version"]
            require(isinstance(version, str) and version not in (".", "..") and "/" not in version,
                    "unsafe dependency version")
            base = name.split("/")[-1]
            keg = Path(client.config["cellar"]) / base / version
            recipe = keg / ".brew" / (base + ".rb")
            require(keg.is_dir() and not keg.is_symlink() and not recipe.is_symlink() and
                    digest(recipe) == dep["recipe_sha256"] and tree_hash(keg) == dep["keg_tree_sha256"],
                    "build dependency absent or changed; automatic installation is prohibited")


def build(client, request, repository_authorized=False):
    require(repository_authorized is True, "source build requires explicit current repository-access authorization")
    reviewed = review_request(client, request)
    brew = Path(client.config["brew"])
    require(brew.is_absolute() and brew.is_file() and os.access(brew, os.X_OK), "explicit builder Homebrew executable required")
    formula_cellar = Path(client.config["cellar"]) / request["name"].split("/")[-1]
    require(not formula_cellar.exists() and not formula_cellar.is_symlink(),
            "target already exists; existing installations are never rebuilt or replaced")
    check_dependencies(client, request)
    builds = client.state / "builds"; builds.mkdir(exist_ok=True, mode=0o700)
    require(not builds.is_symlink(), "linked build state denied")
    output = Path(tempfile.mkdtemp(prefix="build-", dir=builds))
    private_write(output / "request.json", request)
    log_path = output / "build.log"
    env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_INSTALL_CLEANUP="1",
               HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK="1", HOMEBREW_NO_ASK="1",
               HOMEBREW_DEVELOPER="1", HOMEBREW_NO_INSTALL_FROM_API="1")
    for key in ("CFLAGS", "CXXFLAGS", "LDFLAGS", "HOMEBREW_OPTFLAGS", "HOMEBREW_ARCH"):
        env.pop(key, None)
    for key, values in zip(("CFLAGS", "CXXFLAGS", "LDFLAGS"),
                            (request["flags"]["cflags"], request["flags"]["cxxflags"], request["flags"]["ldflags"])):
        if values: env[key] = " ".join(values)
    with open(log_path, "xb") as log:
        os.chmod(log_path, 0o600)
        # Query the explicitly approved builder only after per-operation consent.
        for flag, expected in (("--prefix", client.config["prefix"]), ("--cellar", client.config["cellar"])):
            value = subprocess.run([str(brew), flag], env=env, capture_output=True, text=True, check=True).stdout.strip()
            require(value == expected, "actual builder paths differ from reviewed context")
        for command in reviewed["commands"]:
            review_request(client, request); check_dependencies(client, request)
            log.write(canonical({"argv": command}) + b"\n"); log.flush()
            subprocess.run(command, cwd=output, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    review_request(client, request); check_dependencies(client, request)
    bottles = list(output.glob("*.bottle*.tar.gz"))
    require(len(bottles) == 1, "unexpected bottle output; preserve build for review")
    bottle = bottles[0]
    from .imports import BottleImporter
    parser = BottleImporter.__new__(BottleImporter)
    evidence = parser._archive_evidence(bottle)
    require(evidence["name"] == request["name"].split("/")[-1] and
            evidence["version"] == request["version"] + ("_" + str(request["revision"]) if request["revision"] else ""),
            "actual build version differs from request")
    source_inventory = sorted(request["source_files"].values())
    receipt = evidence["receipt"]
    require(receipt.get("built_as_bottle") is True, "source receipt does not confirm bottle build")
    from .capture import tree_hash
    keg = formula_cellar / evidence["version"]
    manifest = {"schema": 2, "channel": "core2-legacy", "pool_id": request["pool_id"],
        "policy_revision": request["policy_revision"], "kind": "brew-local-bottle",
        "name": request["name"], "version": request["version"], "revision": request["revision"],
        "rebuild": request["rebuild"], "filename": bottle.name, "sha256": digest(bottle), "size": bottle.stat().st_size,
        "context": request["context"], "cpu_target": request["cpu_target"],
        "required_cpu_features": request["required_cpu_features"], "dependencies": request["dependencies"],
        "recipe_sha256": request["formula_sha256"], "embedded_recipe_sha256": evidence["recipe_sha256"],
        "provenance": {"producer_machine_id": request["machine_id"],
            "producer_key_id": load_policy(client.policy_file)["machines"][request["machine_id"]]["key_id"],
            "producer_target": reviewed["host"]["cpu_target"], "recipe_sha256": request["formula_sha256"],
            "embedded_recipe_sha256": evidence["recipe_sha256"], "source_sha256": sha(source_inventory),
            "patches_sha256": sorted(request["patch_files"].values()), "toolchain_sha256": request["toolchain_sha256"],
            "sdk_sha256": request["sdk_sha256"], "compiler": request["compiler"], "flags": request["flags"],
            "flags_evidence": "requested-only; compiler invocations require independent review",
            "build_log_sha256": digest(log_path), "receipt_sha256": digest(keg / "INSTALL_RECEIPT.json"),
            "keg_tree_sha256": tree_hash(keg), "dependency_digest": sha(request["dependencies"]),
            "build_argv": reviewed["commands"][0]},
        "validation": {"formula_test": True, "linkage_test": True, "isolated_pour": False,
            "isa_review": False, "machine_id": request["machine_id"], "report_sha256": digest(log_path)}}
    private_write(output / "candidate-manifest.json", manifest)
    private_write(output / "candidate-plan.json", plan_for(manifest))
    return {"state": "requires-review", "output": str(output), "published": False,
            "message": "Build completed. Independent isolated pour, native ISA review and whole-manifest approval are still required."}
