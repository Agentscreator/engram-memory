"""Deterministic secret detection — regex scanner for commit-time rejection.

Runs in <1ms. Catches common secret patterns. This is enforcement, not advisory.
"""

from __future__ import annotations

import re

# Patterns adapted from common secret scanners (truffleHog, detect-secrets)
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # API Keys & Tokens
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("AWS Secret Key", re.compile(r"(?i)aws[_\-]?secret[_\-]?access[_\-]?key\s*[:=]\s*\S{20,}")),
    (
        "AWS Session Token",
        re.compile(r"(?i)aws[_\-]?session[_\-]?token\s*[:=]\s*['\"]?[A-Za-z0-9+/=]{50,}"),
    ),
    ("Generic API Key (sk-...)", re.compile(r"\bsk-[a-zA-Z0-9]{20,}\b")),
    ("Generic API Key (key-...)", re.compile(r"\bkey-[a-zA-Z0-9]{20,}\b")),
    ("Bearer Token", re.compile(r"Bearer\s+[a-zA-Z0-9\-._~+/]+=*", re.IGNORECASE)),
    ("JWT Token", re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b")),
    ("Private Key Header", re.compile(r"-----BEGIN\s+(RSA|EC|DSA|OPENSSH)?\s*PRIVATE KEY-----")),
    ("Connection String", re.compile(r"(?i)(mongodb|postgres|mysql|redis|amqp)://\S+:\S+@\S+")),
    ("GitHub Token", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36,}\b")),
    ("Slack Token", re.compile(r"\bxox[bpors]-[a-zA-Z0-9\-]{10,}\b")),
    ("Google API Key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    (
        "Google OAuth Client ID",
        re.compile(r"\b[0-9]+-[0-9A-Za-z_]{30}\.apps\.googleusercontent\.com\b"),
    ),
    ("Stripe Secret Key", re.compile(r"\b(?:sk|pk)_(?:test|live)_[0-9a-zA-Z]{24,}\b")),
    (
        "OAuth Refresh Token",
        re.compile(r"(?i)(refresh[_\-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}['\"]?"),
    ),
    (
        "OAuth Client Secret",
        re.compile(r"(?i)(client[_\-]?secret)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}['\"]?"),
    ),
    (
        "Generic Password Assignment",
        re.compile(r"(?i)(password|passwd|pwd|secret|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
    ),
    (
        "High-Entropy Secret Value",
        re.compile(
            r"(?i)(secret|token|auth)[_\-]?(key|token|secret)\s*[:=]\s*['\"]?[A-Za-z0-9+/=]{32,}['\"]?"
        ),
    ),
    # IP Addresses
    (
        "Private IP Address (10.x.x.x)",
        re.compile(
            r"\b10\.(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){2}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
        ),
    ),
    (
        "Private IP Address (192.168.x.x)",
        re.compile(
            r"\b192\.168\.(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.)(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
        ),
    ),
    (
        "Private IP Address (172.16-31.x.x)",
        re.compile(
            r"\b172\.(?:(?:1[6-9]|2[0-9]|3[01])\.)(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.)(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
        ),
    ),
    # PII Patterns (Issue #82)
    ("Email Address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")),
    (
        "US Phone Number",
        re.compile(r"\b(\+1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b"),
    ),
    ("SSN (US)", re.compile(r"\b[0-9]{3}[-\s]?[0-9]{2}[-\s]?[0-9]{4}\b")),
    ("Credit Card Number", re.compile(r"\b(?:[0-9]{4}[-\s]?){3}[0-9]{4}\b")),
    # IP Addresses (Issue extended patterns)
    ("Private IP Address (10.x.x.x)", re.compile(r"\b10\.(?:[0-9]{1,3}\.){2}[0-9]{1,3}\b")),
    ("Private IP Address (192.168.x.x)", re.compile(r"\b192\.168\.(?:[0-9]{1,3}\.)[0-9]{1,3}\b")),
    (
        "Private IP Address (172.16-31.x.x)",
        re.compile(r"\b172\.(?:(?:1[6-9]|2[0-9]|3[0-1]))\.(?:[0-9]{1,3}\.)[0-9]{1,3}\b"),
    ),
    (
        "Public IP Address",
        re.compile(
            r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
        ),
    ),
    # OAuth & Client Secrets
    (
        "OAuth Refresh Token",
        re.compile(r"(?i)(refresh[_\-]?token)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{20,}['\"]?"),
    ),
    ("OAuth Client Secret", re.compile(r"(?i)(client[_\-]?secret)\s*[:=]\s*['\"]?\S{16,}['\"]?")),
    ("Google OAuth Access Token", re.compile(r"\bya29\.[a-zA-Z0-9_\-]{50,}\b")),
    # AWS Session Tokens
    ("AWS Session Token", re.compile(r"(?i)aws[_\-]?session[_\-]?token\s*[:=]\s*\S{100,}")),
    # Google API Keys
    ("Google API Key", re.compile(r"\bAIza[0-9A-Za-z_-]{35,}\b")),
    (
        "Google OAuth Client ID",
        re.compile(r"\b[0-9]+-[a-zA-Z0-9_]{30,}\.apps\.googleusercontent\.com\b"),
    ),
    # Stripe Keys
    ("Stripe Secret Key", re.compile(r"\b(?:sk|pk)_(?:test|live)_[a-zA-Z0-9]{24,}\b")),
    ("Stripe Restricted Key", re.compile(r"\b(?:sk|pk)_(?:test|live)_[a-zA-Z0-9]{24,}\b")),
    # Generic High-Entropy Secrets
    (
        "Generic High-Entropy Secret",
        re.compile(r"(?i)(secret|token|key|auth)\s*[:=]\s*['\"]?[a-zA-Z0-9+/]{32,}={0,2}['\"]?"),
    ),
]


def scan_for_secrets(content: str) -> str | None:
    """Scan content for secret patterns.

    Returns a description of the first match found, or None if clean.
    """
    for name, pattern in _SECRET_PATTERNS:
        match = pattern.search(content)
        if match:
            # Skip false positives for credit card (basic Luhn check)
            if name == "Credit Card Number":
                if not _is_valid_luhn(match.group().replace("-", "").replace(" ", "")):
                    continue
            # Show a truncated preview so the user knows what triggered it
            snippet = match.group()
            if len(snippet) > 20:
                snippet = snippet[:10] + "..." + snippet[-5:]
            return f"{name} (pattern: {snippet})"
    return None


def _is_valid_luhn(card_number: str) -> bool:
    """Validate credit card number using Luhn algorithm."""
    if not card_number.isdigit():
        return False
    digits = [int(d) for d in card_number]
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    checksum = sum(odd_digits)
    for d in even_digits:
        checksum += sum(divmod(d * 2, 10))
    return checksum % 10 == 0
