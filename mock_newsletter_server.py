#!/usr/bin/env python3
"""
Mock newsletter unsubscribe page server.

Serves unsubscribe pages for one or more fake newsletters.  Dispatches by the
HTTP ``Host`` header so a single server on port 80 can handle multiple domains
(e.g. techdaily.com, dealsweekly.com) without port numbers appearing in URLs.

Usage (single newsletter, backward-compatible):
    python3 mock_newsletter_server.py --name "TechDaily Digest" --port 8080

Usage (multiple newsletters, dispatched by Host header):
    python3 mock_newsletter_server.py \
        --newsletter "techdaily.com:TechDaily Digest" \
        --newsletter "dealsweekly.com:DealsWeekly" \
        --port 80
"""

import argparse
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

UNSUBSCRIBE_DIR = "/tmp/newsletter_unsubscribes"

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Segoe UI', Arial, sans-serif;
    background: #f5f5f5;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
  }}
  .card {{
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.08);
    padding: 48px 40px;
    max-width: 520px;
    width: 90%;
    text-align: center;
  }}
  .logo {{
    font-size: 28px;
    font-weight: 700;
    color: #2c3e50;
    margin-bottom: 8px;
  }}
  .subtitle {{
    color: #7f8c8d;
    font-size: 14px;
    margin-bottom: 32px;
  }}
  h1 {{
    font-size: 22px;
    color: #2c3e50;
    margin-bottom: 12px;
  }}
  p {{
    color: #555;
    line-height: 1.6;
    margin-bottom: 28px;
  }}
  button {{
    background: #e74c3c;
    color: #fff;
    border: none;
    padding: 14px 40px;
    font-size: 16px;
    font-weight: 600;
    border-radius: 8px;
    cursor: pointer;
    transition: background 0.2s;
  }}
  button:hover {{ background: #c0392b; }}
  .success-icon {{
    font-size: 56px;
    margin-bottom: 16px;
  }}
  .success-title {{
    color: #27ae60;
    font-size: 22px;
    margin-bottom: 12px;
  }}
</style>
</head>
<body>
<div class="card">
{body}
</div>
</body>
</html>
"""


class NewsletterHandler(BaseHTTPRequestHandler):
    # Set by main() before starting the server.
    # Maps lowercase domain -> display name (e.g. "techdaily.com" -> "TechDaily Digest").
    newsletters: dict[str, str] = {}

    # Fallback when --name was used (single-newsletter mode).
    single_name: str = ""

    def _resolve_name(self) -> str:
        """Return the newsletter name for the current request, or '' if
        unknown."""
        if self.single_name:
            return self.single_name
        host = self.headers.get("Host", "")
        # Strip port if present (e.g. "techdaily.com:8080")
        domain = host.rsplit(":", 1)[0].lower()
        return self.newsletters.get(domain, "")

    def do_GET(self) -> None:
        name = self._resolve_name()
        if not name:
            self.send_error(404, "Unknown newsletter")
            return
        page = self._unsubscribe_page(name)
        self._send_html(page)

    def do_POST(self) -> None:
        name = self._resolve_name()
        if not name:
            self.send_error(404, "Unknown newsletter")
            return
        if self.path == "/unsubscribe":
            self._record_unsubscribe(name)
            page = self._unsubscribed_page(name)
            self._send_html(page)
        else:
            self.send_error(404)

    def _unsubscribe_page(self, name: str) -> str:
        return HTML.format(
            title=f"Unsubscribe – {name}",
            body=(
                f'<div class="logo">{name}</div>\n'
                f'<div class="subtitle">Email Subscription Management</div>\n'
                f"<h1>We're sorry to see you go</h1>\n"
                f'<p>Click the button below to confirm that you want to '
                f'<strong>unsubscribe</strong> from {name}. '
                f'You will stop receiving all future emails from us.</p>\n'
                f'<form method="POST" action="/unsubscribe">\n'
                f'  <button type="submit">Unsubscribe</button>\n'
                f'</form>'
            ),
        )

    def _unsubscribed_page(self, name: str) -> str:
        return HTML.format(
            title=f"Unsubscribed – {name}",
            body=(
                f'<div class="success-icon">✓</div>\n'
                f'<div class="success-title">You have been unsubscribed</div>\n'
                f'<p>You have been successfully removed from the '
                f'<strong>{name}</strong> mailing list. '
                f'You will no longer receive emails from us.</p>\n'
            ),
        )

    def _send_html(self, content: str) -> None:
        data = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _record_unsubscribe(self, name: str) -> None:
        os.makedirs(UNSUBSCRIBE_DIR, exist_ok=True)
        safe = name.replace(" ", "_").replace("/", "_")
        fpath = os.path.join(UNSUBSCRIBE_DIR, f"{safe}.txt")
        with open(fpath, "w") as f:
            f.write(f"unsubscribed from {name}\n")
        print(f"UNSUBSCRIBED: {name!r}  ->  {fpath}", flush=True)

    def log_message(self, fmt, *args) -> None:
        print(f"[{self.client_address[0]}] {fmt % args}", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(
        description="Mock newsletter unsubscribe page server"
    )
    p.add_argument(
        "--name",
        help="Single newsletter display name (simple mode, no Host dispatch)",
    )
    p.add_argument(
        "--newsletter",
        action="append",
        default=[],
        metavar="DOMAIN:NAME",
        help=(
            "Add a newsletter: 'domain:Display Name' "
            "(repeatable; dispatches by Host header)"
        ),
    )
    p.add_argument(
        "--port",
        type=int,
        default=80,
        help="HTTP listen port (default: 80)",
    )
    args = p.parse_args()

    if args.newsletter:
        for entry in args.newsletter:
            domain, _, name = entry.partition(":")
            domain = domain.strip().lower()
            name = name.strip()
            if not domain or not name:
                p.error(f"Invalid --newsletter format: {entry!r}")
            NewsletterHandler.newsletters[domain] = name
        print(
            f"Loaded {len(NewsletterHandler.newsletters)} newsletter(s): "
            f"{list(NewsletterHandler.newsletters.keys())}",
            flush=True,
        )
    elif args.name:
        NewsletterHandler.single_name = args.name
        print(f"Single-newsletter mode: {args.name!r}", flush=True)
    else:
        p.error("Either --name or at least one --newsletter is required.")

    server = HTTPServer(("0.0.0.0", args.port), NewsletterHandler)
    print(f"Listening on 0.0.0.0:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", flush=True)
        server.server_close()
        sys.exit(0)


if __name__ == "__main__":
    main()
