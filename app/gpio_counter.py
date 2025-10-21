# Z (Zeta) definition (M1 addendum)
# ---------------------------------
# Z is the ratio of an observed change (dS) to a reference change (dR):
#     Z = dS / dR
# In this logger:
#   dS = current change of the measured signal, i.e., instantaneous rate over the active time window
#   dR = reference change derived from a sliding reference window of REF_WINDOW_PULSES impulses ("Z-ring")
#   N  = number of valid reference impulses used (quality indicator)
#   quality = OK | WARN | FAIL (heuristic based on N and jitter)
#   drift_level = bucketed by abs(Z - 1):
#       <1e-4 -> LOW, <5e-4 -> MED, <2e-3 -> HIGH, else -> CRITICAL

# Z (Zeta) definition (M2)
# ------------------------
# Z is the ratio of an observed change (dS) to a reference change (dR):
# Z = dS / dR
# dS: pulses observed in the current window of length TIME_WINDOW_SEC (delta_count)
# Z‑ring (reference): last REF_WINDOW_PULSES inter-arrival times (with outlier handling)
# Reference rate: r_ref = N / T_ref, where T_ref is the sum of the last N inter-arrival times
# dR: expected pulses in the window: dR = r_ref * window_sec
# N: number of valid reference impulses (<= REF_WINDOW_PULSES)
# Drift class from |Z−1|: LOW < 2e−4, MED < 1e−3, HIGH < 5e−3, else CRITICAL
# Warm-up: until N == REF_WINDOW_PULSES → quality="WARMUP" and clamp drift_level at most MED.

from __future__ import annotations
import os, threading, time, math, statistics
from dataclasses import dataclass
from typing import Optional, Deque, Tuple
from collections import deque
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

GPIO_PIN = int(os.getenv("GPIO_PIN", 18))
TIME_WINDOW_SEC = float(os.getenv("TIME_WINDOW_SEC", 10.0))
REF_WINDOW_PULSES = int(os.getenv("REF_WINDOW_PULSES", 100))

Z_SEND_ENABLED = os.getenv("Z_SEND_ENABLED", "1") == "1"
Z_SEND_INTERVAL_SEC = float(os.getenv("Z_SEND_INTERVAL_SEC", 1.0))
Z_SEND_HOST = os.getenv("Z_SEND_HOST", "127.0.0.1")
Z_SEND_PORT = int(os.getenv("Z_SEND_PORT", 9787))

EDGE_MODE = os.getenv("EDGE_MODE", "RISING").upper() 
DEBOUNCE_US = int(os.getenv("DEBOUNCE_US", "0"))

QUALITY_JITTER_TAU = float(os.getenv("QUALITY_JITTER_TAU", 0.005))

FORCE_MOCK = os.getenv("FORCE_MOCK", "0") == "1"
MOCK_HZ = float(os.getenv("MOCK_HZ", 10.0))
MOCK_JITTER = float(os.getenv("MOCK_JITTER", 0.02))

# Calibration / oscillator (exposed via app)
RATE_TARGET = float(os.getenv("RATE_TARGET", 10.0)) # Hz
CAL_ON = os.getenv("CAL_ON", "0") == "1"
Kp = float(os.getenv("CAL_KP", 200_000.0)) # proportional gain in ppm per 1.0 error
Ki = float(os.getenv("CAL_KI", 20_000.0)) # integral gain in ppm per 1.0 error
PPM_LIMIT = float(os.getenv("PPM_LIMIT", 200.0))

# Peer sync
PEER_LOCK_ON = os.getenv("PEER_LOCK_ON", "0") == "1"

try:
    import lgpio
    _HAVE_LGPIO = True
except Exception:
    lgpio = None
    _HAVE_LGPIO = False

@dataclass
class Status:
    running: bool
    seq: int
    count: int
    rate_hz: float
    timestamp: str
    last_pulse_age_sec: Optional[float]
    z_value: Optional[float]
    window_sec: float
    window_sec_setting: float
    quality: Optional[str]
    rate_target: float
    ppm_offset: float
    lock_state: str
    peer_rate_hz: Optional[float]
    peer_quality: Optional[str]

