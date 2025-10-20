from fastapi import FastAPI, Body
from fastapi.responses import FileResponse, HTMLResponse
import os
from app.csv_logger import CsvRotatingWriter
from app.gpio_counter import PulseCounter
from app.z_telegram import ZSender
from app.peer_sync import PeerSync
from app.si5351_ctrl import Si5351
from app.pid_guard import PidGuard
from .sysinfo import get_uptime_seconds, get_cpu_temp_c, self_check
from datetime import datetime

app = FastAPI()

DATA_DIR = os.getenv("DATA_DIR", "./data")
os.makedirs(DATA_DIR, exist_ok=True)

csv = CsvRotatingWriter(DATA_DIR, excel_sep=(os.getenv("CSV_EXCEL_SEP", "0") == "1"))
zs = ZSender()
peer = PeerSync()
si = Si5351()
pidg = PidGuard(DATA_DIR)

pc = PulseCounter(csv_writer=csv, z_sender=zs, si=si, peer=peer, pid_guard=pidg)

@app.get("/", response_class=HTMLResponse)
def index():
    # minimal client with HTMX-like fetch using vanilla JS
    with open(os.path.join(os.path.dirname(__file__), "../static/index.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/api/status")
def status():
    s = pc.status()
    return {
        **s.__dict__,
        "uptime_sec": get_uptime_seconds(),
        "cpu_temp_c": get_cpu_temp_c(),
        "self_check": self_check(s.running, s.last_pulse_age_sec),
        "csv_path": csv.path(),
    }

@app.post("/api/start")
def start():
    return {"started": pc.start()}

@app.post("/api/stop")
def stop():
    return {"stopped": pc.stop()}

@app.get("/api/csv")
def get_csv():
    filename = f"{datetime.now().strftime('%Y-%m-%d %H-%M-%S')}.csv"
    return FileResponse(csv.path(), filename=filename)

@app.post("/api/set_target")
def set_target(rate_hz: float = Body(embed=True)):
    pc._rate_target = float(rate_hz)
    return {"rate_target": pc._rate_target}

@app.post("/api/cal_on")
def cal_on():
    pc._cal_on = True
    return {"calibration": "ON"}

@app.post("/api/cal_off")
def cal_off():
    pc._cal_on = False
    return {"calibration": "OFF"}

@app.post("/api/nudge_ppm")
def nudge(ppm: float = Body(embed=True)):
    pc._ppm_offset = float(ppm)
    try:
        si.nudge_ppm(0, pc._ppm_offset)
    except Exception:
        pass
    return {"ppm_offset": pc._ppm_offset}
