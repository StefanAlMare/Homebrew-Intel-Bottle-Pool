"""Read-only alternatives; never silently downgrade, patch or select a Git branch."""
from .common import PoolError
from .imports import normalize_cpu_features, homebrew_baseline_features


def solutions(brew, name):
    brew.validate_name(name)
    info = brew.info(name)
    available = normalize_cpu_features(brew.host_cpu_features())
    baseline = homebrew_baseline_features(brew.tag)
    candidates = []
    for candidate in info.get("versioned_formulae", []):
        brew.validate_name(candidate)
        try:
            record = brew.info(candidate)
            candidates.append({"formula": record["full_name"], "version": brew.pkg_version(record),
                               "disabled": bool(record.get("disabled")),
                               "deprecated": bool(record.get("deprecated")),
                               "cpu_verified": False,
                               "status": "not recommended: disabled" if record.get("disabled") else
                                         "security/support review needed" if record.get("deprecated") else
                                         "candidate only: CPU/macOS/dependency validation required"})
        except (PoolError, OSError, KeyError, ValueError):
            candidates.append({"formula": candidate, "cpu_verified": False, "status": "metadata unavailable; review required"})
    return {"formula": info["full_name"], "missing_baseline_features": sorted(baseline - available),
            "core2_build_target_available": {"SSE2", "SSE3", "SSSE3", "CX16"} <= available,
            "versioned_candidates": candidates,
            "options": [
                "Use an artifact already verified for this exact CPU, macOS, prefix and dependency context.",
                "Use the private Core2 Legacy build-plan on an explicitly enrolled dedicated builder. Source builds need current repository-access authorization and native CPU validation; upstream minimum requirements may still prevent them.",
                "Review a supported versioned formula listed below. A Python formula version is not a Git branch. Older does not automatically mean compatible or secure.",
                "If upstream removed legacy CPU support, a reviewed source patch or separate legacy tap is a new task requiring approval.",
                "Keep the queue paused or explicitly skip this item; never replace a dependency or downgrade silently."],
            "mutations_performed": False}


def format_solutions(report):
    lines = ["Compatibility options — " + report["formula"], "",
             "Missing bottle baseline instructions: " + (", ".join(report["missing_baseline_features"]) or "none"),
             "A successful test on a newer Intel Mac does not prove Core 2 compatibility.", ""]
    lines += [str(n) + ". " + option for n, option in enumerate(report["options"], 1)]
    lines += ["", "Versioned formula candidates (NOT yet CPU-verified):"]
    lines += [x["formula"] + " " + x.get("version", "") + " — " + x["status"] for x in report["versioned_candidates"]]
    if not report["versioned_candidates"]:
        lines.append("No versioned alternatives are declared by the current formula metadata.")
    return "\n".join(lines)
