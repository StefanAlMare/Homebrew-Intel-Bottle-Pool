"""Structured, non-interactive handoff for decisions that require a person."""
import hashlib
import json
import re

from .common import PoolError

ACTION_MARKER = "HOMEBREW_POOL_ACTION_REQUIRED="


class ActionRequired(PoolError):
    """A safe automatic choice is unavailable; the GUI must ask the user."""

    def __init__(self, reason, *, category="review", subject="", choices=None, detail=""):
        super().__init__(reason)
        self.reason = reason
        self.category = category
        self.subject = subject
        self.choices = choices or [
            {"id": "continue", "label": "Continue"},
            {"id": "skip", "label": "Skip"},
            {"id": "cancel", "label": "Cancel"},
        ]
        self.detail = detail[-4000:]

    def as_dict(self):
        value = {
            "schema": 1,
            "category": self.category,
            "subject": self.subject,
            "reason": self.reason,
            "detail": self.detail,
            "choices": self.choices,
        }
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
        value["id"] = hashlib.sha256(canonical.encode()).hexdigest()[:20]
        return value

    def marker(self):
        return ACTION_MARKER + json.dumps(self.as_dict(), sort_keys=True)


_RULES = (
    ("authentication", re.compile(r"(?:sudo|administrator|authentication|password).{0,80}(?:required|needed|failed|cannot|must)|(?:required|need).{0,80}(?:sudo|administrator|authentication|password)", re.I),
     "Administrator authentication is required. Homebrew Pool will never collect your password."),
    ("conflict", re.compile(r"(?:conflicting files|conflict.{0,40}(?:file|link|package)|already exists|would overwrite|refusing to link|could not symlink)", re.I),
     "A file or package conflict needs an explicit decision."),
    ("license", re.compile(r"(?:accept|agree).{0,80}(?:license|terms)|(?:license|terms).{0,80}(?:accept|agree|confirmation)", re.I),
     "A license or explicit confirmation must be accepted by the user."),
    ("confirmation", re.compile(r"(?:confirmation required|are you sure|requires confirmation|interactive prompt)", re.I),
     "Homebrew requested an explicit confirmation."),
    ("trust", re.compile(r"(?:not trusted|untrusted|requires? explicit trust|must.{0,40}brew trust)", re.I),
     "Homebrew requires explicit trust for this package. Review its source and use brew trust before continuing."),
)


def classify_command_failure(output, subject=""):
    """Return an ActionRequired for recognizable interactive failures."""
    text = output or ""
    if re.search(r"illegal instruction|(?:requires?|needs?|unsupported).{0,80}(?:SSE4[._]2|AVX|CPU instruction)|(?:SSE4[._]2|AVX).{0,80}(?:required|not supported)", text, re.I):
        return ActionRequired("This formula needs CPU compatibility review. Safe alternatives are available.",
            category="cpu_compatibility", subject=subject, detail=text,
            choices=[{"id": "compatibility", "label": "Review Compatibility Options"},
                     {"id": "skip", "label": "Skip This Item"}, {"id": "cancel", "label": "Cancel Run"}])
    for category, pattern, reason in _RULES:
        if pattern.search(text):
            return ActionRequired(reason, category=category, subject=subject, detail=text)
    return None
