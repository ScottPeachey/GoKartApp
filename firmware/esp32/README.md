# ESP32 Firmware (Phase 6 skeleton)

PlatformIO + ESP-IDF project with mock-sensor mode for bare devkit testing.

## Build

```bash
cd firmware/esp32
pio run -e esp32s3_mock
pio run -t upload -e esp32s3_mock   # flash to connected board
pio device monitor -b 115200
```

## Behaviour (mock mode)

- Boots through OFF → BOOT → SELF_TEST → READY
- Auto-arms after 1 s (mock brake held)
- Streams JSON telemetry lines on serial (ingest with `gokart telemetry ingest --serial <port>`)
- Console display driver prints speed/mode/SOC every 100 ms

## Tasks

| Task | Rate | Role |
|------|------|------|
| control_task | 100 Hz | detect_faults → safety_step → resolve_limits → control_step |
| telemetry_task | 50 Hz | JSON lines over serial |
| display_task | 10 Hz | console DisplayDriver stub |

Portable logic lives in `firmware/core_c/` and is shared with the host golden test runner.
