"""Read-only, secret-safe Obsidian bridge configuration diagnostic.

This script intentionally uses only the Python standard library so it can run
with the system Python before project dependencies such as httpx are installed.
It never makes network requests and never prints configured values.
"""
from __future__ import annotations

import ipaddress
import os
import re
from pathlib import Path
from urllib.parse import urlparse


ENV_FILE = Path.home() / ".config" / "line-ai-secretary" / "obsidian-bridge.env"
EXPECTED_HOSTNAME = "line-bot-yvea.onrender.com"
ENV_KEYS = {
    "url": "OBSIDIAN_BRIDGE_SERVER_URL",
    "bridge_key": "OBSIDIAN_BRIDGE_KEY",
    "vault_path": "OBSIDIAN_VAULT_PATH",
}


def _load_env_file(path: Path) -> dict[str, str]:
    """Read the startup env file format without importing startup dependencies."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _validate_server_url(server_url: str) -> None:
    """Match bridge URL policy using standard-library-only parsing."""
    try:
        if (
            not isinstance(server_url, str)
            or not server_url
            or any(char.isspace() for char in server_url)
        ):
            raise ValueError
        parsed = urlparse(server_url)
        hostname = parsed.hostname
        parsed.port  # Access validates malformed port values.
    except (AttributeError, ValueError):
        raise ValueError("invalid server URL") from None

    valid_hostname = False
    if hostname and not any(char.isspace() for char in hostname):
        try:
            ipaddress.ip_address(hostname)
            valid_hostname = True
        except ValueError:
            try:
                ascii_hostname = hostname.encode("idna").decode("ascii")
                labels = ascii_hostname.rstrip(".").split(".")
                valid_hostname = all(
                    label
                    and len(label) <= 63
                    and label[0].isalnum()
                    and label[-1].isalnum()
                    and all(char.isalnum() or char == "-" for char in label)
                    for label in labels
                )
            except UnicodeError:
                valid_hostname = False

    has_credentials = parsed.username is not None or parsed.password is not None
    if has_credentials:
        valid_hostname = False
    is_https = parsed.scheme == "https" and valid_hostname
    is_loopback_http = (
        parsed.scheme == "http"
        and hostname in {"localhost", "127.0.0.1"}
        and not has_credentials
    )
    if not (is_https or is_loopback_http):
        raise ValueError("invalid server URL")


def inspect_values(
    file_values: dict[str, str], process_env: dict[str, str]
) -> dict[str, object]:
    """Mirror Startup's setting precedence and report properties, never values."""
    selected = {
        name: (
            file_values.get(key, process_env.get(key, "")),
            "file" if key in file_values else "process_env",
        )
        for name, key in ENV_KEYS.items()
    }
    url = selected["url"][0].rstrip("/")
    result: dict[str, object] = {
        "url_set": bool(url),
        "url_source": selected["url"][1],
        "bridge_key_set": bool(selected["bridge_key"][0]),
        "bridge_key_source": selected["bridge_key"][1],
        "vault_path_set": bool(selected["vault_path"][0]),
        "vault_path_source": selected["vault_path"][1],
        "url_has_whitespace": any(char.isspace() for char in url),
        "url_has_quote": any(char in url for char in ('"', "'")),
        "url_has_square_bracket": "[" in url or "]" in url,
        "url_has_userinfo": False,
        "url_scheme_https": False,
        "url_hostname_present": False,
        "url_hostname_matches_expected": False,
        "url_port_parses": False,
    }
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        result["url_scheme_https"] = parsed.scheme == "https"
        result["url_hostname_present"] = bool(hostname)
        result["url_hostname_matches_expected"] = hostname == EXPECTED_HOSTNAME
        result["url_has_userinfo"] = (
            parsed.username is not None or parsed.password is not None
        )
        parsed.port
        result["url_port_parses"] = True
    except (AttributeError, ValueError):
        pass

    try:
        _validate_server_url(url)
        result["bridge_validator_accepts"] = True
        result["bridge_validator_error"] = "none"
    except ValueError:
        result["bridge_validator_accepts"] = False
        result["bridge_validator_error"] = "invalid_server_url"

    # Diagnostic succeeds only for the exact expected production host.
    result["diagnostic_accepts"] = bool(
        result["url_set"]
        and result["url_scheme_https"]
        and result["url_hostname_matches_expected"]
        and not result["url_has_userinfo"]
        and not result["url_has_whitespace"]
        and result["url_port_parses"]
        and result["bridge_validator_accepts"]
    )
    return result


def main() -> int:
    try:
        file_values = _load_env_file(ENV_FILE)
    except (OSError, UnicodeError) as exc:
        # Only exception class is safe to show; configured values stay private.
        print(f"config_load_error={type(exc).__name__}")
        return 1
    result = inspect_values(file_values, dict(os.environ))
    for key, value in result.items():
        print(f"{key}={value}")
    required_set = all(
        result[key] for key in ("url_set", "bridge_key_set", "vault_path_set")
    )
    return 0 if required_set and result["diagnostic_accepts"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
