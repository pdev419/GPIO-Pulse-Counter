import argparse
import json
import socket
import sys
import time


def main():
    ap = argparse.ArgumentParser(description="Z-telegram UDP receiver")
    ap.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    ap.add_argument("--port", type=int, default=9787, help="UDP port (default: 9787)")
    ap.add_argument("--bufsize", type=int, default=4096, help="Receive buffer size")
    ap.add_argument("--jsonl", default=None, help="Append JSON Lines to this file")
    ap.add_argument("--quiet", action="store_true", help="Suppress per-message prints")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((args.host, args.port))
    except OSError as e:
        print(f"[receiver] Bind failed on {args.host}:{args.port} → {e}", file=sys.stderr)
        sys.exit(2)

    print(f"[receiver] listening on udp://{args.host}:{args.port}")
    fp = open(args.jsonl, "a", encoding="utf-8") if args.jsonl else None

    try:
        while True:
            data, addr = sock.recvfrom(args.bufsize)
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            try:
                obj = json.loads(data.decode("utf-8"))
            except Exception:
                if not args.quiet:
                    print(f"{ts} {addr} malformed: {data!r}")
                continue

            seq = obj.get("seq")
            z = obj.get("z")
            N = obj.get("N")
            quality = obj.get("quality")

            if not args.quiet:
                print(f"{ts} {addr} seq={seq} z={z} N={N} quality={quality}")

            if fp:
                out = {"ts": ts, "from": f"{addr[0]}:{addr[1]}", **obj}
                fp.write(json.dumps(out, ensure_ascii=False) + "\n")
                fp.flush()
    except KeyboardInterrupt:
        pass
    finally:
        if fp:
            fp.close()
        sock.close()
        print("\n[receiver] closed.")


if __name__ == "__main__":
    main()
