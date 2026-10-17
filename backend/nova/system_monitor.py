"""Read-only local hardware and resource telemetry for the NOVA dashboard."""
from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

import psutil
from fastapi import APIRouter

from nova.config import settings

router = APIRouter(prefix="/api/system", tags=["system-monitor"])


def _cpu_model() -> str:
    candidate = platform.processor().strip()
    if candidate:
        return candidate[:180]
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith(("model name", "hardware", "processor")) and ":" in line:
                value = line.split(":", 1)[1].strip()
                if value and not value.isdigit():
                    return value[:180]
    except OSError:
        pass
    return platform.machine() or "Unknown processor"


def _storage() -> list[dict[str, Any]]:
    paths = [Path.cwd(), settings.workspace, settings.database_path.parent]
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        try:
            resolved = path.resolve()
            usage = shutil.disk_usage(resolved if resolved.exists() else resolved.parent)
            key = str(usage.total)
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "label": "Workspace" if path == settings.workspace else ("Database volume" if path == settings.database_path.parent else "System volume"),
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "used_percent": round((usage.used / usage.total) * 100, 1) if usage.total else 0,
            })
        except (OSError, PermissionError, ValueError):
            continue
    return result


def _nvidia_gpus() -> list[dict[str, Any]]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return []
    try:
        completed = subprocess.run(
            [executable, "--query-gpu=name,utilization.gpu,memory.total,memory.used,temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2, check=False, shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    devices: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines()[:16]:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 5:
            continue
        def number(value: str) -> float | None:
            try:
                return float(value) if value.lower() not in {"n/a", "[not supported]"} else None
            except ValueError:
                return None
        devices.append({
            "name": parts[0][:120], "vendor": "NVIDIA",
            "utilization_percent": number(parts[1]),
            "memory_total_mb": number(parts[2]), "memory_used_mb": number(parts[3]),
            "temperature_c": number(parts[4]), "telemetry": "nvidia-smi",
        })
    return devices



def _sysfs_gpus(base: Path | None = None) -> list[dict[str, Any]]:
    """Read best-effort AMD/Intel GPU telemetry from Linux sysfs without changing device state."""
    drm_root = base if base is not None else Path("/sys/class/drm")
    devices: list[dict[str, Any]] = []
    try:
        cards = sorted(drm_root.glob("card[0-9]*"))
    except OSError:
        return devices

    def read_number(path: Path, divisor: float = 1.0) -> float | None:
        try:
            value = float(path.read_text(encoding="ascii").strip())
            return round(value / divisor, 1)
        except (OSError, ValueError, OverflowError):
            return None

    for card in cards[:16]:
        device = card / "device"
        try:
            vendor_id = (device / "vendor").read_text(encoding="ascii").strip().lower()
            device_id = (device / "device").read_text(encoding="ascii").strip().lower()
        except OSError:
            continue
        vendor = {"0x1002": "AMD", "0x8086": "Intel"}.get(vendor_id)
        if vendor is None:
            continue

        name = None
        for name_file in (device / "product_name", device / "label"):
            try:
                name = name_file.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if name:
                break
        if not name:
            name = f"{vendor} graphics ({device_id})"

        utilization = read_number(device / "gpu_busy_percent")
        total_mb = read_number(device / "mem_info_vram_total", 1024 * 1024)
        used_mb = read_number(device / "mem_info_vram_used", 1024 * 1024)
        temperature = None
        try:
            sensors = list((device / "hwmon").glob("hwmon*/temp*_input"))
        except OSError:
            sensors = []
        for sensor in sensors[:8]:
            candidate = read_number(sensor, 1000)
            if candidate is not None and -20 <= candidate <= 150:
                temperature = candidate
                break
        devices.append({
            "name": name[:120],
            "vendor": vendor,
            "utilization_percent": utilization if utilization is None or 0 <= utilization <= 100 else None,
            "memory_total_mb": total_mb,
            "memory_used_mb": used_mb,
            "temperature_c": temperature,
            "telemetry": "Linux sysfs (best-effort)",
        })
    return devices

def _accelerator_hints() -> dict[str, Any]:
    """Report device-node hints only; don't load drivers or run vendor management tools."""
    base = Path("/sys/bus/pci/devices")
    pci_npu_names: list[str] = []
    try:
        for device in list(base.iterdir())[:2048]:
            try:
                vendor = (device / "vendor").read_text(encoding="ascii").strip().lower()
                device_id = (device / "device").read_text(encoding="ascii").strip().lower()
                class_id = (device / "class").read_text(encoding="ascii").strip().lower()
            except OSError:
                continue
            # PCI class 0x120000 is Processing Accelerator. Vendor names are intentionally
            # conservative: generic PCI devices are not automatically labelled as NPUs.
            if class_id.startswith("0x1200"):
                pci_npu_names.append(f"PCI accelerator ({vendor}:{device_id})")
    except OSError:
        pass

    npu_nodes = [str(p) for p in (Path("/dev/accel"), Path("/dev/ivpu"), Path("/dev/amdxdna")) if p.exists()]
    tpu_nodes = [str(p) for p in (Path("/dev/apex_0"), Path("/dev/apex"), Path("/dev/google-coral")) if p.exists()]
    try:
        render_nodes = len(list(Path("/dev/dri").glob("renderD*")))
    except OSError:
        render_nodes = 0
    return {
        "npu": {"detected": bool(npu_nodes or pci_npu_names), "device_nodes": npu_nodes, "pci_accelerators": pci_npu_names[:16], "telemetry": "device presence only"},
        "tpu": {"detected": bool(tpu_nodes), "device_nodes": tpu_nodes, "telemetry": "device presence only"},
        "graphics_device_nodes": render_nodes,
    }


def collect_system_metrics() -> dict[str, Any]:
    """Collect bounded, read-only resource metrics without exposing processes or serial IDs."""
    virtual = psutil.virtual_memory()
    swap = psutil.swap_memory()
    cpu_freq = None
    try:
        freq = psutil.cpu_freq()
        if freq:
            cpu_freq = {"current_mhz": round(freq.current, 1), "min_mhz": round(freq.min, 1), "max_mhz": round(freq.max, 1)}
    except (OSError, RuntimeError):
        pass
    try:
        battery_obj = psutil.sensors_battery()
        battery = None if battery_obj is None else {
            "percent": round(float(battery_obj.percent), 1),
            "plugged_in": battery_obj.power_plugged,
            "seconds_left": int(battery_obj.secsleft) if battery_obj.secsleft >= 0 else None,
        }
    except (AttributeError, OSError, RuntimeError):
        battery = None

    gpus = _nvidia_gpus() + _sysfs_gpus()
    accelerators = _accelerator_hints()
    return {
        "collected_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(), "python": platform.python_version()},
        "processor": {
            "model": _cpu_model(),
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True) or 1,
            "utilization_percent": round(psutil.cpu_percent(interval=0.05), 1),
            "frequency": cpu_freq,
            "load_average": [round(value, 2) for value in getattr(psutil, "getloadavg", lambda: ())()] if hasattr(psutil, "getloadavg") else None,
        },
        "ram": {"total_bytes": virtual.total, "used_bytes": virtual.used, "available_bytes": virtual.available, "used_percent": round(virtual.percent, 1)},
        "swap": {"total_bytes": swap.total, "used_bytes": swap.used, "used_percent": round(swap.percent, 1)},
        "storage": _storage(),
        "battery": battery,
        "gpu": {"detected": bool(gpus or accelerators["graphics_device_nodes"]), "devices": gpus, "graphics_device_nodes": accelerators["graphics_device_nodes"], "telemetry_note": "Detailed telemetry is available only when a supported vendor adapter is installed."},
        "npu": accelerators["npu"],
        "tpu": accelerators["tpu"],
        "notes": [
            "Read-only telemetry; NOVA does not change clock, voltage, fan, charging, or power settings.",
            "GPU telemetry uses NVIDIA nvidia-smi plus best-effort AMD/Intel Linux sysfs counters; availability depends on kernel and driver support.",
            "NPU/TPU detection is best-effort and depends on OS device nodes and permissions.",
            "A missing battery means the OS did not expose a battery sensor (common on desktops).",
        ],
    }


@router.get("")
def system_metrics() -> dict[str, Any]:
    return collect_system_metrics()
