"""Read-only loopback web server for the ref-to-print viewer.

Serves the page in web/r2p-viewer/, printer profiles, and job files under
jobs/ (manifests, reports, meshes, renderer PNGs) plus /api/jobs. Nothing is
written and no stage is run. The optional --tailnet flag publishes the
server on tailscale serve port 8445 and removes only that entry on exit.
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import subprocess
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
HTTPS_PORT = 8445
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})

# Mirror of the step order in r2p/state.py (ORDER); kept here so the viewer
# imports nothing from the driver.
STEPS = ("S0", "S1", "G1", "S2", "G2", "S3", "G3", "S4")
GATES = ("G1", "G2", "G3")

_SEG = r"[A-Za-z0-9_-][A-Za-z0-9_.-]*"  # no leading dot, so "." and ".." never match
_JOBFILE = r"(?:parts\.manifest|job\.state|brief|form\.manifest)\.json"

_CTYPES = {
    ".html": "text/html; charset=utf-8",
    ".mjs": "text/javascript",
    ".js": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".stl": "model/stl",
    ".png": "image/png",
}


class LaunchError(RuntimeError):
    """A tailnet step refused or failed; printed as one line by main()."""


@dataclass
class CmdResult:
    returncode: int
    stdout: str
    stderr: str


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def run(cmd: list[str], timeout: float = 15.0) -> CmdResult:
    """Run one command. Never raises: 127 for a missing binary, 124 for a timeout."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError as exc:
        return CmdResult(127, "", f"{cmd[0]}: not found ({exc})")
    except subprocess.TimeoutExpired as exc:
        return CmdResult(124, _text(exc.stdout), _text(exc.stderr) or f"timed out after {timeout}s")
    except OSError as exc:
        return CmdResult(126, "", f"{cmd[0]}: {exc}")
    return CmdResult(proc.returncode, proc.stdout, proc.stderr)


# ---------------------------------------------------------------- file access


def _host_name(value: str) -> str | None:
    """Hostname from a Host header or extra host: drops brackets and any port."""
    v = value.strip().lower()
    if not v:
        return None
    if v.startswith("["):
        end = v.find("]")
        if end < 0:
            return None
        rest = v[end + 1 :]
        if rest and not rest.startswith(":"):
            return None
        return v[1:end]
    if v.count(":") == 1:
        return v.split(":", 1)[0]
    return v  # a plain name, or a bare IPv6 address such as ::1


def _map_path(path: str) -> str | None:
    """Map an unquoted request path to a path relative to the root, or None."""
    if path == "/web/r2p-viewer/":
        return "web/r2p-viewer/index.html"
    m = re.fullmatch(rf"/web/r2p-viewer/({_SEG}\.(?:html|mjs|css|json))", path)
    if m:
        return f"web/r2p-viewer/{m.group(1)}"
    m = re.fullmatch(rf"/printer/({_SEG}\.json)", path)
    if m:
        return f"printer/{m.group(1)}"
    m = re.fullmatch(rf"/jobs/({_SEG})/({_JOBFILE})", path)
    if m:
        return f"jobs/{m.group(1)}/{m.group(2)}"
    m = re.fullmatch(rf"/jobs/({_SEG})/(reports/{_SEG}\.json)", path)
    if m:
        return f"jobs/{m.group(1)}/{m.group(2)}"
    m = re.fullmatch(rf"/jobs/({_SEG})/(parts/{_SEG}\.stl)", path)
    if m:
        return f"jobs/{m.group(1)}/{m.group(2)}"
    m = re.fullmatch(rf"/jobs/({_SEG})/(views/(?:{_SEG}/)*{_SEG}\.png)", path)
    if m:
        return f"jobs/{m.group(1)}/{m.group(2)}"
    return None


def _safe_file(root: Path, rel: str) -> Path | None:
    """The file at root/rel if it resolves inside its top folder, else None."""
    try:
        allowed = (root / rel.split("/", 1)[0]).resolve(strict=True)
        target = (root / rel).resolve()
    except OSError:
        return None
    if not target.is_relative_to(allowed) or not target.is_file():
        return None
    return target


