import os, errno

class PidGuard:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "logger.pid")

    def acquire(self) -> bool:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    pid = int(f.read().strip())
                os.kill(pid, 0)
                return False  # alive
            except Exception:
                pass
        with open(self.path, "w") as f:
            f.write(str(os.getpid()))
        return True

    def release(self):
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
        except OSError:
            pass
