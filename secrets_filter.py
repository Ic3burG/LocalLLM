"""Deterministic redaction of secrets/credentials before they are persisted.

The learner subagent and the manual-save endpoint both route through
``write_user_memory`` in ``gemma_bridge``; that function calls
``redact_secrets`` so credentials never land in the (potentially synced/public)
USER_MEMORY.md. This is a stdlib-only module so it can be unit-tested without
importing the bridge's native extensions.

Scope (by design): credentials only. Phone numbers and emails are intentionally
left intact — they are useful contact context, not secrets.
"""

import re

REDACTED = "[REDACTED]"

# Structured, high-confidence secrets.
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_TOKEN_PREFIX = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}"  # OpenAI-style
    r"|gh[posru]_[A-Za-z0-9]{20,}"  # GitHub
    r"|xox[baprs]-[A-Za-z0-9-]{10,})"  # Slack
)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE)
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# password: value  /  password = value  /  password is value
_PASSWORD = re.compile(
    r"\b(password|passwd|pwd|passphrase)(\s*(?:[:=]|is|was)\s*)(\S+)",
    re.IGNORECASE,
)

# OTP / verification codes: only digits that sit next to an explicit
# code-ish phrase, so plain numbers (rates, years, zip/area codes) survive.
_OTP = re.compile(
    r"\b((?:verification|security|access|login|one[\s-]?time|auth(?:entication)?"
    r"|confirmation)\s+code"
    r"|passcode|otp|2fa"
    r"|code(?:\s+is|\s*[:=]))"  # keyword phrase
    r"([^\n\d]{0,15}?)"  # short non-digit gap
    r"(\d{4,8})\b",  # the code itself
    re.IGNORECASE,
)

# Credit-card-like runs of digits; validated with Luhn to avoid redacting
# arbitrary long numbers.
_CC_CANDIDATE = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn_ok(digits: str) -> bool:
    nums = [int(c) for c in digits]
    parity = len(nums) % 2
    total = 0
    for i, d in enumerate(nums):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _redact_cc(match: re.Match) -> str:
    raw = match.group(0)
    digits = re.sub(r"[ -]", "", raw)
    if 13 <= len(digits) <= 19 and _luhn_ok(digits):
        return REDACTED
    return raw


def redact_secrets(text: str) -> str:
    """Replace credential-like substrings with ``[REDACTED]``.

    Leaves the surrounding context (and the labelling keyword) intact so the
    memory stays readable.
    """
    if not text:
        return text
    text = _PRIVATE_KEY.sub(REDACTED, text)
    text = _AWS_KEY.sub(REDACTED, text)
    text = _TOKEN_PREFIX.sub(REDACTED, text)
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    text = _SSN.sub(REDACTED, text)
    text = _PASSWORD.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
    text = _OTP.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
    text = _CC_CANDIDATE.sub(_redact_cc, text)
    return text
