"""Passive observations only: source snapshots, original integrals and payload reads."""
import json
import sys
from lake import Lake
from objects import Objects
from analysis_ref import analyse
from exposure_samples import NAMES, sample


class Reads(Objects):
    def __init__(self):
        super().__init__()
        self.gets = []

    def get(self, fid):
        rows = super().get(fid)
        self.gets.append({"file": fid, "rows": len(rows)})
        return rows


class SnapshotView:
    def __init__(self, lake, sid):
        self.lake, self.sid = lake, sid

    def read(self):
        return self.lake.read(self.sid)


def run(spec):
    objects = Reads()
    lake = Lake(objects=objects)
    try:
        lake.seed(spec["files"])
        steps = []
        for op in spec.get("operations", []):
            if op["op"] == "rewrite":
                sid = lake.rewrite(op["job"], op["inputs"], op["layout"])
            elif op["op"] == "delete":
                sid = lake.delete(op["snapshot"], op["file"], op["pos"])
            else:
                raise ValueError("BAD_OPERATION")
            steps.append({"op": op["op"], "snapshot": sid})
        views = {}
        for sid in sorted({q[0] for q in spec["queries"]}):
            try:
                views[str(sid)] = lake.read(sid)
            except ValueError as exc:
                views[str(sid)] = {"error": str(exc)}
        observations = []
        for query in spec["queries"]:
            sid, station, left, right, threshold = query
            objects.gets.clear()
            try:
                original = analyse(SnapshotView(lake, sid), station, left, right)
            except ValueError as exc:
                original = {"error": str(exc)}
            observations.append({"input": query, "original": original,
                                 "gets": list(objects.gets)})
        return {"head": lake.catalog.head(), "steps": steps,
                "views": views, "queries": observations}
    finally:
        lake.catalog.db.close()


def main(argv):
    if len(argv) != 1 or argv[0] not in NAMES + ("all",):
        raise SystemExit("usage: exposure_probe.py all|" + "|".join(NAMES))
    names = NAMES if argv == ["all"] else argv
    for name in names:
        print(json.dumps({"case": name, "observed": run(sample(name))}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
