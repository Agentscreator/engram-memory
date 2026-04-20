"""Codebase verification — fact-vs-code conflict detection.

Scans the working directory for verifiable claims in Engram facts and
surfaces conflicts when a fact contradicts what the code actually says.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("engram")

# Files to scan for config key/value pairs
_CONFIG_FILES = [
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Dockerfile",
]

# Files to scan for version/dependency info
_DEPENDENCY_FILES = [
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "pom.xml",
    "build.gradle",
]

# Max file size to read (skip large generated files)
_MAX_FILE_SIZE = 256 * 1024  # 256 KB

# Patterns for extracting key=value from env/config files
_ENV_PATTERN = re.compile(r"^([A-Z][A-Z0-9_]{2,})\s*=\s*(.+)$", re.MULTILINE)

# Pattern for port numbers in config/docker files
_PORT_PATTERN = re.compile(r"(?:port|PORT)\s*[:=]\s*(\d{2,5})")
_DOCKER_PORT_PATTERN = re.compile(r'"(\d+):(\d+)"')
_EXPOSE_PATTERN = re.compile(r"EXPOSE\s+(\d+)")


def scan_codebase(root: str | Path | None = None) -> dict[str, Any]:
    """Scan the codebase and return a structured snapshot of ground truth.

    Returns a dict with:
        config_keys: {KEY: value} from .env files
        ports: [port_numbers] from config/docker
        technologies: {tech_name: evidence_file}
        versions: {package_name: version_string}
        files: set of existing file paths (relative)
    """
    root = Path(root) if root else Path.cwd()
    if not root.is_dir():
        return {}

    result: dict[str, Any] = {
        "config_keys": {},
        "ports": set(),
        "technologies": {},
        "versions": {},
        "files": set(),
    }

    # Collect file listing (top 3 levels, skip hidden/vendor dirs)
    _skip_dirs = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".next",
        ".nuxt",
        "dist",
        "build",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "target",
        "vendor",
    }
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune hidden and vendor directories
        dirnames[:] = [d for d in dirnames if d not in _skip_dirs and not d.startswith(".")]
        rel_dir = os.path.relpath(dirpath, root)
        depth = rel_dir.count(os.sep) if rel_dir != "." else 0
        if depth > 3:
            dirnames.clear()
            continue
        for fname in filenames:
            rel_path = os.path.join(rel_dir, fname) if rel_dir != "." else fname
            result["files"].add(rel_path)

    # Scan .env and config files for key=value pairs
    for config_file in _CONFIG_FILES:
        path = root / config_file
        if not path.is_file() or path.stat().st_size > _MAX_FILE_SIZE:
            continue
        try:
            content = path.read_text(errors="replace")
            for match in _ENV_PATTERN.finditer(content):
                key, value = match.group(1), match.group(2).strip().strip("'\"")
                # Don't store actual secret values — just record the key exists
                # and store non-secret values (ports, hosts, feature flags)
                if _is_safe_to_store(key, value):
                    result["config_keys"][key] = value
                else:
                    result["config_keys"][key] = "<redacted>"

            # Extract port numbers
            for m in _PORT_PATTERN.finditer(content):
                result["ports"].add(int(m.group(1)))
            for m in _DOCKER_PORT_PATTERN.finditer(content):
                result["ports"].add(int(m.group(2)))  # container port
            for m in _EXPOSE_PATTERN.finditer(content):
                result["ports"].add(int(m.group(1)))
        except Exception:
            pass

    # Scan dependency files for versions and technologies
    _scan_package_json(root, result)
    _scan_pyproject(root, result)
    _scan_requirements_txt(root, result)
    _scan_dockerfile(root, result)
    _scan_go_mod(root, result)

    # Detect technologies from file presence
    _detect_technologies(root, result)

    # Convert sets to lists for JSON serialization
    result["ports"] = sorted(result["ports"])
    result["files"] = None  # Don't serialize the full file list

    return result


def verify_fact_against_codebase(
    fact: dict[str, Any],
    codebase: dict[str, Any],
) -> list[dict[str, str]]:
    """Check a single fact's entities against the codebase snapshot.

    Returns a list of mismatches, each with:
        entity_name: the entity that conflicts
        fact_value: what the fact claims
        code_value: what the code actually has
        evidence: which file/source the code value came from
        explanation: human-readable description
    """
    mismatches: list[dict[str, str]] = []

    entities = fact.get("entities")
    if not entities:
        return mismatches

    # Parse entities if stored as JSON string
    if isinstance(entities, str):
        try:
            entities = json.loads(entities)
        except (json.JSONDecodeError, TypeError):
            return mismatches

    if not isinstance(entities, list):
        return mismatches

    config_keys = codebase.get("config_keys", {})
    ports = set(codebase.get("ports", []))
    versions = codebase.get("versions", {})

    for entity in entities:
        etype = entity.get("type", "")
        ename = entity.get("name", "")
        evalue = entity.get("value")

        if etype == "config_key" and ename in config_keys:
            # Fact mentions a config key — check if the fact's content
            # claims a specific value that differs from the code
            code_val = config_keys[ename]
            if code_val == "<redacted>":
                continue  # Can't verify secrets
            # Look for the config key's value in the fact content
            fact_content = fact.get("content", "")
            claimed = _extract_claimed_value(ename, fact_content)
            if claimed is not None and str(claimed) != str(code_val):
                mismatches.append(
                    {
                        "entity_name": ename,
                        "fact_value": str(claimed),
                        "code_value": str(code_val),
                        "evidence": ".env / config files",
                        "explanation": (
                            f"Fact claims {ename}={claimed}, but codebase has {ename}={code_val}"
                        ),
                    }
                )

        elif etype == "numeric" and ename == "port" and evalue is not None:
            # Fact claims a specific port number
            claimed_port = int(evalue) if evalue != -1 else None
            if claimed_port and ports and claimed_port not in ports:
                mismatches.append(
                    {
                        "entity_name": "port",
                        "fact_value": str(claimed_port),
                        "code_value": ", ".join(str(p) for p in sorted(ports)),
                        "evidence": "config / Dockerfile",
                        "explanation": (
                            f"Fact claims port {claimed_port}, "
                            f"but codebase uses port(s) {', '.join(str(p) for p in sorted(ports))}"
                        ),
                    }
                )

        elif etype == "version":
            # Fact claims a version for a package
            pkg_name = ename.replace("_version", "")
            if pkg_name in versions:
                code_ver = versions[pkg_name]
                fact_ver = str(evalue) if evalue else ""
                if fact_ver and code_ver and not _versions_compatible(fact_ver, code_ver):
                    mismatches.append(
                        {
                            "entity_name": ename,
                            "fact_value": fact_ver,
                            "code_value": code_ver,
                            "evidence": "dependency files",
                            "explanation": (
                                f"Fact claims {pkg_name} version {fact_ver}, "
                                f"but codebase has {code_ver}"
                            ),
                        }
                    )

    return mismatches


# ── Internal helpers ──────────────────────────────────────────────────


def _is_safe_to_store(key: str, value: str) -> bool:
    """Return True if a config value is safe to store (not a secret)."""
    secret_patterns = (
        "SECRET",
        "PASSWORD",
        "TOKEN",
        "KEY",
        "PRIVATE",
        "CREDENTIAL",
        "AUTH",
        "APIKEY",
        "API_KEY",
    )
    key_upper = key.upper()
    for pattern in secret_patterns:
        if pattern in key_upper:
            return False
    # Also skip values that look like tokens/hashes
    if len(value) > 40 and re.match(r"^[a-zA-Z0-9+/=_-]+$", value):
        return False
    return True


def _extract_claimed_value(key: str, content: str) -> str | None:
    """Try to extract the value a fact claims for a config key."""
    # Look for patterns like "KEY=value", "KEY is value", "KEY set to value"
    patterns = [
        re.compile(rf"{re.escape(key)}\s*=\s*['\"]?(\S+?)['\"]?(?:\s|$|,|\.)", re.IGNORECASE),
        re.compile(
            rf"{re.escape(key)}\s+(?:is|set to|equals?|configured as)\s+['\"]?(\S+?)['\"]?(?:\s|$|,|\.)",
            re.IGNORECASE,
        ),
    ]
    for pattern in patterns:
        m = pattern.search(content)
        if m:
            return m.group(1)
    return None


def _versions_compatible(fact_ver: str, code_ver: str) -> bool:
    """Check if two version strings are compatible (same major.minor)."""
    # Strip leading 'v' or '^' or '~'
    fact_ver = fact_ver.lstrip("v^~>=<! ")
    code_ver = code_ver.lstrip("v^~>=<! ")

    fact_parts = fact_ver.split(".")
    code_parts = code_ver.split(".")

    # Compare major version at minimum
    if fact_parts[0] != code_parts[0]:
        return False
    # If both have minor, compare that too
    if len(fact_parts) > 1 and len(code_parts) > 1:
        if fact_parts[1] != code_parts[1]:
            return False
    return True


def _scan_package_json(root: Path, result: dict[str, Any]) -> None:
    """Extract versions and technologies from package.json."""
    path = root / "package.json"
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text())
        # Engine versions
        engines = data.get("engines", {})
        for engine, ver in engines.items():
            result["versions"][engine.lower()] = ver

        # Dependencies
        for dep_key in ("dependencies", "devDependencies"):
            deps = data.get(dep_key, {})
            for pkg, ver in deps.items():
                result["versions"][pkg.lower()] = ver
                # Detect technologies
                tech_map = {
                    "next": "nextjs",
                    "react": "react",
                    "vue": "vue",
                    "express": "express",
                    "fastify": "fastify",
                    "prisma": "prisma",
                    "typeorm": "typeorm",
                    "pg": "postgresql",
                    "mysql2": "mysql",
                    "redis": "redis",
                    "mongodb": "mongodb",
                    "graphql": "graphql",
                }
                pkg_lower = pkg.lower()
                if pkg_lower in tech_map:
                    result["technologies"][tech_map[pkg_lower]] = "package.json"
    except Exception:
        pass


def _scan_pyproject(root: Path, result: dict[str, Any]) -> None:
    """Extract versions from pyproject.toml."""
    path = root / "pyproject.toml"
    if not path.is_file():
        return
    try:
        content = path.read_text()
        # Python version requirement
        m = re.search(r'requires-python\s*=\s*"([^"]+)"', content)
        if m:
            result["versions"]["python"] = m.group(1)
        # Project version
        m = re.search(r'version\s*=\s*"([^"]+)"', content)
        if m:
            result["versions"]["project"] = m.group(1)
    except Exception:
        pass


def _scan_requirements_txt(root: Path, result: dict[str, Any]) -> None:
    """Extract package versions from requirements.txt."""
    path = root / "requirements.txt"
    if not path.is_file():
        return
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([a-zA-Z0-9_-]+)\s*[=~><]+\s*(.+)$", line)
            if m:
                result["versions"][m.group(1).lower()] = m.group(2).strip()
    except Exception:
        pass


def _scan_dockerfile(root: Path, result: dict[str, Any]) -> None:
    """Extract base image versions and ports from Dockerfile."""
    path = root / "Dockerfile"
    if not path.is_file():
        return
    try:
        content = path.read_text()
        # FROM image:version
        for m in re.finditer(r"FROM\s+(\S+?)(?::(\S+))?(?:\s|$)", content):
            image = m.group(1).split("/")[-1]  # e.g. node from library/node
            ver = m.group(2)
            if ver and ver != "latest":
                result["versions"][image.lower()] = ver
            result["technologies"][image.lower()] = "Dockerfile"
        # EXPOSE ports
        for m in _EXPOSE_PATTERN.finditer(content):
            result["ports"].add(int(m.group(1)))
    except Exception:
        pass


def _scan_go_mod(root: Path, result: dict[str, Any]) -> None:
    """Extract Go version from go.mod."""
    path = root / "go.mod"
    if not path.is_file():
        return
    try:
        content = path.read_text()
        m = re.search(r"^go\s+(\d+\.\d+(?:\.\d+)?)", content, re.MULTILINE)
        if m:
            result["versions"]["go"] = m.group(1)
        result["technologies"]["go"] = "go.mod"
    except Exception:
        pass


def _detect_technologies(root: Path, result: dict[str, Any]) -> None:
    """Detect technologies from file/directory presence."""
    markers = {
        "docker-compose.yml": "docker",
        "docker-compose.yaml": "docker",
        "Dockerfile": "docker",
        ".dockerignore": "docker",
        "kubernetes": "kubernetes",
        "k8s": "kubernetes",
        "nginx.conf": "nginx",
        "package.json": "nodejs",
        "pyproject.toml": "python",
        "requirements.txt": "python",
        "Cargo.toml": "rust",
        "go.mod": "go",
        "Gemfile": "ruby",
        "pom.xml": "java",
        "build.gradle": "java",
    }
    for marker, tech in markers.items():
        if (root / marker).exists():
            result["technologies"].setdefault(tech, marker)
