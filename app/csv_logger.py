from __future__ import annotations
import os, io, shutil
from datetime import datetime, timezone
from threading import RLock
from typing import Optional

class CsvRotatingWriter:
    COLUMNS = [
        "seq", "count", "delta_count", "rate_hz", "status", "timestamp",
        "z", "drift_level", "window_sec", "quality",
        "rate_target", "ppm_offset", "lock_state",
        "peer_rate_hz", "peer_quality"
    ]

    def __init__(self, data_dir: str, max_bytes: int = 10_000_000, backup_count: int = 5, excel_sep: bool = False):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._path = os.path.join(self.data_dir, "run.csv")
        self._lock = RLock()
        self.excel_sep = excel_sep
        self._ensure_header()

    def _ensure_header(self):
        want = ",".join(self.COLUMNS) + "\n"

        if not os.path.exists(self._path) or os.path.getsize(self._path) == 0:
            print(self._path)
            with open(self._path, "w", encoding="utf-8", newline="") as f:
                if self.excel_sep:
                    f.write("sep=,\n")
                f.write(want)

    def path(self) -> str:
        return self._path

    def rotate_if_needed(self):
        if os.path.getsize(self._path) < self.max_bytes:
            return
        for i in range(self.backup_count, 0, -1):
            src = f"{self._path}.{i}"
            dst = f"{self._path}.{i+1}"
            if os.path.exists(src):
                if i == self.backup_count:
                    os.remove(src)
                else:
                    os.replace(src, dst)
        shutil.copy2(self._path, f"{self._path}.1")
        open(self._path, "w").close()
        self._ensure_header()

    def write_row(
        self,
        *,
        seq: int,
        count: int,
        delta_count: int,
        rate_hz: float,
        status: str,
        z: Optional[float],
        drift_level: str,
        window_sec: float,
        quality: str,
        rate_target: float,
        ppm_offset: float,
        lock_state: str,
        peer_rate_hz: Optional[float],
        peer_quality: Optional[str],
    ):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        z_str = "" if (z is None) else f"{z:.9f}"
        peer_rate_str = "" if (peer_rate_hz is None) else f"{peer_rate_hz: .9f}"
        line = f"{seq},{count},{delta_count},{rate_hz:.9f},{status},{ts},{z_str},{drift_level},{window_sec:.6f},{quality},{rate_target:.9f},{ppm_offset:3f},{lock_state},{peer_rate_str},{peer_quality or ''} \n"
        with self._lock:
            self.rotate_if_needed()
            with open(self._path, "a", encoding="utf-8", newline="") as f:
                f.write(line)