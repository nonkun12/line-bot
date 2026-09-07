#!/usr/bin/env python3
"""Push safe Oracle VM / Docker / n8n metrics to LINE AI Secretary dashboard."""
import hashlib
import hmac
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request

URL = os.environ.get("ORACLE_STATUS_URL", "").strip()
SECRET = os.environ.get("ORACLE_STATUS_SECRET", "").strip()


def command(*args):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
    except Exception:
        return ""


def memory():
    values = {}
    try:
        for line in open("/proc/meminfo", encoding="utf-8"):
            key, value = line.split(":", 1)
            values[key] = int(value.strip().split()[0]) * 1024
    except Exception:
        return {}
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    return {"total_bytes": total, "available_bytes": available, "used_bytes": max(0, total - available)}


def uptime():
    try:
        return round(float(open("/proc/uptime", encoding="utf-8").read().split()[0]))
    except Exception:
        return None


def disk():
    try:
        total, used, free = shutil.disk_usage("/")
        return {"total_bytes": total, "used_bytes": used, "free_bytes": free, "used_percent": round(used / total * 100, 1)}
    except Exception:
        return {}


def docker():
    raw = command("docker", "ps", "--format", "{{.Names}}|{{.Status}}|{{.Ports}}")
    containers = []
    for line in raw.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            containers.append({"name": parts[0], "status": parts[1], "ports": parts[2]})
    n8n = next((c for c in containers if "n8n" in c["name"].lower()), None)
    return {"available": bool(raw or command("docker", "--version")), "containers": containers, "n8n": n8n}


def load():
    raw = command("cat", "/proc/loadavg")
    try:
        return [float(x) for x in raw.split()[:3]]
    except Exception:
        return []


def build_payload():
    return {
        "hostname": socket.gethostname(),
        "timestamp": time.time(),
        "uptime_sec": uptime(),
        "load": load(),
        "memory": memory(),
        "disk": disk(),
        "docker": docker(),
        "platform": command("uname", "-sr"),
    }


def main():
    if not URL or not SECRET:
        raise SystemExit("ORACLE_STATUS_URL and ORACLE_STATUS_SECRET are required")
    body = json.dumps(build_payload(), ensure_ascii=False, separators=(",", ":")).encode()
    signature = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(URL, data=body, method="POST", headers={"Content-Type": "application/json", "X-Oracle-Signature": signature})
    with urllib.request.urlopen(req, timeout=10) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"HTTP {response.status}")


if __name__ == "__main__":
    main()
