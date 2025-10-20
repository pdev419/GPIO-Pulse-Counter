import json, socket, threading, time, os
from typing import Optional

class PeerSync:
    def __init__(self, port: int = None):
        self.port = port or int(os.getenv("Z_SEND_PORT", 9787))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((os.getenv("PEER_BIND", "0.0.0.0"), self.port))
        self.best_peer_rate: Optional[float] = None
        self.best_peer_quality: Optional[str] = None
        self.best_peer_jitter: Optional[float] = None
        self.best_peer_ip: Optional[str] = None
        self._stop = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        self.sock.settimeout(0.5)
        last_seen = {}
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                data = None
            if not data:
                now = time.time()
                drop = [k for k,v in last_seen.items() if now - v > 30]
                for k in drop: last_seen.pop(k, None)
                continue
            last_seen[addr[0]] = time.time()
            try:
                obj = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            r = obj.get("rate_hz")
            q = obj.get("quality")
            j = obj.get("jitter")
            if r is None or q is None:
                continue
            if (q == "OK") and (j is not None):
                if (self.best_peer_jitter is None) or (j < self.best_peer_jitter):
                    self.best_peer_rate = r
                    self.best_peer_quality = q
                    self.best_peer_jitter = j
                    self.best_peer_ip = addr[0]