"""Independent piecewise-rational exposure evidence; not the proposed query index.

This module computes super-threshold duration/excess for the fixed-snapshot
queries of EXPOSURE.md directly from real Lake snapshots, segment by segment,
with exact Fraction arithmetic. It deliberately does NOT build the recommended
segment-tree index of DESIGN.md: per query it scans the station's segments,
which is precisely what the proposed index avoids.

collect() returns {name: {"observed", "predicted", "explanation"}} keyed by
exposure_samples.NAMES. "observed" comes straight from exposure_probe.run()
(real Lake calls, original full-scan integrals, payload-read counts).
"predicted" is independently computed here (super-threshold semantics, agreed
errors). "explanation" states numeric boundaries and the index access paths
the recommended design would take (a design prediction, not a measurement).

Rerun:
    python3 exposure_evidence.py            # demo: print collect() as JSON
    python3 exposure_check.py verify        # full regression + this evidence
Random self-check: seed 20261114, 300 rounds; it cross-checks the direct
calculator against an independent shattered-midpoint evaluation and against
window additivity on small random snapshots.
"""
import json
import random
import sys
from fractions import Fraction
from lake import Lake
from exposure_probe import run
from exposure_samples import NAMES, sample

GAP = 10
SEED = 20261114
ROUNDS = 300


def segments(rows, station):
    """Winner-filtered interpolation segments for one station.

    Same-timestamp rows keep the smallest visible id first; an invalid winner
    is a break and is never replaced by a valid same-timestamp candidate.
    A segment exists only between time-adjacent winners that are both valid
    with gap <= GAP. Returns sorted (t0, y0, t1, y1) tuples.
    """
    winners = {}
    for row in rows:
        value = row["value"]
        if value["station"] != station:
            continue
        t = value["t"]
        if t not in winners or value["id"] < winners[t]["id"]:
            winners[t] = value
    ordered = [winners[t] for t in sorted(winners)]
    result = []
    for a, b in zip(ordered, ordered[1:]):
        gap = b["t"] - a["t"]
        if a["valid"] and b["valid"] and gap <= GAP:
            result.append((a["t"], a["reading"], b["t"], b["reading"]))
    return result


def clip_segment(t0, y0, t1, y1, lo, hi, threshold):
    """Exact (duration, excess) of one linear segment clipped to [lo, hi).

    y - threshold is linear, so the strict super-threshold set inside
    [lo, hi) is a (possibly empty) half-interval; its measure and integral
    are computed by endpoint signs and, when signs differ, the exact
    rational crossing point. Endpoints equal to the threshold have measure
    zero and do not affect either quantity.
    """
    span = t1 - t0
    slope = Fraction(y1 - y0, span)
    elo = Fraction(y0) + slope * (lo - t0) - threshold
    ehi = Fraction(y0) + slope * (hi - t0) - threshold
    if elo <= 0 and ehi <= 0:
        return Fraction(0), Fraction(0)
    if elo > 0 and ehi > 0:
        length = Fraction(hi - lo)
        return length, (elo + ehi) * length / 2
    crossing = lo + Fraction(hi - lo) * (elo / (elo - ehi))
    if elo > 0:
        length = crossing - lo
        return length, elo * length / 2
    length = hi - crossing
    return length, ehi * length / 2


def expose(rows, station, left, right, threshold):
    """Direct per-segment super-threshold computation over [left, right)."""
    if type(left) is not int or type(right) is not int or left > right:
        raise ValueError("BAD_WINDOW")
    duration = Fraction(0)
    excess = Fraction(0)
    for t0, y0, t1, y1 in segments(rows, station):
        lo, hi = max(left, t0), min(right, t1)
        if lo >= hi:
            continue
        d, e = clip_segment(t0, y0, t1, y1, lo, hi, threshold)
        duration += d
        excess += e
    return duration, excess


