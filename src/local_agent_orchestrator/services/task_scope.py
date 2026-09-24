from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable


BUILTIN_FORBIDDEN_NAMES = {
    ".git",
    ".env",
    ".env.local",
    ".env.production",
    "credentials.json",
    "credentials.yml",
    "credentials.yaml",
    "secrets.json",
    "secrets.yml",
    "secrets.yaml",
}
BUILTIN_FORBIDDEN_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


@dataclass(frozen=True, slots=True)
class ScopeClassification:
    primary: tuple[str, ...] = ()
    discouraged: tuple[str, ...] = ()
    unexpected: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()

    @property
    def grey(self) -> tuple[str, ...]:
        return self.discouraged + self.unexpected


def normalize_scope(values: Iterable[str] | None) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values or ():
        path = value.replace("\\", "/").strip().rstrip("/")
        if path and path not in normalized:
            normalized.append(path)
    return tuple(normalized)


def path_matches(path: str, scope: Iterable[str]) -> bool:
    normalized = path.replace("\\", "/").strip().rstrip("/")
    return any(
        normalized == boundary
        or normalized.startswith(boundary + "/")
        for boundary in normalize_scope(scope)
    )


def is_builtin_forbidden(path: str) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    parts = PurePosixPath(normalized).parts
    basename = parts[-1] if parts else ""
    basename_lower = basename.lower()
    protected_tokens = set(
        basename_lower.replace(".", "_").replace("-", "_").split("_")
    )
    return (
        ".git" in parts
        or basename_lower in BUILTIN_FORBIDDEN_NAMES
        or basename_lower.startswith(".env.")
        or basename_lower.endswith(tuple(BUILTIN_FORBIDDEN_SUFFIXES))
        or bool(
            protected_tokens
            & {"secret", "secrets", "credential", "credentials"}
        )
    )


def is_forbidden_path(path: str, forbidden_scope: Iterable[str] | None = None) -> bool:
    return is_builtin_forbidden(path) or path_matches(path, forbidden_scope or ())


def classify_changed_files(
    changed_files: Iterable[str],
    *,
    primary_scope: Iterable[str] | None = None,
    discouraged_scope: Iterable[str] | None = None,
    forbidden_scope: Iterable[str] | None = None,
) -> ScopeClassification:
    primary = []
    discouraged = []
    unexpected = []
    forbidden = []
    for path in changed_files:
        if is_forbidden_path(path, forbidden_scope):
            forbidden.append(path)
        elif path_matches(path, primary_scope or ()):
            primary.append(path)
        elif path_matches(path, discouraged_scope or ()):
            discouraged.append(path)
        else:
            unexpected.append(path)
    return ScopeClassification(
        primary=tuple(primary),
        discouraged=tuple(discouraged),
        unexpected=tuple(unexpected),
        forbidden=tuple(forbidden),
    )
