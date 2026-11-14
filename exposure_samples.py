"""Public finite inputs and hand-calculated anchors; no query index."""
from copy import deepcopy


def points(coords, station="A", start=1):
    return [{"id": start + i, "station": station, "t": t,
             "reading": y, "valid": True} for i, (t, y) in enumerate(coords)]


def answer(sid, duration, excess):
    return {"snapshot": sid, "duration": duration, "excess": excess}


def sample(name):
    ramp = points([(0, 0), (10, 10)])
    cases = {
        "rise": {"files": {"p": ramp}, "queries": [
            [1, "A", 2, 8, 4], [1, "A", -5, 15, 10],
            [1, "A", 0, 10, -2], [1, "A", 7, 7, 0],
            [1, "absent", 0, 10, 0], [1, "A", 8, 2, 0]],
            "expected": [answer(1, [4, 1], [8, 1]), answer(1, [0, 1], [0, 1]),
                         answer(1, [10, 1], [70, 1]), answer(1, [0, 1], [0, 1]),
                         answer(1, [0, 1], [0, 1]), {"error": "BAD_WINDOW"}]},
        "fall": {"files": {"p": points([(0, 10), (10, 0)])},
            "queries": [[1, "A", 2, 8, 4]],
            "expected": [answer(1, [4, 1], [8, 1])]},
        "fraction": {"files": {"p": points([(0, 0), (3, 2)])},
            "queries": [[1, "A", 0, 3, 1], [1, "A", 1, 2, 1]],
            "expected": [answer(1, [3, 2], [3, 4]), answer(1, [1, 2], [1, 12])]},
        "flat": {"files": {"p": points([(0, 4), (10, 4)])},
            "queries": [[1, "A", 0, 10, 4], [1, "A", 0, 10, 3], [1, "A", 0, 10, 5]],
            "expected": [answer(1, [0, 1], [0, 1]), answer(1, [10, 1], [10, 1]),
                         answer(1, [0, 1], [0, 1])]},
        "breaks": {"files": {"p": [
            {"id": 1, "station": "A", "t": 0, "reading": 0, "valid": True},
            {"id": 2, "station": "A", "t": 5, "reading": 9, "valid": False},
            {"id": 3, "station": "A", "t": 5, "reading": 4, "valid": True},
            {"id": 4, "station": "A", "t": 10, "reading": 10, "valid": True}
        ] + points([(0, -2), (10, 2), (21, 9)], "B", 5)},
            "queries": [[1, "A", 0, 10, 0], [1, "B", 5, 21, 0],
                        [1, "B", 10, 21, 0], [1, "B", -10, 40, -3]],
            "expected": [answer(1, [0, 1], [0, 1]), answer(1, [5, 1], [5, 1]),
                         answer(1, [0, 1], [0, 1]), answer(1, [10, 1], [30, 1])]},
        "multi": {"files": {"p": points([(0, 0), (5, 10), (10, 0), (12, 4)])},
            "queries": [[1, "A", -1, 13, 4], [1, "A", 2, 8, 4]],
            "expected": [answer(1, [6, 1], [18, 1]), answer(1, [6, 1], [18, 1])]},
        "snapshots": {"files": {"p": ramp}, "operations": [
            {"op": "rewrite", "job": "flip", "inputs": ["p"], "layout": [[["p", 1], ["p", 0]]]},
            {"op": "delete", "snapshot": 2, "file": "rewrite-flip-0", "pos": 0}],
            "queries": [[1, "A", 2, 8, 4], [2, "A", 2, 8, 4],
                        [3, "A", 2, 8, 4], [0, "A", 0, 10, 0], [99, "A", 0, 10, 0]],
            "expected": [answer(1, [4, 1], [8, 1]), answer(2, [4, 1], [8, 1]),
                         answer(3, [0, 1], [0, 1]), answer(0, [0, 1], [0, 1]),
                         {"error": "NO_SNAPSHOT"}]}
    }
    spec = deepcopy(cases[name])
    spec.setdefault("operations", [])
    return spec


NAMES = ("rise", "fall", "fraction", "flat", "breaks", "multi", "snapshots")