def shattered(rows, station, left, right, threshold):
    """Independent evaluation: shatter [left, right) at every segment bound
    and every exact threshold crossing, then decide each atomic sub-interval
    by a midpoint sign test and integrate its trapezoid. No case-split
    algebra is shared with clip_segment, so the two paths cross-check."""
    if type(left) is not int or type(right) is not int or left > right:
        raise ValueError("BAD_WINDOW")
    segs = segments(rows, station)
    cuts = {Fraction(left), Fraction(right)}
    for t0, y0, t1, y1 in segs:
        lo, hi = max(left, t0), min(right, t1)
        if lo >= hi:
            continue
        cuts.add(Fraction(lo))
        cuts.add(Fraction(hi))
        if y0 != y1:
            crossing = Fraction(t0) + Fraction((threshold - y0) * (t1 - t0), y1 - y0)
            if lo < crossing < hi:
                cuts.add(crossing)
    points = sorted(cuts)
    duration = Fraction(0)
    excess = Fraction(0)
    for u, v in zip(points, points[1:]):
        for t0, y0, t1, y1 in segs:
            if t0 <= u and v <= t1:
                mid = (u + v) / 2
                ymid = Fraction(y0) + Fraction(y1 - y0, t1 - t0) * (mid - t0)
                if ymid > threshold:
                    yu = Fraction(y0) + Fraction(y1 - y0, t1 - t0) * (u - t0)
                    yv = Fraction(y0) + Fraction(y1 - y0, t1 - t0) * (v - t0)
                    duration += v - u
                    excess += (yu + yv - 2 * threshold) * (v - u) / 2
                break
    return duration, excess


def ratio(value):
    return [value.numerator, value.denominator]


def predict(spec):
    """Independent super-threshold answers for spec["queries"], in order.

    Replays the sample through real Lake calls on a fresh in-memory lake,
    then applies expose() to the rows of each requested snapshot. Agreed
    errors surface as {"error": ...}. Never consults sample()["expected"]
    and never calls analysis_ref.
    """
    lake = Lake()
    try:
        lake.seed(spec["files"])
        for op in spec.get("operations", []):
            if op["op"] == "rewrite":
                lake.rewrite(op["job"], op["inputs"], op["layout"])
            elif op["op"] == "delete":
                lake.delete(op["snapshot"], op["file"], op["pos"])
            else:
                raise ValueError("BAD_OPERATION")
        results = []
        for sid, station, left, right, threshold in spec["queries"]:
            try:
                if type(left) is not int or type(right) is not int or left > right:
                    raise ValueError("BAD_WINDOW")
                view = lake.read(sid)
                duration, excess = expose(view["rows"], station, left, right, threshold)
                results.append({"snapshot": view["snapshot"],
                                "duration": ratio(duration), "excess": ratio(excess)})
            except ValueError as exc:
                results.append({"error": str(exc)})
        return results
    finally:
        lake.catalog.db.close()


def random_check(rounds=ROUNDS, seed=SEED):
    """Small random cross-checks; deterministic under the recorded seed."""
    rng = random.Random(seed)
    queries = 0
    for _ in range(rounds):
        count = rng.randint(1, 8)
        ids = rng.sample(range(1, 10000), count)
        rows = [{"id": ids[k], "station": rng.choice("AB"),
                 "t": rng.randint(0, 24), "reading": rng.randint(-6, 14),
                 "valid": rng.random() < 0.8} for k in range(count)]
        cut = rng.randint(0, count)
        lake = Lake()
        try:
            lake.seed({"f0": rows[:cut], "f1": rows[cut:]})
            view = lake.read(1)
            for _ in range(3):
                left = rng.randint(-3, 25)
                right = left + rng.randint(0, 27)
                threshold = rng.randint(-7, 15)
                station = rng.choice("AB")
                direct = expose(view["rows"], station, left, right, threshold)
                assert direct == shattered(view["rows"], station, left, right, threshold), \
                    (rows, station, left, right, threshold, direct)
                mid = rng.randint(left, right)
                first = expose(view["rows"], station, left, mid, threshold)
                second = expose(view["rows"], station, mid, right, threshold)
                assert (first[0] + second[0], first[1] + second[1]) == direct, \
                    (rows, station, left, mid, right, threshold)
                queries += 1
        finally:
            lake.catalog.db.close()
    print(f"RANDOM_SELF_CHECK_OK seed={seed} rounds={rounds} queries={queries} "
          "(shattered-midpoint equivalence, window additivity)", file=sys.stderr)


