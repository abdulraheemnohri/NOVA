from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api/hardware", tags=["hardware"])


def _read(path: str, limit: int = 8192) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:limit].strip()
    except (OSError, UnicodeError):
        return ""


def _getprop(name: str) -> str:
    executable = shutil.which("getprop")
    if not executable:
        return ""
    try:
        result = subprocess.run(
            [executable, name], capture_output=True, text=True, timeout=1,
            check=False, shell=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:200]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


def _memory_total_mb() -> int | None:
    match = re.search(r"^MemTotal:\s+(\d+)\s+kB", _read("/proc/meminfo"), re.M)
    return round(int(match.group(1)) / 1024) if match else None


def _cpu_summary() -> dict[str, Any]:
    info = _read("/proc/cpuinfo", 65536)
    processors = len(re.findall(r"^processor\s*:", info, re.M))
    model_names = list(dict.fromkeys(re.findall(r"^(?:model name|Hardware|Processor)\s*:\s*(.+)$", info, re.M | re.I)))
    return {"logical_cpus": processors or (os.cpu_count() or None), "reported_names": model_names[:8]}


def _thermal_readings() -> list[dict[str, Any]]:
    readings: list[dict[str, Any]] = []
    root = Path("/sys/class/thermal")
    try:
        zones = sorted(root.glob("thermal_zone*"))[:32]
    except OSError:
        return readings
    for zone in zones:
        raw = _read(str(zone / "temp"), 64)
        if not raw or not re.fullmatch(r"-?\d{1,9}", raw):
            continue
        value = int(raw)
        # Linux thermal sysfs commonly reports millidegrees C; retain unknown units safely.
        readings.append({
            "zone": zone.name,
            "type": _read(str(zone / "type"), 128) or "unknown",
            "temperature_c": round(value / 1000, 1) if abs(value) >= 1000 else None,
            "raw": value,
        })
    return readings


def get_hardware_profile() -> dict[str, Any]:
    model = _getprop("ro.product.model") or _getprop("ro.product.vendor.model")
    device = _getprop("ro.product.device")
    platform_name = _getprop("ro.board.platform") or _getprop("ro.soc.model")
    cpu = _cpu_summary()
    identity = " ".join([model, device, platform_name, " ".join(cpu["reported_names"])]).lower()
    gs101_match = any(token in identity for token in ("pixel 6", "pixel 6 pro", "pixel 6a", "gs101", "oriole", "raven", "bluejay"))
    known_chip = None
    if gs101_match:
        known_chip = {
            "name": "Google Tensor GS101",
            "process_nm": 5,
            "cpu_layout_reference": [
                {"cores": 2, "architecture": "Cortex-X1", "max_ghz_reference": 2.80},
                {"cores": 2, "architecture": "Cortex-A76", "max_ghz_reference": 2.25},
                {"cores": 4, "architecture": "Cortex-A55", "max_ghz_reference": 1.80},
            ],
            "gpu_reference": "ARM Mali-G78 MP20",
            "security_reference": "Titan M2",
            "note": "Reference specifications; current clock, RAM, GPU/TPU delegate availability and thermal state are not inferred from this identification.",
        }
    return {
        "platform": platform.system(),
        "machine": platform.machine(),
        "android_model": model or None,
        "android_device": device or None,
        "android_board_platform": platform_name or None,
        "cpu": cpu,
        "memory_total_mb": _memory_total_mb(),
        "thermal_zones": _thermal_readings(),
        "chip_reference": known_chip,
        "accelerators": {
            "google_edge_tpu": {
                "status": "unverified",
                "reason": "NOVA does not assume TPU execution from the SoC name. Verify the exact LiteRT-LM build, model artifact, delegate and device support before enabling acceleration.",
            },
            "mali_gpu": {
                "status": "unverified",
                "reason": "GPU presence does not guarantee that LiteRT, ONNX Runtime or whisper.cpp is configured to use it.",
            },
        },
        "runtime_recommendation": {
            "profile": "mobile",
            "max_optional_tasks": 1,
            "model_policy": "Prefer one active local LLM at a time; measure memory and thermal behavior before increasing concurrency.",
        },
        "limitations": [
            "In Debian proot, Android getprop or thermal sysfs may be unavailable or permission-limited.",
            "Memory reported by /proc/meminfo is the environment-visible value, not necessarily total physical device RAM.",
            "Thermal zones may be missing, restricted, or use non-millidegree units.",
        ],
    }


@router.get("/profile")
def hardware_profile() -> dict[str, Any]:
    """Return observed hardware information and conservative acceleration status."""
    return get_hardware_profile()
