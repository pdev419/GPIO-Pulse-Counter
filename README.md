# Pulse Logger (M2) – Raspberry Pi 5

**What it does**  
Measures a pulse signal on Raspberry Pi 5 (GPIO18), computes stable **windowed rate**, **Z (Zeta)** with a sliding **Z-ring**, writes an **extended CSV**, and provides optional **Si5351A** oscillator calibration and **2-box peer sync**. A small web UI shows live KPIs and basic controls.

---

## Quick Start

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv python3-lgpio python3-smbus
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # or paste your .env values
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# open http://<pi-ip>:8000
````

**Web UI**

* **Start / Stop** logging
* **Download CSV**
* **Control panel:** Rate (Hz, `<window_sec>` s), Target, PPM offset, Lock state, Peer rate/quality
* Buttons: **Set Target**, **Cal ON**, **Cal OFF**, **Nudge ppm**

---

## Windowed Measurement (true stability)

* Configure window length via `.env` **`TIME_WINDOW_SEC`** (default **10 s**).
* Each window stores `(t0, c0)`; at end:

  * `window_sec = t_now − t0`
  * `delta_count = count_total − c0`
  * `rate_hz = delta_count / window_sec`
* `window_sec` is recorded in **Status** and **CSV** (plain float, `.` decimal).

---

## Z & Z-ring (short definition)

**Z = dS / dR**

* **dS:** pulses observed in the current window (`delta_count`).
* **Z-ring:** sliding reference from last **REF_WINDOW_PULSES** inter-arrival times (outliers clipped).
* **Reference rate:** `r_ref = N / T_ref` (N intervals over their total time).
* **dR:** expected pulses in the window: `dR = r_ref × window_sec`.
* **N:** number of valid reference impulses (`≤ REF_WINDOW_PULSES`).
* **Drift class** from `abs(Z−1)`: **LOW < 2e-4**, **MED < 1e-3**, **HIGH < 5e-3**, else **CRITICAL**.
* **Warm-up:** until `N == REF_WINDOW_PULSES`, set `quality="WARMUP"` and cap drift ≤ **MED**.

---

## CSV (exact order)

```
seq,count,delta_count,rate_hz,status,timestamp,z,drift_level,window_sec,quality,rate_target,ppm_offset,lock_state,peer_rate_hz,peer_quality
```

* Numeric fields are plain floats with `.` decimal (no thousands grouping).
* Optional first line `sep=,` for Excel if `CSV_EXCEL_SEP=1` in `.env`.

---

## API (minimal)

* `GET /api/status` → includes `window_sec`, `rate_target`, `ppm_offset`, `lock_state`, `peer_rate_hz`, `peer_quality`
* `POST /api/set_target { "rate_hz": 10.000 }`
* `POST /api/cal_on` / `POST /api/cal_off`
* `POST /api/nudge_ppm { "ppm": 25 }`
* Existing: `POST /api/start`, `POST /api/stop`, `GET /api/csv`

---

## Calibration (Si5351A) – optional, OFF by default

* Env: `CAL_ON=0|1`, `RATE_TARGET`, `CAL_KP`, `CAL_KI`, `PPM_LIMIT` (±200 ppm).
* Each window: `e = (rate_target − rate_hz) / rate_target`.
  PI control computes a clamped `ppm_step`; `ppm_offset` is applied via I²C.
* `lock_state`: `FREE | WARMUP | LOCKED | HOLD`.
* Safe dev mode: set `SI5351_DRYRUN=1` to **skip actual I²C writes**.

---

## Peer Sync (two boxes)

* UDP broadcast (default) or unicast via `.env` `PEER_LIST=ip1,ip2,…` on port `Z_SEND_PORT` (default **9787**).
* Message every `Z_SEND_INTERVAL_SEC`:
  `{ "node_id", "seq", "rate_hz", "z", "jitter", "ppm_offset", "quality", "lock_state" }`
* Each box picks **best single peer** (lowest `jitter` with `quality=="OK"`).
* **Peer-lock** (optional): set `PEER_LOCK_ON=1` to use peer rate as target (same PI loop, ±200 ppm clamp).
* UI shows `peer_rate_hz`, `peer_quality`; CSV appends both.

**Two-box acceptance demo (short):**

1. Run both Pis on the same LAN; keep broadcast or set `PEER_LIST`.
2. Start both; ensure peer fields populate.
3. Enable **Cal ON** + **Peer-lock ON** on one box → rate difference stays within **±200 ppm** over ~20 min.
4. Briefly stop one box → other shows **HOLD**, then re-locks when peer returns.

---

## .env (key items)

```dotenv
GPIO_PIN=18
TIME_WINDOW_SEC=10
REF_WINDOW_PULSES=100
QUALITY_JITTER_TAU=0.005
DATA_DIR=./data
CSV_EXCEL_SEP=0
Z_SEND_ENABLED=1
Z_SEND_INTERVAL_SEC=1
Z_SEND_HOST=255.255.255.255
Z_SEND_PORT=9787
PEER_LIST=
NODE_ID=pi5-node
RATE_TARGET=10.000
CAL_ON=0
CAL_KP=200000
CAL_KI=20000
PPM_LIMIT=200
PEER_LOCK_ON=0
SI5351_DRYRUN=1
SI5351_XTAL_HZ=25000000
```

---

## Notes

* **Single-instance guard:** `DATA_DIR/logger.pid` prevents duplicate logger processes.
* **Security:** No router changes required; keep SSH key-only.
* **Licensing:** MIT for project; third-party notices included.
* **Plot:** reuse `analysis/plot_run.py` for a 20-min run (rate and optional Z).
