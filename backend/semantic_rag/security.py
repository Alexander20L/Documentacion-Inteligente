from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from .models import FindingSeverity, PublicationPolicy, ScanResult, SecurityFinding


DEFAULT_DENY_GLOBS = (
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.crt",
    "*.cer",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "*credential*",
    "*credentials*",
    "*secrets*",
    "*.jks",
    "*.keystore",
    "*.dump",
    "*.bak",
)


@dataclass(frozen=True)
class _SecretPattern:
    name: str
    expression: re.Pattern[str]


_SECRET_PATTERNS = (
    _SecretPattern("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    _SecretPattern("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    _SecretPattern("github_token", re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b")),
    _SecretPattern("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    _SecretPattern(
        "assigned_secret",
        re.compile(
            r"(?im)(?P<prefix>\b(?:[a-z0-9]+[_-])?(?:api[_-]?key|secret|password|passwd|token)\s*[:=]\s*)"
            r"(?P<quote>[\"'`])(?P<secret>[^\r\n]{8,}?)(?P=quote)"
        ),
    ),
    _SecretPattern(
        "assigned_secret_unquoted",
        re.compile(
            r"(?im)(?P<prefix>^\s*(?:[a-z0-9]+[_-])?(?:api[_-]?key|secret|password|passwd|token)\s*[:=]\s*)"
            r"(?P<secret>[A-Za-z0-9_./+:=-]{8,})(?=\s*(?:#.*)?$)"
        ),
    ),
)


class SecurityScanner:
    def __init__(self, *, excludes: tuple[str, ...] = (), deny_globs: tuple[str, ...] = DEFAULT_DENY_GLOBS) -> None:
        self.excludes = excludes
        self.deny_globs = deny_globs

    @staticmethod
    def _matches(path: str, patterns: tuple[str, ...]) -> str | None:
        normalized = str(PurePosixPath(path.replace("\\", "/")))
        while normalized.startswith("./"):
            normalized = normalized[2:]
        basename = PurePosixPath(normalized).name
        for pattern in patterns:
            folded_pattern = pattern.casefold()
            if fnmatch.fnmatchcase(normalized.casefold(), folded_pattern) or fnmatch.fnmatchcase(basename.casefold(), folded_pattern):
                return pattern
        return None

    def scan(self, path: str, text: str) -> ScanResult:
        excluded_by = self._matches(path, self.excludes)
        denied_by = excluded_by or self._matches(path, self.deny_globs)
        if denied_by:
            code = "configured_exclusion" if excluded_by else "denied_file"
            finding = SecurityFinding(
                code=code,
                severity=FindingSeverity.CRITICAL,
                path=path,
                pattern=denied_by,
                message="File excluded by security policy",
            )
            return ScanResult(allowed=False, policy=PublicationPolicy.EXCLUDE, findings=(finding,))

        findings: list[SecurityFinding] = []
        redacted = text
        code_suffixes = {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx"}
        suffix = PurePosixPath(path.replace("\\", "/")).suffix.casefold()
        for secret_pattern in _SECRET_PATTERNS:
            if secret_pattern.name == "assigned_secret_unquoted" and suffix in code_suffixes:
                continue
            matches = list(secret_pattern.expression.finditer(redacted))
            for match in reversed(matches):
                line = redacted.count("\n", 0, match.start()) + 1
                if "secret" in match.groupdict():
                    start, end = match.span("secret")
                else:
                    start, end = match.span()
                replacement = "[REDACTED]" + "\n" * redacted[start:end].count("\n")
                redacted = redacted[:start] + replacement + redacted[end:]
                findings.append(
                    SecurityFinding(
                        code="secret_redacted",
                        severity=FindingSeverity.CRITICAL,
                        path=path,
                        line=line,
                        pattern=secret_pattern.name,
                        message="Potential secret was redacted",
                        redacted=True,
                    )
                )
        policy = PublicationPolicy.REDACT if findings else PublicationPolicy.INDEX
        return ScanResult(allowed=True, policy=policy, redacted_text=redacted, findings=tuple(findings))