def _read_json(root: Path, rel: str) -> object | None:
    target = _safe_file(root, rel)
    if target is None:
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def list_jobs(root: Path) -> dict:
    """The /api/jobs payload: jobs with a parts.manifest.json, sorted by name."""
    jobs: list[dict] = []
    jobs_dir = root / "jobs"
    if not jobs_dir.is_dir():
        return {"jobs": jobs}
    for entry in sorted(jobs_dir.iterdir(), key=lambda e: e.name):
        name = entry.name
        if not re.fullmatch(_SEG, name) or not entry.is_dir():
            continue
        base = f"jobs/{name}"
        if _safe_file(root, f"{base}/parts.manifest.json") is None:
            continue

        manifest = _read_json(root, f"{base}/parts.manifest.json")
        parts = manifest.get("parts") if isinstance(manifest, dict) else None
        parts_count = len(parts) if isinstance(parts, list) else 0

        brief = _read_json(root, f"{base}/brief.json")
        printer = brief.get("printer") if isinstance(brief, dict) else None
        if isinstance(printer, str) and printer.endswith(".json"):
            printer = printer[: -len(".json")]
        elif not isinstance(printer, str):
            printer = None

        state = _read_json(root, f"{base}/job.state.json")
        steps = state.get("steps") if isinstance(state, dict) else None
        if not isinstance(steps, dict):
            steps = {}

        def status(step: str, steps: dict = steps) -> str | None:
            s = steps.get(step)
            value = s.get("status") if isinstance(s, dict) else None
            return value if isinstance(value, str) else None

        next_step = None
        if isinstance(state, dict):
            next_step = next((s for s in STEPS if status(s) != "done"), None)
        gates = {g: status(g) or "pending" for g in GATES}

        reports: list[str] = []
        rdir = entry / "reports"
        if rdir.is_dir():
            for f in sorted(rdir.glob("*.json"), key=lambda p: p.name):
                if re.fullmatch(_SEG, f.name) and _safe_file(root, f"{base}/reports/{f.name}"):
                    reports.append(f"reports/{f.name}")

        jobs.append(
            {
                "job": name,
                "parts": parts_count,
                "printer": printer,
                "next": next_step,
                "gates": gates,
                "reports": reports,
            }
        )
    return {"jobs": jobs}


# ----------------------------------------------------------------- HTTP server


