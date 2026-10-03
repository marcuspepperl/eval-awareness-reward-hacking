"""Local server for the labelling UI: serves the page, label sets, and the codebook, and autosaves labels.

    uv run python scripts/judge/label_server.py [--port 7581]
    open http://localhost:7581/?set=uitest&labeler=mark

Routes:
  GET  /                                  labelling page (scripts/judge/label_ui/label.html)
  GET  /static/<file>                     page assets (scripts/judge/label_ui/)
  GET  /codebook.md                       docs/codebook.md
  GET  /api/set/<set>                     logs/12-judge/labelsets/<set>/data.json
  GET  /api/labels/<set>/<labeler>        {key: label record} for that labeller
  PUT  /api/labels/<set>/<labeler>/<idx>  save one attempt's label record (JSON body)
Labels are written to logs/12-judge/labels/<set>/<labeler>/<key with ':' -> '__'>.json.
Binds to 127.0.0.1 only. Names are restricted to [A-Za-z0-9_-] to keep paths inside the roots.
"""

import argparse
import json
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UI = REPO / "scripts/judge/label_ui"
SETS = REPO / "logs/12-judge/labelsets"
LABELS = REPO / "logs/12-judge/labels"
CODEBOOK = REPO / "docs/codebook.md"
NAME = re.compile(r"^[A-Za-z0-9_-]+$")


def _safe(*names: str) -> bool:
    """True if every path component is a plain name (no traversal)."""
    return all(NAME.match(n) for n in names)


class Handler(SimpleHTTPRequestHandler):
    """Static files + a small JSON API for label sets and label records."""

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        """Write a complete response with no caching."""
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        """Send a JSON response."""
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _file(self, path: Path, ctype: str) -> None:
        """Send a file, or 404."""
        if path.is_file():
            self._send(200, path.read_bytes(), ctype)
        else:
            self._json({"error": "not found"}, 404)

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        """Route GET requests."""
        path = self.path.split("?", 1)[0]
        parts = [p for p in path.split("/") if p]
        if not parts:
            return self._file(UI / "label.html", "text/html; charset=utf-8")
        if (
            parts[0] == "static"
            and len(parts) == 2
            and re.match(r"^[\w.-]+$", parts[1])
        ):
            ctype = {"js": "text/javascript", "css": "text/css"}.get(
                parts[1].rsplit(".", 1)[-1], "application/octet-stream"
            )
            return self._file(UI / parts[1], ctype + "; charset=utf-8")
        if parts == ["codebook.md"]:
            return self._file(CODEBOOK, "text/markdown; charset=utf-8")
        if parts[:2] == ["api", "set"] and len(parts) == 3 and _safe(parts[2]):
            return self._file(SETS / parts[2] / "data.json", "application/json")
        if parts[:2] == ["api", "labels"] and len(parts) == 4 and _safe(*parts[2:]):
            d = LABELS / parts[2] / parts[3]
            recs = {}
            for f in sorted(d.glob("*.json")) if d.is_dir() else []:
                rec = json.loads(f.read_text())
                recs[rec["key"]] = rec
            return self._json(recs)
        self._json({"error": "not found"}, 404)

    def do_PUT(self) -> None:  # noqa: N802
        """Save one attempt's label record."""
        parts = [p for p in self.path.split("?", 1)[0].split("/") if p]
        if not (
            parts[:2] == ["api", "labels"] and len(parts) == 5 and _safe(*parts[2:4])
        ):
            return self._json({"error": "bad path"}, 400)
        rec = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        key = rec.get("key", "")
        if not re.match(r"^[\w:.-]+$", key):
            return self._json({"error": "bad key"}, 400)
        d = LABELS / parts[2] / parts[3]
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / (key.replace(":", "__") + ".json.tmp")
        tmp.write_text(json.dumps(rec, indent=1))
        tmp.replace(d / (key.replace(":", "__") + ".json"))
        self._json({"ok": True})

    def log_message(self, fmt: str, *args) -> None:
        """Log only non-GET requests (saves) to keep the console readable."""
        if self.command != "GET":
            super().log_message(fmt, *args)


def main() -> None:
    """Start the server on localhost."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7581)
    args = ap.parse_args()
    print(f"labelling UI: http://localhost:{args.port}/?set=<set>&labeler=<name>")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
