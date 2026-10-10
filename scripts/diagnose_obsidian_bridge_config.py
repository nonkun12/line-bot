"""Read-only, secret-safe diagnostics for the Startup-to-Bridge URL config."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

# Direct script execution sets sys.path[0] to scripts/, not the repository root.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.obsidian_mac_startup import ENV_FILE, _load_env_file
from scripts.obsidian_mac_bridge import _validate_server_url


EXPECTED_HOSTNAME = "line-bot-yvea.onrender.com"
ENV_KEYS = {
    "url": "OBSIDIAN_BRIDGE_SERVER_URL",
    "bridge_key": "OBSIDIAN_BRIDGE_KEY",
    "vault_path": "OBSIDIAN_VAULT_PATH",
}


def inspect_values(file_values: dict[str, str], process_env: dict[str, str]) -> dict[str, object]:
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
        result["url_has_userinfo"] = parsed.username is not None or parsed.password is not None
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

    # Diagnostic succeeds only for the exact expected production host. This is
    # stricter than URL syntax validation, so alternate hosts are never mistaken
    # for the configured Render service.
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
    except Exception as exc:
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