class PulseCounter:
    def __init__(self, csv_writer, z_sender=None, si=None, peer=None, pid_guard=None):
        self.csv = csv_writer
        self.z_sender = z_sender
        self.si = si
        self.peer = peer
        self.pid_guard = pid_guard

        self._lock = threading.RLock()
        self._running = False
        self._seq = 0
        self._count_total = 0
        self._window_count0 = 0
        self._t0 = time.monotonic()
        self._last_rate_hz = 0.0
        self._last_window_sec = TIME_WINDOW_SEC
        self._quality = None
        self._last_pulse_time: Optional[float] = None
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._chip = None
        self._cb = None
        self._last_z = None
        self._z_ref_times: Deque[float] = deque(maxlen=REF_WINDOW_PULSES + 1)
        self._z_last_emit = 0.0

        # calibration
        self._rate_target = RATE_TARGET
        self._ppm_offset = 0.0
        self._cal_on = CAL_ON
        self._lock_state = "FREE" # FREE|WARMUP|LOCKED|HOLD
        self._i_term = 0.0

        # peer
        self._peer_rate_hz: Optional[float] = None
        self._peer_quality: Optional[str] = None

    def start(self):
        with self._lock:
            if self._running:
                return False
            if self.pid_guard and not self.pid_guard.acquire():
                return False
            
            print("Starting PulseCounter...")
            
            self._stop_evt.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._running = True
            self._thread.start()
            return True

    def stop(self):
        with self._lock:
            if not self._running:
                return False
            self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=5)
        with self._lock:
            self._running = False
            self._thread = None
            
            print("Stopping PulseCounter...")

            if self._cb is not None:
                try:
                    cancel = getattr(self._cb, "cancel", None)
                    if callable(cancel):
                        cancel()
                except Exception:
                    pass
                self._cb = None
            if self._chip is not None:
                try:
                    if hasattr(lgpio, "gpio_free"):
                        lgpio.gpio_free(self._chip, GPIO_PIN)
                except Exception:
                    pass
                try:
                    lgpio.gpiochip_close(self._chip)
                except Exception:
                    pass
                self._chip = None
            if self.pid_guard:
                self.pid_guard.release()
        return True

    def _configure_lgpio(self):
        self._chip = lgpio.gpiochip_open(0)
        edge_const = {
            "RISING": getattr(lgpio, "RISING_EDGE", 1),
            "FALLING": getattr(lgpio, "FALLING_EDGE", 2),
            "BOTH": getattr(lgpio, "BOTH_EDGES", 3),
        }.get(EDGE_MODE, getattr(lgpio, "RISING_EDGE", 1))
        lgpio.gpio_claim_alert(self._chip, GPIO_PIN, edge_const, 0)
        if DEBOUNCE_US > 0 and hasattr(lgpio, "gpio_set_debounce_micros"):
            try:
                lgpio.gpio_set_debounce_micros(self._chip, GPIO_PIN, DEBOUNCE_US)
            except Exception:
                pass
        self._cb = lgpio.callback(self._chip, GPIO_PIN, edge_const, self._edge_cb)

    def _edge_cb(self, chip, gpio, level, ticks):
        if level not in (0, 1):
            return
        now = time.monotonic()
        self._last_pulse_time = now
        self._count_total += 1
        self._z_ref_times.append(now)

    def _ref_stats(self) -> Optional[Tuple[int, float, float]]:
        if len(self._z_ref_times) < (REF_WINDOW_PULSES + 1):
            return None
        times = list(self._z_ref_times)
        intervals = [t2 - t1 for t1, t2 in zip(times[:-1], times[1:])]

        # Remove obvious outliers
        if len(intervals) >= 5:
            med = statistics.median(intervals)
            max_ok = med * 5
            intervals = [x for x in intervals if x <= max_ok]
        
        N = min(REF_WINDOW_PULSES, len(intervals))
        if N == 0:
            return None

        use = intervals[-N:]
        T_ref = sum(use)
        if T_ref <= 0:
            return None

        r_ref = N / T_ref
        mu = T_ref / N

        var = sum((x - mu) ** 2 for x in use) / len(use)
        sigma = math.sqrt(var)
        jitter_cv = (sigma / mu) if mu > 0 else float("inf")
        
        return N, r_ref, jitter_cv

    def _compute_window(self, now: float) -> Tuple[float, int, float]:
        dt = now - self._t0
        dc = self._count_total - self._window_count0
        rate = (dc / dt) if dt > 0 else 0.0
        return dt, dc, rate

    def _compute_z(self, window_sec: float, delta_count: int) -> Optional[float]:
        stats = self._ref_stats()
        if not stats:
            return None
 
        N, r_ref, _ = stats
        dS = float(delta_count)
        dR = r_ref * window_sec

        if dR <= 0:
            return None

        return dS / dR

    @staticmethod
    def _drift_level(z: Optional[float], warmup: bool) -> str:
        if z is None or not math.isfinite(z):
            return "CRITICAL" if not warmup else "MED"
        d = abs(z - 1.0)
        if d < 2e-4:
            return "LOW"
        if d < 1e-4:
            return "MED"
        if d < 5e-3:
            return "HIGH"
        return "CRITICAL" if not warmup else "MED"

    def _quality_and_lock(self) -> Tuple[str, str]:
        stats = self._ref_stats()
        if not stats:
            return "WARMUP", "WARMUP"
        N, _, jitter_cv = stats
        if N < REF_WINDOW_PULSES:
            return "WARMUP", "WARMUP"
        if jitter_cv < QUALITY_JITTER_TAU:
            return "OK", ("LOCKED" if self._cal_on or PEER_LOCK_ON else "FREE")
        return "WARN", ("HOLD" if self._cal_on or PEER_LOCK_ON else "FREE")

    def _apply_calibration(self, rate_hz: float, window_sec: float):
        target = self._rate_target
        if self.peer and self.peer.best_peer_rate is not None and PEER_LOCK_ON:
            target = self.peer.best_peer_rate
        e = (target - rate_hz) / target if target > 0 else 0.0

        self._i_term += e * (window_sec / max(1.0, TIME_WINDOW_SEC))
        ppm = Kp * e + Ki * self._i_term

        ppm = max(-PPM_LIMIT, min(PPM_LIMIT, ppm))
        self._ppm_offset = ppm

        if self.si and (self._cal_on or PEER_LOCK_ON):
            try:
                self.si.nudge_ppm(0, ppm)
            except Exception:
                pass

    def _run(self):
        use_mock = FORCE_MOCK or not _HAVE_LGPIO
        if use_mock:
            def _mock():
                import random
                period = 1.0 / max(1e-6, MOCK_HZ)
                next_t = time.monotonic()
                while not self._stop_evt.is_set():
                    self._edge_cb(None, GPIO_PIN, 1, 0)
                    jitter = (random.random() * 2 - 1) * MOCK_JITTER
                    dt = period * max(0.0, 1.0 + jitter)
                    next_t += dt
                    while True:
                        now = time.monotonic()
                        rem = next_t - now
                        if rem <= 0 or self._stop_evt.wait(min(0.01, rem)):
                            break
            threading.Thread(target=_mock, daemon=True).start()
        else:
            self._configure_lgpio()

        self._t0 = time.monotonic()
        self._window_count0 = self._count_total
        self._z_last_emit = time.monotonic()

        while not self._stop_evt.wait(0.01):
            now = time.monotonic()
            dt, dc, rate = self._compute_window(now)
            if abs(dt - TIME_WINDOW_SEC) <0.2 and dt >= TIME_WINDOW_SEC:
                self._last_rate_hz = rate
                warmup = (self._ref_stats() is None) or (self._ref_stats()[0] < REF_WINDOW_PULSES)
                self._last_z = self._compute_z(dt, dc)
                quality, lock_state = self._quality_and_lock()
                drift = self._drift_level(z, warmup)
                self._quality = quality

                if warmup:
                    lock_state = "WARMUP"
                if self._cal_on or PEER_LOCK_ON:
                    self._apply_calibration(rate, dt)
                if self.peer:
                    self._peer_rate_hz = self.peer.best_peer_rate
                    self._peer_quality = self.peer.best_peer_quality

                self._seq += 1
                self.csv.write_row(
                    seq=self._seq,
                    count=self._count_total,
                    delta_count=dc,
                    rate_hz=rate,
                    status="RUNNING",
                    z=self._last_z,
                    drift_level=drift,
                    window_sec=dt,
                    quality=quality,
                    rate_target=self._rate_target,
                    ppm_offset=self._ppm_offset,
                    lock_state=lock_state,
                    peer_rate_hz=self._peer_rate_hz,
                    peer_quality=self._peer_quality,
                )
                self._t0 = now
                self._window_count0 = self._count_total
                self._last_window_sec = dt

            if Z_SEND_ENABLED and self.z_sender and (now - self._z_last_emit) >= Z_SEND_INTERVAL_SEC:
                z = self._compute_z(max(1e-6, self._last_window_sec), dc)
                stats = self._ref_stats()
                jitter = stats[2] if stats else None

                self.z_sender.emit_peer(
                    node_id=os.getenv("NODE_ID", os.uname().nodename),
                    seq=self._seq,
                    rate_hz=self._last_rate_hz,
                    z=z,
                    jitter=jitter,
                    ppm_offset=self._ppm_offset,
                    quality=self._quality_and_lock()[0],
                    lock_state=self._quality_and_lock()[1]
                )
                self._z_last_emit = now

        now = time.monotonic()
        dt, dc, rate = self._compute_window(now)
        z = self._compute_z(dt, dc)
        quality, lock_state = self._quality_and_lock()
        drift = self._drift_level(z, (quality == "WARMUP"))
        self._seq += 1
        self._quality = quality
        
        self.csv.write_row(
            seq=self._seq,
            count=self._count_total,
            delta_count=dc,
            rate_hz=rate,
            status="STOPPED",
            z=z,
            drift_level=drift,
            window_sec=dt,
            quality=quality,
            rate_target=self._rate_target,
            ppm_offset=self._ppm_offset,
            lock_state=lock_state,
            peer_rate_hz=self._peer_rate_hz,
            peer_quality=self._peer_quality,
        )

    def status(self) -> Status:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        last_age = None
        if self._last_pulse_time is not None:
            last_age = max(0.0, time.monotonic() - self._last_pulse_time)
        return Status(
            running=self._running,
            seq=self._seq,
            count=self._count_total,
            rate_hz=self._last_rate_hz,
            timestamp=ts,
            last_pulse_age_sec=last_age,
            z_value=self._last_z,
            window_sec=self._last_window_sec,
            window_sec_setting=TIME_WINDOW_SEC,
            quality=self._quality,
            rate_target=self._rate_target,
            ppm_offset=self._ppm_offset,
            lock_state=self._quality_and_lock()[1],
            peer_rate_hz=self._peer_rate_hz,
            peer_quality=self._peer_quality,
        )
