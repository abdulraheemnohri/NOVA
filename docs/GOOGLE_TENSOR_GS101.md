# Google Tensor GS101 hardware profile for NOVA

NOVA can run inside Debian/proot on a Pixel 6 family device. The hardware endpoint is deliberately **observation-first**: it reports properties exposed by the current Linux environment and keeps accelerator support marked `unverified` until the exact runtime/model combination has been tested.

## Pixel 6 family reference

| Attribute | Reference |
|---|---|
| SoC | Google Tensor GS101 |
| Process | Samsung 5 nm |
| CPU topology | 2× Cortex-X1, 2× Cortex-A76, 4× Cortex-A55 |
| GPU | ARM Mali-G78 MP20 |
| Security | Titan M2 |
| Memory | LPDDR5; available capacity varies by handset variant |

Clock speeds in marketing/reference tables are not guaranteed current operating clocks. Thermal throttling, power policy and Android scheduling can reduce sustained performance.

## Acceleration policy

- Gemma/LiteRT-LM remains the primary local model.
- A Tensor/Edge TPU label does **not** mean a given Gemma artifact can run on that accelerator. Confirm the exact artifact format, supported operators, LiteRT-LM build, delegate availability and target-device support.
- NOVA reports TPU/GPU acceleration as `unverified` by default. It must not advertise acceleration until a runtime probe or an explicit benchmark establishes it.
- Mali GPU presence alone does not make ONNX Runtime or whisper.cpp GPU accelerated; the relevant backend/build must support and select that GPU path.
- Start with one active large model and one optional task at a time on mobile. Avoid running parallel multi-billion-parameter models. Use bounded timeouts and clean temporary files.
- Readable thermal-zone values are advisory, not a calibrated battery or SoC temperature guarantee. Do not throttle based solely on an unknown sysfs zone.

## API

Authenticated endpoint: `GET /api/hardware/profile`

The response includes environment-visible CPU and memory information, Android properties when `getprop` is available, thermal-zone readings when accessible, GS101 reference specs when device identity matches, and explicit unverified status for TPU/GPU.

## Debian terminal quick check

```bash
getprop ro.product.model 2>/dev/null || true
getprop ro.board.platform 2>/dev/null || true
grep -E '^(MemTotal|MemAvailable):' /proc/meminfo
grep -E '^(processor|model name|Hardware|Processor)[[:space:]]*:' /proc/cpuinfo | head -40
ls /sys/class/thermal/thermal_zone*/temp 2>/dev/null || true
```

On a Debian proot, some Android properties and thermal data may not be exposed. A missing value means “not observable here”, not “hardware absent”.
