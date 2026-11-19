"""Tests for viewer/serve.py: HTTP contract, path safety, host check, tailnet calls."""

from __future__ import annotations

import http.client
import json
import os
import sys
import threading

import pytest

from viewer import serve
from viewer.serve import CmdResult, LaunchError, make_server

DEMO_STATE = {
    "schema": "job.state/1",
    "job": "demo",
    "escalated": False,
    "escalation_reason": None,
    "params": {},
    "steps": {
        "S0": {"status": "done", "attempts": 1, "needs": "none"},
        "S1": {"status": "done", "attempts": 1, "needs": "modelling"},
        "G1": {"status": "done", "attempts": 1, "needs": "none"},
        "S2": {"status": "done", "attempts": 1, "needs": "none"},
        "G2": {"status": "pending", "attempts": 0, "needs": "none"},
        "S3": {"status": "pending", "attempts": 0, "needs": "none"},
        "G3": {"status": "pending", "attempts": 0, "needs": "none"},
        "S4": {"status": "pending", "attempts": 0, "needs": "person"},
    },
}


@pytest.fixture
def fake_root(tmp_path):
    """A pipeline folder with one real-looking job, an empty job, and a secret above it."""
    root = tmp_path / "ref"
    (root / "web" / "r2p-viewer").mkdir(parents=True)
    (root / "web" / "r2p-viewer" / "index.html").write_text("<!doctype html><title>v</title>")
    (root / "printer").mkdir()
    (root / "printer" / "x.json").write_text('{"id": "x"}')

    demo = root / "jobs" / "demo"
    (demo / "reports").mkdir(parents=True)
    (demo / "parts").mkdir()
    (demo / "views").mkdir()
    (demo / "parts.manifest.json").write_text(
        json.dumps({"job": "demo", "parts": [{"name": "a"}, {"name": "b"}]})
    )
    (demo / "job.state.json").write_text(json.dumps(DEMO_STATE))
    (demo / "brief.json").write_text(json.dumps({"printer": "ender3-v3se.json"}))
    (demo / "reports" / "G1.check.report.json").write_text('{"gate": "G1"}')
    (demo / "parts" / "a.stl").write_bytes(b"solid a\nendsolid a\n")
    (demo / "views" / "v.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (demo / "parts" / "x.py").write_text("print('not served')")

    empty = root / "jobs" / "empty"
    empty.mkdir()
    (empty / "job.state.json").write_text("{}")

    # A file one level above the root, reachable only by traversal.
    (tmp_path / "pyproject.toml").write_text("secret = 1\n")
    # A symlink inside a served folder that points outside the root.
    (tmp_path / "outside.stl").write_bytes(b"outside")
    try:
        os.symlink(tmp_path / "outside.stl", demo / "parts" / "escape.stl")
    except (OSError, NotImplementedError):
        pass
    return root


def _start(root, extra_hosts=()):
    srv = make_server(root, 0, extra_hosts)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv


@pytest.fixture
def server(fake_root):
    srv = _start(fake_root)
    yield srv
    srv.shutdown()
    srv.server_close()


def _request(srv, method, path, host="default"):
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    if host == "default":
        conn.putheader("Host", f"127.0.0.1:{port}")
    elif host is not None:
        conn.putheader("Host", host)
    conn.endheaders()
    resp = conn.getresponse()
    body = resp.read()
    headers = {k.lower(): v for k, v in resp.getheaders()}
    conn.close()
    return resp.status, headers, body


def get(srv, path, host="default"):
    return _request(srv, "GET", path, host)


# ------------------------------------------------------------- happy paths


def test_root_redirects_to_viewer(server):
    status, headers, _ = get(server, "/")
    assert status == 302
    assert headers["location"] == "/web/r2p-viewer/"


def test_viewer_directory_serves_index(server):
    status, headers, body = get(server, "/web/r2p-viewer/")
    assert status == 200
    assert headers["content-type"] == "text/html; charset=utf-8"
    assert b"<title>v</title>" in body


def test_page_file(server):
    status, headers, body = get(server, "/web/r2p-viewer/index.html")
    assert status == 200
    assert headers["content-type"] == "text/html; charset=utf-8"
    assert int(headers["content-length"]) == len(body)
    assert headers["cache-control"] == "no-store"


def test_printer_profile(server):
    status, headers, body = get(server, "/printer/x.json")
    assert status == 200
    assert headers["content-type"] == "application/json"
    assert json.loads(body) == {"id": "x"}


def test_manifest_and_state(server):
    status, _, body = get(server, "/jobs/demo/parts.manifest.json")
    assert status == 200
    assert json.loads(body)["job"] == "demo"
    status, _, _ = get(server, "/jobs/demo/job.state.json")
    assert status == 200


def test_stl_content_type(server):
    status, headers, body = get(server, "/jobs/demo/parts/a.stl")
    assert status == 200
    assert headers["content-type"] == "model/stl"
    assert body == b"solid a\nendsolid a\n"


def test_report(server):
    status, headers, body = get(server, "/jobs/demo/reports/G1.check.report.json")
    assert status == 200
    assert headers["content-type"] == "application/json"
    assert json.loads(body) == {"gate": "G1"}


def test_png(server):
    status, headers, body = get(server, "/jobs/demo/views/v.png")
    assert status == 200
    assert headers["content-type"] == "image/png"
    assert body.startswith(b"\x89PNG")


def test_head_returns_headers_only(server):
    status, headers, body = _request(server, "HEAD", "/jobs/demo/parts/a.stl")
    assert status == 200
    assert headers["content-type"] == "model/stl"
    assert int(headers["content-length"]) == len(b"solid a\nendsolid a\n")
    assert body == b""


def test_api_jobs_shape(server):
    status, headers, body = get(server, "/api/jobs")
    assert status == 200
    assert headers["content-type"] == "application/json"
    data = json.loads(body)
    assert list(data) == ["jobs"]
    # "empty" has no parts.manifest.json, so only "demo" is listed.
    assert len(data["jobs"]) == 1
    job = data["jobs"][0]
    assert job == {
        "job": "demo",
        "parts": 2,
        "printer": "ender3-v3se",
        "next": "G2",
        "gates": {"G1": "done", "G2": "pending", "G3": "pending"},
        "reports": ["reports/G1.check.report.json"],
    }


def test_api_jobs_next_null_when_complete(fake_root):
    state = json.loads((fake_root / "jobs" / "demo" / "job.state.json").read_text())
    for step in state["steps"].values():
        step["status"] = "done"
    (fake_root / "jobs" / "demo" / "job.state.json").write_text(json.dumps(state))
    srv = _start(fake_root)
    try:
        _, _, body = get(srv, "/api/jobs")
        job = json.loads(body)["jobs"][0]
        assert job["next"] is None
        assert job["gates"] == {"G1": "done", "G2": "done", "G3": "done"}
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_jobs_without_state_file(fake_root):
    (fake_root / "jobs" / "demo" / "job.state.json").unlink()
    srv = _start(fake_root)
    try:
        _, _, body = get(srv, "/api/jobs")
        job = json.loads(body)["jobs"][0]
        assert job["next"] is None
        assert job["gates"] == {"G1": "pending", "G2": "pending", "G3": "pending"}
    finally:
        srv.shutdown()
        srv.server_close()


# ------------------------------------------------------------- path safety


@pytest.mark.parametrize(
    "path",
    [
        "/jobs/../pyproject.toml",
        "/jobs/demo/../../pyproject.toml",
        "/jobs/%2e%2e/pyproject.toml",
        "/jobs/demo/%2e%2e/%2e%2e/pyproject.toml",
        "/jobs/demo%2F..%2F..%2Fpyproject.toml",
        "/web/r2p-viewer/../../pyproject.toml",
        "/printer/../jobs/demo/parts.manifest.json",
        "/jobs/demo/parts/escape.stl",  # symlink pointing outside the root
        "/jobs/demo/parts/x.py",  # a .py file under jobs
        "/jobs/demo/reports/../../../pyproject.toml",
        "/jobs/demo/views/../../../pyproject.toml",
        "/nope",
        "/pyproject.toml",
        "/api/jobs/",
        "/web/r2p-viewer/index.py",
    ],
)
def test_unsafe_or_unlisted_paths_are_404(server, path):
    status, _, body = get(server, path)
    assert status == 404
    assert b"secret" not in body


def test_encoded_dot_dot_in_file_name_is_404(server):
    status, _, _ = get(server, "/jobs/demo/parts/%2e%2e.stl")
    assert status == 404


def test_query_string_is_dropped(server):
    status, _, body = get(server, "/printer/x.json?v=1")
    assert status == 200
    assert json.loads(body) == {"id": "x"}


# ----------------------------------------------------------- host and method


def test_bad_host_is_403(server):
    status, _, _ = get(server, "/api/jobs", host="evil.example")
    assert status == 403


def test_missing_host_is_403(server):
    status, _, _ = get(server, "/api/jobs", host=None)
    assert status == 403


@pytest.mark.parametrize("host", ["127.0.0.1:9999", "localhost", "localhost:8080", "[::1]", "[::1]:8445"])
def test_loopback_hosts_are_allowed(server, host):
    status, _, _ = get(server, "/api/jobs", host=host)
    assert status == 200


def test_extra_host_with_and_without_port(fake_root):
    srv = _start(fake_root, extra_hosts=("ciara-ai.tail1234.ts.net",))
    try:
        assert get(srv, "/api/jobs", host="ciara-ai.tail1234.ts.net")[0] == 200
        assert get(srv, "/api/jobs", host="ciara-ai.tail1234.ts.net:8445")[0] == 200
        assert get(srv, "/api/jobs", host="other.tail1234.ts.net")[0] == 403
    finally:
        srv.shutdown()
        srv.server_close()


def test_post_is_405(server):
    status, _, _ = _request(server, "POST", "/api/jobs")
    assert status == 405


def test_put_is_405(server):
    status, _, _ = _request(server, "PUT", "/printer/x.json")
    assert status == 405


# ---------------------------------------------------------------- tailnet


class FakeTailscale:
    """Stands in for serve.run. Records every command; answers status queries."""

    def __init__(self, serve_status=None, fail_serve=False):
        self.calls: list[list[str]] = []
        self.serve_status = serve_status if serve_status is not None else {}
        self.fail_serve = fail_serve

    def __call__(self, cmd, timeout=15.0):
        self.calls.append(list(cmd))
        if cmd[:3] == ["tailscale", "serve", "status"]:
            return CmdResult(0, json.dumps(self.serve_status), "")
        if cmd[:2] == ["tailscale", "status"]:
            return CmdResult(0, json.dumps({"Self": {"DNSName": "ciara-ai.tail1234.ts.net."}}), "")
        if "--bg" in cmd and self.fail_serve:
            return CmdResult(1, "", "serve broke")
        return CmdResult(0, "", "")


def test_tailnet_refuses_when_8445_served(monkeypatch):
    fake = FakeTailscale({"TCP": {"8445": {"HTTPS": True}}})
    monkeypatch.setattr(serve, "run", fake)
    with pytest.raises(LaunchError) as info:
        serve.tailnet_up(54321)
    assert "port 8445 is already served" in str(info.value)
    assert not any("--bg" in call for call in fake.calls)


def test_tailnet_refuses_when_8445_in_web_key(monkeypatch):
    fake = FakeTailscale({"Web": {"ciara-ai.tail1234.ts.net:8445": {}}})
    monkeypatch.setattr(serve, "run", fake)
    with pytest.raises(LaunchError):
        serve.tailnet_up(54321)
    assert not any("--bg" in call for call in fake.calls)


def test_tailnet_up_exact_command_and_url(monkeypatch):
    fake = FakeTailscale({"TCP": {"443": {"HTTPS": True}}})
    monkeypatch.setattr(serve, "run", fake)
    url = serve.tailnet_up(54321)
    assert url == "https://ciara-ai.tail1234.ts.net:8445/"
    assert [
        "tailscale",
        "serve",
        "--bg",
        "--https=8445",
        "http://127.0.0.1:54321",
    ] in fake.calls


def test_tailnet_up_error_on_nonzero(monkeypatch):
    fake = FakeTailscale(fail_serve=True)
    monkeypatch.setattr(serve, "run", fake)
    with pytest.raises(LaunchError) as info:
        serve.tailnet_up(54321)
    assert "serve broke" in str(info.value)


def test_tailnet_down_exact_command(monkeypatch):
    fake = FakeTailscale()
    monkeypatch.setattr(serve, "run", fake)
    serve.tailnet_down()
    assert fake.calls == [["tailscale", "serve", "--https=8445", "off"]]


def test_no_reset_or_funnel_ever(monkeypatch):
    fake = FakeTailscale()
    monkeypatch.setattr(serve, "run", fake)
    serve.tailnet_up(54321)
    serve.tailnet_down()
    serve.served_ports()
    serve.dns_name()
    for call in fake.calls:
        joined = " ".join(call)
        assert "reset" not in joined
        assert "funnel" not in joined


def test_served_ports_parses_bad_output_as_empty(monkeypatch):
    monkeypatch.setattr(serve, "run", lambda cmd, timeout=15.0: CmdResult(0, "not json", ""))
    assert serve.served_ports() == set()


def test_served_ports_refuses_when_status_fails(monkeypatch):
    # An unknown serve state must not look like a free 8445.
    monkeypatch.setattr(serve, "run", lambda cmd, timeout=15.0: CmdResult(1, "", "access denied"))
    with pytest.raises(LaunchError):
        serve.served_ports()


def test_served_ports_collects_tcp_and_web(monkeypatch):
    data = {"TCP": {"443": {}}, "Web": {"host.ts.net:8445": {}, "host.ts.net:8443": {}}}
    monkeypatch.setattr(serve, "run", lambda cmd, timeout=15.0: CmdResult(0, json.dumps(data), ""))
    assert serve.served_ports() == {443, 8445, 8443}


def test_dns_name_strips_trailing_dot(monkeypatch):
    fake = FakeTailscale()
    monkeypatch.setattr(serve, "run", fake)
    assert serve.dns_name() == "ciara-ai.tail1234.ts.net"


def test_run_reports_missing_binary_as_127():
    result = serve.run(["definitely-not-a-real-binary-r2p-viewer"])
    assert result.returncode == 127


def test_run_reports_timeout_as_124():
    result = serve.run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.2)
    assert result.returncode == 124


def test_main_tailnet_refusal_returns_2(monkeypatch, fake_root, capsys):
    fake = FakeTailscale({"TCP": {"8445": {}}})
    monkeypatch.setattr(serve, "run", fake)
    rc = serve.main(["--tailnet", "--root", str(fake_root), "--port", "0"])
    assert rc == 2
    assert "viewer.serve: port 8445 is already served" in capsys.readouterr().err
    assert not any("--bg" in call for call in fake.calls)
    assert not any("off" in call for call in fake.calls)
