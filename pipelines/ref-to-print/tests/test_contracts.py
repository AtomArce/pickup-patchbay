import json

import jsonschema
import pytest

from checks import report as rp


@pytest.mark.parametrize(
    "name",
    ["brief", "form.manifest", "parts.manifest", "check.report", "slice.report", "job.state"],
)
def test_schema_is_valid(name):
    jsonschema.Draft202012Validator.check_schema(rp.load_schema(name))


def test_chain_chomp_brief_matches_schema():
    rp.load_json(rp.ROOT / "jobs" / "chain-chomp" / "brief.json", "brief")


def test_printer_profile_loads():
    printer = rp.load_printer("ender3-v3se")
    assert printer["build_volume_mm"] == [220, 220, 250]


def test_report_pass_and_fail(tmp_path):
    good = rp.make_report("mesh", [rp.result("cube", "watertight", True)])
    bad = rp.make_report("mesh", [rp.result("cube", "watertight", False, note="2 open edges")])
    assert rp.finish(good, tmp_path / "good.json") == rp.EXIT_PASS
    assert rp.finish(bad, tmp_path / "bad.json") == rp.EXIT_FAIL
    assert json.loads((tmp_path / "bad.json").read_text())["passed"] is False


def test_empty_report_does_not_pass():
    assert rp.make_report("mesh", [])["passed"] is False
