# NOVA mobile processor support (CPU, GPU, NPU)

## Goal

NOVA must support mobile processor families through capability detection and runtime-compatible execution—not by assuming every accelerator is available. The first target is Google Tensor GS101 in Pixel 6 / Pixel 6 Pro / Pixel 6a, while keeping ARM64 Android/Linux and other CPU/GPU/NPU devices extensible.

## How processor support works

1. **Observe hardware:** read the environment-visible CPU architecture, CPU topology/frequencies, memory, battery and thermal/GPU telemetry when exposed. Missing permissions or sysfs files mean “unknown”, not “unsupported”.
2. **Inspect the actual model:** use the installed LiteRT-LM model metadata/describe feature when supported by that version. Verify model format, required operators, accelerator-specific artifact and runtime version.
3. **Verify runtime backend:** LiteRT-LM documents CPU/GPU backends and NPU support for supported platforms and model artifacts. On Google Tensor, NPU use requires a compatible Tensor-specific artifact/runtime path; a generic .litertlm file is not proof of GS101 NPU support.
4. **Choose safely:** prefer a backend only after compatibility is confirmed. If the accelerator cannot be verified, report that fact and use CPU only if the configured runtime supports it. Never silently switch to a cloud provider.
5. **Protect mobile resources:** default to one optional task at a time, bound timeouts and temporary storage, avoid loading multiple large models, and expose thermal/battery observations when accessible.

## GS101-specific behavior

- Device identification is a hint from Android properties and CPU/device strings, not a performance benchmark.
- Reference SoC topology: 2× Cortex-X1, 2× Cortex-A76 and 4× Cortex-A55; ARM Mali-G78 MP20 GPU; Titan M2 security coprocessor.
- NOVA does not hardcode the reference clock speeds as current frequencies. Use live sysfs readings if available.
- GPU telemetry interfaces are vendor/kernel-specific. Mali counters may not be exposed to a Debian proot. Do not claim GPU acceleration merely because the device has Mali graphics.
- TPU/NPU execution is only reported as verified when the actual LiteRT-LM build, model artifact and selected backend establish it. Do not label the Tensor accelerator as universally available to every .tflite/.litertlm model.
- A browser dashboard or Python API client cannot force an accelerator that the separate LiteRT-LM server was not built/configured to use. Backend selection must happen in the runtime launcher/configuration and be confirmed by logs or a runtime capability report.

## API and dashboard integration

- GET /api/hardware/profile: NOVA's observed hardware profile and conservative acceleration status.
- GET /api/system routes (see the system-monitor router): existing system telemetry such as CPU, memory, battery and best-effort GPU information.
- GET /api/runtimes and GET /api/runtimes/lifecycle: installed optional runtimes and task-scoped activity.

These endpoints require NOVA's local API token, except any explicitly documented health route. They do not prove that a specific inference ran on a GPU/NPU. A future benchmark/probe should record model artifact, runtime version, selected backend, warm-up state, token throughput and failures before changing the backend preference.

## Debian/proot checks

    uname -m
    getprop ro.product.model 2>/dev/null || true
    getprop ro.product.device 2>/dev/null || true
    getprop ro.board.platform 2>/dev/null || true
    grep -E '^(MemTotal|MemAvailable):' /proc/meminfo
    ls /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq 2>/dev/null | head
    ls /sys/class/thermal/thermal_zone*/temp 2>/dev/null | head

On Pixel 6, Android may restrict these interfaces from Debian/proot. Use Android-side inspection/ADB if the container cannot see the properties. Never run a root-only hardware probe just to fill a dashboard field.

## Official runtime references

- LiteRT-LM overview and backend matrix: https://developers.google.com/edge/litert-lm/overview
- LiteRT-LM Android/JVM quick start: https://developers.google.cn/edge/litert-lm/android
- Google Tensor NPU guidance: https://developers.google.cn/edge/litert/next/litert_lm_npu
- LiteRT GPU delegate: https://developers.google.com/edge/litert/android/gpu_native
