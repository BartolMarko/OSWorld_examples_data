#!/usr/bin/env python3
"""
Mock SMTP server that captures all outbound emails from Thunderbird.

Listens on 0.0.0.0:10025 (plain SMTP, no auth, no TLS) and saves every
received message as an individual .eml file in a hidden output directory.

Usage:
    python3 mock_mail_server.py [--port 10025] [--outbox /tmp/mock_smtp_outbox]

The outbox directory is deliberately placed outside /home/user/ so that
an agent performing a desktop task is unlikely to stumble across it.
"""

import argparse
import email
import os
import socket
import sys
import threading
import time
from datetime import datetime, timezone


class MockSMTPServer:
    """Single-threaded, socket-based SMTP sink.  Accepts one connection at a
    time; for a testbench with a single Thunderbird instance this is plenty."""

    def __init__(self, host: str = "0.0.0.0", port: int = 10025,
                 outbox_dir: str = "/tmp/mock_smtp_outbox"):
        self.host = host
        self.port = port
        self.outbox_dir = outbox_dir
        os.makedirs(self.outbox_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # SMTP session handler
    # ------------------------------------------------------------------

    def _handle_session(self, conn: socket.socket, addr: tuple) -> None:
        """Run a single SMTP conversation."""
        peer = f"{addr[0]}:{addr[1]}"
        print(f"[{peer}] connect", flush=True)

        # Accumulators for the current transaction
        mail_from: str | None = None
        rcpt_tos: list[str] = []
        data_lines: list[str] = []
        in_data: bool = False

        try:
            conn.settimeout(60)  # 60 s idle → close
            conn.sendall(b"220 mock-smtp ESMTP ready\r\n")

            while True:
                line = self._recv_line(conn)
                if line is None:
                    break

                cmd = line[:4].upper().rstrip()
                arg = line[4:].strip() if len(line) > 4 else ""

                if cmd == "HELO" or cmd == "EHLO":
                    conn.sendall(b"250 Hello\r\n")

                elif cmd == "MAIL":
                    mail_from = arg  # e.g. FROM:<...>
                    rcpt_tos.clear()
                    data_lines.clear()
                    in_data = False
                    conn.sendall(b"250 OK\r\n")

                elif cmd == "RCPT":
                    rcpt_tos.append(arg)  # e.g. TO:<...>
                    conn.sendall(b"250 OK\r\n")

                elif cmd == "DATA":
                    in_data = True
                    conn.sendall(b"354 Start mail input; end with <CRLF>.<CRLF>\r\n")

                elif cmd == "RSET":
                    mail_from = None
                    rcpt_tos.clear()
                    data_lines.clear()
                    in_data = False
                    conn.sendall(b"250 OK\r\n")

                elif cmd == "QUIT":
                    conn.sendall(b"221 Bye\r\n")
                    break

                else:
                    # Unrecognised – might be a continuation line in DATA
                    if in_data:
                        # End-of-data marker is a single "." on a line
                        if line.rstrip("\r\n") == ".":
                            in_data = False
                            self._save_email(peer, mail_from, rcpt_tos,
                                             "\n".join(data_lines))
                            conn.sendall(b"250 OK\r\n")
                        else:
                            data_lines.append(line.rstrip("\r\n"))
                    else:
                        conn.sendall(b"500 Unrecognised command\r\n")
        except (socket.timeout, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass
            print(f"[{peer}] disconnect", flush=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _recv_line(conn: socket.socket) -> str | None:
        """Read one CRLF-terminated line from *conn*."""
        buf = b""
        while not buf.endswith(b"\n"):
            try:
                chunk = conn.recv(1)
            except (socket.timeout, ConnectionResetError):
                return None
            if not chunk:
                return None
            buf += chunk
        return buf.decode("utf-8", errors="replace")

    def _save_email(self, peer: str, mail_from: str | None,
                    rcpt_tos: list[str], raw_data: str) -> None:
        """Write the raw message to a .eml file and log metadata."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        fname = f"{ts}_{len(os.listdir(self.outbox_dir)):04d}.eml"
        fpath = os.path.join(self.outbox_dir, fname)

        with open(fpath, "w", encoding="utf-8") as fh:
            fh.write(raw_data)
            if not raw_data.endswith("\n"):
                fh.write("\n")

        # Try to extract subject for the log line
        try:
            msg = email.message_from_string(raw_data)
            subject = msg.get("Subject", "(no subject)")
        except Exception:
            subject = "(parse error)"

        print(
            f"[{peer}] SAVED {fname}  from={mail_from}  "
            f"to={rcpt_tos}  subject={subject!r}",
            flush=True,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Bind and serve forever (or until Ctrl-C)."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.host, self.port))
            sock.listen(5)
            print(f"Mock SMTP server listening on {self.host}:{self.port}", flush=True)
            print(f"Outbox: {self.outbox_dir}", flush=True)

            while True:
                conn, addr = sock.accept()
                t = threading.Thread(target=self._handle_session,
                                     args=(conn, addr), daemon=True)
                t.start()


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Mock SMTP sink for Thunderbird testing")
    p.add_argument("--port", type=int, default=10025,
                   help="Listening port (default: 10025)")
    p.add_argument("--outbox", type=str,
                   default="/tmp/mock_smtp_outbox",
                   help="Directory for saved .eml files")
    args = p.parse_args()

    server = MockSMTPServer(port=args.port, outbox_dir=args.outbox)
    try:
        server.run()
    except KeyboardInterrupt:
        print("\nShutting down.", flush=True)
        sys.exit(0)
