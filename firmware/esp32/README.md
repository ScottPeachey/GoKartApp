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

- Boots OFF → BOOT → SELF_TEST → READY (watchdog reset reason → FAULT on next boot)
- Auto-arms with mock brake held, precharges, then enters DRIVING with mock throttle
- Streams schema-aligned JSON telemetry on serial (`gokart telemetry ingest --serial <port>`)
- `DisplayDriver` console stub prints speed/mode/SOC every 100 ms
- Mechanical brakes remain available during FAULT; torque/regen cut immediately

## Tasks

| Task | Rate | Role |
|------|------|------|
| `sensor_task` | 200 Hz | Mock ADC sensors → double-buffered snapshot |
| `control_task` | 100 Hz | Read snapshot → safety/limits/control → command slot; feeds task WDT |
| `can_task` | 50 Hz | Consumes command slot (TWAI driver in Phase 7) |
| `telemetry_task` | 50 Hz | JSON lines over serial |
| `display_task` | 10 Hz | Active `DisplayDriver` (console stub) |

Portable logic lives in `firmware/core_c/` and is verified against Python via golden vectors:

```bash
gokart firmware golden
```

Hardware limit ceilings are generated into `include/hard_limits.h` from seed vehicle configs.
