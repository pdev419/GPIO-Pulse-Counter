from __future__ import annotations
import os, time

def get_uptime_seconds() -> float:
    try:
        with open("/proc/uptime", "r") as f:
            return float(f.read().split()[0])
    except Exception:
        return 0.0

def get_cpu_temp_c() -> float:
    paths = [
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/devices/virtual/thermal/thermal_zone0/temp",
    ]

    for p in paths:
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    v = int(f.read().strip())
                    return v / 1000.0
            except Exception:
                pass
        return float("nan")

def self_check(running: bool, last_pulse_age_sec: float | None) -> str:
    if not running:
        return "YELLOW: stopped"
    if last_pulse_age_sec is None:
        return "YELLOW: no pulses yet"
    if last_pulse_age_sec < 2:
        return "GREEN: healthy"
    if last_pulse_age_sec < 10:
        return "YELLOW: slow input"
    return "RED: no recent pulses"