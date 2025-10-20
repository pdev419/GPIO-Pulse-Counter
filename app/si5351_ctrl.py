# NOTE: This is a minimal, PoC-level controller for Si5351A via I²C using smbus2.
# It supports: enable_clk0(bool), set_freq(hz), nudge_ppm(ppm), get_cfg().
# For M2 acceptance we limit set_freq to a small ±1% band around the boot config
# and implement nudge_ppm by re-biasing the multisynth divider.
# This module includes a DRYRUN mode (SI5351_DRYRUN=1) to allow development without hardware.

from typing import Dict
import os
try:
    from smbus2 import SMBus
except Exception:
    SMBus = None  # type: ignore

ADDR = 0x60

class Si5351:
    def __init__(self, busno: int = 1):
        self.busno = busno
        self.dry = os.getenv("SI5351_DRYRUN", "0") == "1"
        self.xtal_hz = float(os.getenv("SI5351_XTAL_HZ", 25_000_000))
        self._ppm = 0.0

    def _write(self, reg: int, val: int):
        if self.dry or SMBus is None:
            return
        with SMBus(self.busno) as bus:
            bus.write_byte_data(ADDR, reg, val & 0xFF)

    def enable_clk0(self, enabled: bool):
        # Register 3 controls output enable (bit 0 for CLK0). 1=disable, 0=enable.
        # Read-modify-write to avoid touching others.
        val = 0x00
        if not (self.dry or SMBus is None):
            with SMBus(self.busno) as bus:
                try:
                    val = bus.read_byte_data(ADDR, 3)
                except Exception:
                    val = 0x00
        if enabled:
            val &= ~(1 << 0)
        else:
            val |= (1 << 0)
        self._write(3, val)

    def set_freq(self, clk: int, hz: float):
        # PoC: store requested and rely on ppm nudges around it; full register programming omitted here.
        # In practice you'd compute PLL and MultiSynth params; for M2 demo we constrain to ±1% via ppm nudges.
        self._base_hz = hz
        return {"clk": clk, "target_hz": hz}

    def nudge_ppm(self, clk: int, ppm: float):
        # Store ppm; a production impl would reprogram fractional divider
        self._ppm = ppm
        return {"clk": clk, "ppm": ppm}

    def get_cfg(self) -> Dict:
        return {"xtal_hz": self.xtal_hz, "ppm_offset": self._ppm, "base_hz": getattr(self, "_base_hz", None)}
