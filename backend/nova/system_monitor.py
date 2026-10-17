"""Read-only local hardware and resource telemetry for the NOVA dashboard."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
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


def _is_android() -> bool:
    return bool(os.environ.get("ANDROID_ROOT") or os.environ.get("ANDROID_DATA") or hasattr(sys, "getandroidapilevel"))


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _mobile_cpu_cores(base: Path | None = None) -> list[dict[str, Any]]:
    """Read Android/Linux per-core topology and current/max frequencies where exposed."""
    root = base if base is not None else Path("/sys/devices/system/cpu")
    result: list[dict[str, Any]] = []
    try:
        cores = sorted(root.glob("cpu[0-9]*"), key=lambda p: int(p.name[3:]))
    except (OSError, ValueError):
        return result
    for core in cores[:256]:
        suffix = core.name[3:]
        online = _read_text(core / "online")
        current = _read_text(core / "cpufreq" / "scaling_cur_freq")
        maximum = _read_text(core / "cpufreq" / "cpuinfo_max_freq")
        minimum = _read_text(core / "cpufreq" / "cpuinfo_min_freq")
        def mhz(value: str | None) -> float | None:
            try:
                return round(float(value) / 1000, 1) if value is not None else None
            except ValueError:
                return None
        result.append({
            "core": int(suffix),
            "online": online != "0",
            "current_mhz": mhz(current),
            "min_mhz": mhz(minimum),
            "max_mhz": mhz(maximum),
        })
    return result


def _mobile_battery() -> dict[str, Any] | None:
    """Read Android battery values from sysfs or optional Termux:API, without shell."""
    battery_root = Path("/sys/class/power_supply/battery")
    capacity = _read_text(battery_root / "capacity")
    status = _read_text(battery_root / "status")
    if capacity is not None:
        try:
            percent = max(0.0, min(100.0, float(capacity)))
            plugged = status.lower() in {"charging", "full", "not charging"} if status else None
            return {
                "percent": round(percent, 1),
                "plugged_in": plugged,
                "seconds_left": None,
                "source": "Android power_supply sysfs",
                "status": status or None,
            }
        except ValueError:
            pass
    executable = shutil.which("termux-battery-status")
    if executable:
        try:
            result = subprocess.run([executable], capture_output=True, text=True, timeout=2, check=False, shell=False)
            if result.returncode == 0 and len(result.stdout) <= 16384:
                body = json.loads(result.stdout)
                percent = float(body.get("percentage"))
                if 0 <= percent <= 100:
                    status_value = str(body.get("status", "")).lower()
                    return {
                        "percent": round(percent, 1),
                        "plugged_in": status_value in {"charging", "full"},
                        "seconds_left": None,
                        "source": "Termux:API",
                        "status": status_value or None,
                    }
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, json.JSONDecodeError):
            pass
    return None


def _mobile_gpu(base: Path | None = None) -> list[dict[str, Any]]:
    """Best-effort Android GPU counters; values vary by vendor and kernel."""
    devices: list[dict[str, Any]] = []
    kgsl = (base / "kgsl-3d0") if base is not None else Path("/sys/class/kgsl/kgsl-3d0")
    busy = _read_text(kgsl / "gpubusy")
    if busy:
        try:
            used, total = (float(part) for part in busy.split()[:2])
            utilization = round(100 * used / total, 1) if total > 0 and 0 <= used <= total else None
        except (ValueError, TypeError):
            utilization = None
        clock = _read_text(kgsl / "gpuclk")
        maximum = _read_text(kgsl / "max_gpuclk")
        def mhz(value: str | None) -> float | None:
            try:
                return round(float(value) / 1_000_000, 1) if value else None
            except ValueError:
                return None
        devices.append({
            "name": "Qualcomm Adreno GPU (KGSL)",
            "vendor": "Qualcomm",
            "utilization_percent": utilization,
            "memory_total_mb": None,
            "memory_used_mb": None,
            "temperature_c": None,
            "current_clock_mhz": mhz(clock),
            "max_clock_mhz": mhz(maximum),
            "telemetry": "Android KGSL sysfs",
        })
    # Some Mali kernels expose a utilization text file, but no standardized VRAM counter.
    mali_paths = ((base / "mali0" / "utilization",) if base is not None else (Path("/sys/class/misc/mali0/device/utilization"), Path("/sys/kernel/mali/mali0/utilization")))
    if not devices:
        for path in mali_paths:
            value = _read_text(path)
            if value is None:
                continue
            import re
            match = re.search(r"(?:\d+(?:\.\d+)?)", value)
            utilization = None
            if match:
                try:
                    candidate = float(match.group(0))
                    if 0 <= candidate <= 100:
                        utilization = candidate
                except ValueError:
                    pass
            devices.append({
                "name": "ARM Mali GPU",
                "vendor": "ARM",
                "utilization_percent": utilization,
                "memory_total_mb": None,
                "memory_used_mb": None,
                "temperature_c": None,
                "telemetry": "Android Mali sysfs (format-dependent)",
            })
            break
    return devices


def _storage() -> list[dict[str, Any]]:
    paths = [Path.cwd(), settings.workspace, settings.database_path.parent]
    if _is_android():
        paths.extend([Path("/storage/emulated/0"), Path("/sdcard"), Path("/storage/self/primary")])
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
                "label": ("Shared internal storage" if str(path) in {"/storage/emulated/0", "/sdcard", "/storage/self/primary"} else ("Workspace" if path == settings.workspace else ("Database volume" if path == settings.database_path.parent else "System volume"))),
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

    npu_nodes = [str(p) for p in (Path("/dev/accel"), Path("/dev/ivpu"), Path("/dev/amdxdna"), Path("/dev/adsprpc-smd"), Path("/dev/fastrpc-cdsp"), Path("/dev/fastrpc-adsp")) if p.exists()]
    tpu_nodes = [str(p) for p in (Path("/dev/apex_0"), Path("/dev/apex"), Path("/dev/google-coral"), Path("/dev/edgetpu0")) if p.exists()]
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
            "source": "psutil",
            "status": None,
        }
    except (AttributeError, OSError, RuntimeError):
        battery = None
    if _is_android():
        battery = _mobile_battery() or battery

    gpus = _nvidia_gpus() + _sysfs_gpus() + (_mobile_gpu() if _is_android() else [])
    accelerators = _accelerator_hints()
    return {
        "collected_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "platform": {"system": "Android" if _is_android() else platform.system(), "release": platform.release(), "machine": platform.machine(), "python": platform.python_version(), "form_factor": "mobile" if _is_android() else "desktop_or_server", "android_detected": _is_android()},
        "processor": {
            "model": _cpu_model(),
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True) or 1,
            "cores": _mobile_cpu_cores() if _is_android() else [],
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
            "Android mobile support includes CPU core frequency hints, battery sysfs/optional Termux:API, accessible shared storage, and best-effort Adreno/Mali GPU counters; device permissions and kernel interfaces vary.",
            "A missing battery means the OS did not expose a battery sensor (common on desktops).",
        ],
    }


@router.get("")
def system_metrics() -> dict[str, Any]:
    return collect_system_metrics()
