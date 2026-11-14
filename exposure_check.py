"""Regression and finite design-evidence checks; complexity still needs review."""
import importlib
import json
import re
import sys
from fractions import Fraction
from pathlib import Path
from checks import check
from exposure_probe import run
from exposure_samples import NAMES, sample


def baseline():
    check()
    actual = {name: run(sample(name)) for name in NAMES}
    assert actual["rise"]["queries"][0]["original"] == {
        "snapshot": 1, "covered": 6, "integral": [30, 1], "mean": [5, 1]}
    assert actual["fraction"]["queries"][0]["original"]["integral"] == [3, 1]
    assert actual["breaks"]["queries"][0]["original"]["covered"] == 0
    assert actual["breaks"]["queries"][1]["original"]["integral"] == [5, 1]
    assert actual["multi"]["queries"][0]["original"]["integral"] == [54, 1]
    snapshots = actual["snapshots"]
    assert snapshots["head"] == 3
    assert snapshots["steps"] == [{"op": "rewrite", "snapshot": 2}, {"op": "delete", "snapshot": 3}]
    assert [r["original"].get("integral") for r in snapshots["queries"][:4]] == [
        [30, 1], [30, 1], [0, 1], [0, 1]]
    assert snapshots["views"]["1"]["rows"][0]["value"]["t"] == 0
    assert snapshots["views"]["2"]["rows"][0]["value"]["t"] == 10
    assert actual["rise"]["queries"][-1]["original"] == {"error": "BAD_WINDOW"}
    assert snapshots["queries"][-1]["original"] == {"error": "NO_SNAPSHOT"}
    assert actual == {name: run(sample(name)) for name in NAMES}
    print("EXPOSURE_BASELINE_OK: snapshots, ties, breaks, original integrals and replay")
    return actual


def verify():
    actual = baseline()
    records = importlib.import_module("exposure_evidence").collect()
    assert set(records) == set(NAMES), "evidence case names"
    for name in NAMES:
        row = records[name]
        assert row["observed"] == actual[name], (name, "observation differs")
        assert row["predicted"] == sample(name)["expected"], (name, "exposure prediction differs")
        assert isinstance(row["explanation"], str) and row["explanation"].strip(), name
        for result in row["predicted"]:
            if "error" in result:
                continue
            for field in ("duration", "excess"):
                n, d = result[field]
                assert type(n) is int and type(d) is int and n >= 0 and d > 0
                value = Fraction(n, d)
                assert [value.numerator, value.denominator] == result[field]
    text = Path("DESIGN.md").read_text(encoding="utf-8")
    sources = ("lake.py", "catalog.py", "objects.py", "analysis_ref.py")
    citations = re.findall(r"(lake\.py|catalog\.py|objects\.py|analysis_ref\.py):(\d+)", text)
    assert {n for n, _ in citations} == set(sources), "cite all four source modules"
    for name, line in citations:
        assert 1 <= int(line) <= len(Path(name).read_text(encoding="utf-8").splitlines())
    print(json.dumps(records, ensure_ascii=False, sort_keys=True))
    print("DESIGN_EVIDENCE_OK: finite observations and anchors checked; design requires human review")


def main(argv):
    if argv == ["baseline"]:
        baseline()
    elif argv == ["verify"]:
        verify()
    else:
        raise SystemExit("usage: exposure_check.py baseline|verify")


if __name__ == "__main__":
    main(sys.argv[1:])