EXPLANATIONS = {
    "rise": "单段上升 y=t：H=4 的严格超阈区间从交点 t=4 起算，[2,8) 截断给 duration=4、excess=8；"
            "H=10 与平端点相等按严格大于得零；[7,7) 空窗、未知站点返回两项零，L>R 报 BAD_WINDOW。"
            "推荐索引路径（方案预测，非实测）：站点目录二分 1 次命中 A，叶定位 2 次二分；"
            "唯一段被窗口切断，按边界叶 O(1) 裁剪求值，不进入内部节点，也不扫描窗内片段。"
            "observed 为基线实测：原参照全量读 1 文件 2 行，original 是覆盖/积分而非超阈答案。",
    "fall": "下降段 y=10-t 与上升对称：严格超阈取交点 t=6 左侧，[2,8) 内为 [2,6)，"
            "duration=4、excess=8，说明升降段同一套严格超阈规则。"
            "推荐索引路径（方案预测，非实测）：站点二分 + 叶定位后仅 1 个边界叶，"
            "O(1) 精确求交点与三角形面积；无需枚举任何整数阈值。",
    "fraction": "斜率 2/3 产生有理交点 t=3/2：全窗 duration=3/2、excess=3/4，"
                "子窗 [1,2) 得 1/2 与 1/12，验证约分有理数（分母为正、零写 [0,1]）。"
                "推荐索引路径（方案预测，非实测）：边界叶裁剪时交点 t*=t0+(H-y0)/s 以 Fraction 精确表示，"
                "无浮点；段内截断不触发内部节点。",
    "flat": "平段 y=4：H=4 时严格大于为零（剖面在断点 H=4 取上侧 slab），H=3 时整段计入 "
            "duration=10、excess=10，H=5 为零，锁定阈值相等边界。"
            "推荐索引路径（方案预测，非实测）：若窗内含多段，规范节点以 bisect_right 在断点表上"
            "定位 H 所属左闭 slab，平段恰在断点上时落入上侧零系数 slab。",
    "breaks": "t=5 处 id=2 的无效胜者形成断点，id=3 的有效同刻候选不得顶替，故 A 站无曲线；"
              "B 站间隔 10 恰好插值、间隔 11 断开，孤立点时长为零；H=-3 低于全段时整段计入。"
              "推荐索引路径（方案预测，非实测）：断点与大间隔在构建期即不产生段叶，"
              "查询期叶定位自然跳过空隙，无需在窗内逐点检查有效性。",
    "multi": "三段曲线（升、降、短升）：[-1,13) 覆盖全部段，duration=6、excess=18；"
             "[2,8) 截断首末段后答案相同，验证窗口截断与跨段可加。"
             "推荐索引路径（方案预测，非实测）：全覆窗下叶区间整体由不超过 2⌈log2(S+1)⌉ 个规范节点覆盖，"
             "每节点一次断点二分定位 H=4 的 slab 并 O(1) 求值；截断窗另加至多 2 个边界叶裁剪。",
    "snapshots": "重排只改物理行序，(t,id) 排序后曲线不变，快照 2 答案同快照 1；"
                 "删除后快照 3 只剩孤立点得零；快照 0 为空返回零，99 报 NO_SNAPSHOT。"
                 "句柄绑定构建快照：build 一次性读出并复制数据，后续 delete/rewrite 不改原句柄答案。"
                 "推荐索引路径（方案预测，非实测）：每个快照各建一份静态索引，目录定位只发生在构建期。",
}


def collect():
    random_check()
    records = {}
    for name in NAMES:
        spec = sample(name)
        records[name] = {"observed": run(spec),
                         "predicted": predict(spec),
                         "explanation": EXPLANATIONS[name]}
    return records


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
