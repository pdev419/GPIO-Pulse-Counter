from __future__ import annotations
import json, socket, time, os
from typing import Optional


class ZSender:
    def __init__(self, host: str = None, port: int = None):
        self.host = host or os.getenv("Z_SEND_HOST", "255.255.255.255")
        self.port = int(port or os.getenv("Z_SEND_PORT", 9787))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.peer_list = [x.strip() for x in os.getenv("PEER_LIST", "").split(",") if x.strip()]

    def emit(self, z: Optional[float], N: int, quality: str = None):
        msg = {"z": z, "N": N, "quality": quality or ""}
        self._send(json.dumps(msg).encode("utf-8"))
    
    def emit_peer(self, **kwargs):
        self._send(json.dumps(kwargs, ensure_ascii=False).encode('utf-8'))
    
    def _send(self, payload: bytes):
        if self.peer_list:
            for ip in self.peer_list:
                try:
                    self.sock.sendto(payload, (ip, self.port))
                except OSError:
                    pass
        else:
            try:
                self.sock.sendto(payload, (self.host, self.port))
            except OSError:
                pass