class _Handler(BaseHTTPRequestHandler):
    root: Path = DEFAULT_ROOT
    allowed_hosts: frozenset[str] = _LOOPBACK

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write(f"viewer: {format % args}\n")

    def parse_request(self) -> bool:
        """Host and method checks run before dispatch; a refusal is answered here."""
        if not super().parse_request():
            return False
        if _host_name(self.headers.get("Host") or "") not in self.allowed_hosts:
            self._reply(403, b"forbidden host\n", "text/plain; charset=utf-8")
            return False
        if self.command not in ("GET", "HEAD"):
            self._reply(
                405, b"method not allowed\n", "text/plain; charset=utf-8", [("Allow", "GET, HEAD")]
            )
            return False
        return True

    def do_GET(self) -> None:
        self._route()

    def do_HEAD(self) -> None:
        self._route()

    def _route(self) -> None:
        path = unquote(self.path.split("?", 1)[0])
        head = self.command == "HEAD"
        if path == "/":
            self._reply(302, b"", "text/plain; charset=utf-8", [("Location", "/web/r2p-viewer/")], head)
            return
        if path == "/api/jobs":
            body = (json.dumps(list_jobs(self.root), indent=2) + "\n").encode("utf-8")
            self._reply(200, body, "application/json", [], head)
            return
        rel = _map_path(path)
        target = _safe_file(self.root, rel) if rel else None
        ctype = _CTYPES.get(target.suffix.lower()) if target else None
        if target is None or ctype is None:
            self._reply(404, b"not found\n", "text/plain; charset=utf-8", [], head)
            return
        try:
            body = target.read_bytes()
        except OSError:
            self._reply(404, b"not found\n", "text/plain; charset=utf-8", [], head)
            return
        self._reply(200, body, ctype, [], head)

    def _reply(
        self,
        status: int,
        body: bytes,
        ctype: str,
        headers: list[tuple[str, str]] | tuple = (),
        head: bool = False,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()
        if not head and body:
            self.wfile.write(body)
            self.wfile.flush()


def make_server(
    root: Path, port: int = 0, extra_hosts: tuple[str, ...] = ()
) -> ThreadingHTTPServer:
    """A loopback server for the pipeline folder `root`. Port 0 picks a free port."""
    root = Path(root).resolve()
    allowed = set(_LOOPBACK)
    for host in extra_hosts:
        name = _host_name(host)
        if name:
            allowed.add(name)
    handler = type(
        "ViewerHandler",
        (_Handler,),
        {"root": root, "allowed_hosts": frozenset(allowed)},
    )
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


# --------------------------------------------------------------------- tailnet


def served_ports() -> set[int]:
    """Ports that `tailscale serve status --json` currently serves (TCP and Web keys)."""
    result = run(["tailscale", "serve", "status", "--json"])
    if result.returncode != 0:
        # Unknown state must not look like a free port: refuse rather than risk clobbering 8445.
        raise LaunchError(f"`tailscale serve status` failed ({result.returncode}): {result.stderr.strip()}")
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        return set()
    ports: set[int] = set()
    if not isinstance(data, dict):
        return ports
    tcp = data.get("TCP")
    if isinstance(tcp, dict):
        for key in tcp:
            try:
                ports.add(int(key))
            except (TypeError, ValueError):
                pass
    web = data.get("Web")
    if isinstance(web, dict):
        for key in web:
            try:
                ports.add(int(str(key).rsplit(":", 1)[-1]))
            except (TypeError, ValueError):
                pass
    return ports


def dns_name() -> str:
    """This machine's tailnet DNS name, from `tailscale status --json`, without the trailing dot."""
    result = run(["tailscale", "status", "--json"])
    try:
        name = json.loads(result.stdout)["Self"]["DNSName"]
    except (ValueError, KeyError, TypeError):
        name = None
    if result.returncode != 0 or not isinstance(name, str) or not name.strip():
        detail = (result.stderr or result.stdout).strip() or "no DNSName in output"
        raise LaunchError(f"could not read the tailnet DNS name: {detail}")
    return name.strip().rstrip(".")


def tailnet_up(local_port: int) -> str:
    """Publish 127.0.0.1:local_port on tailnet port 8445 and return the https URL."""
    if HTTPS_PORT in served_ports():
        raise LaunchError(
            f"port {HTTPS_PORT} is already served (is `hanger up` running?); stop it first"
        )
    host = dns_name()
    result = run(
        [
            "tailscale",
            "serve",
            "--bg",
            f"--https={HTTPS_PORT}",
            f"http://127.0.0.1:{local_port}",
        ]
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "no output"
        raise LaunchError(f"tailscale serve failed (exit {result.returncode}): {detail}")
    return f"https://{host}:{HTTPS_PORT}/"


def tailnet_down() -> CmdResult:
    """Remove only the port 8445 serve entry."""
    return run(["tailscale", "serve", f"--https={HTTPS_PORT}", "off"])


# ------------------------------------------------------------------------ CLI


def _raise_interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="viewer.serve",
        description="Read-only web viewer for ref-to-print jobs (loopback only).",
    )
    parser.add_argument("--port", type=int, default=0, help="local port (default: any free port)")
    parser.add_argument(
        "--root", type=Path, default=DEFAULT_ROOT, help="pipeline folder (default: this project)"
    )
    parser.add_argument(
        "--tailnet", action="store_true", help=f"also publish on tailscale serve port {HTTPS_PORT}"
    )
    args = parser.parse_args(argv)

    extra: tuple[str, ...] = ()
    if args.tailnet:
        try:
            extra = (dns_name(),)
        except LaunchError as exc:
            print(f"viewer.serve: {exc}", file=sys.stderr)
            return 2

    server = make_server(args.root, args.port, extra)
    port = server.server_address[1]
    tailnet_on = False
    try:
        print(f"viewer: http://127.0.0.1:{port}/", flush=True)
        print(f"from the Mac: ssh -N -L {port}:127.0.0.1:{port} ciara-ai", flush=True)
        if args.tailnet:
            try:
                url = tailnet_up(port)
            except LaunchError as exc:
                print(f"viewer.serve: {exc}", file=sys.stderr)
                return 2
            tailnet_on = True
            print(f"tailnet: {url}", flush=True)
            signal.signal(signal.SIGTERM, _raise_interrupt)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if tailnet_on:
            off = tailnet_down()
            if off.returncode != 0:
                detail = (off.stderr or off.stdout).strip()
                print(f"viewer.serve: could not remove port {HTTPS_PORT}: {detail}", file=sys.stderr)
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
