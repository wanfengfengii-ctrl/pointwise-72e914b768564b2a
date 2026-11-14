"""Full-scan numerical reference. No persistent analysis index."""
from fractions import Fraction

G = 10


def ratio(value):
    return [value.numerator, value.denominator]


def analyse(lake, station, left, right):
    if type(left) is not int or type(right) is not int or left > right:
        raise ValueError("BAD_WINDOW")
    view = lake.read()
    points = sorted((r["value"] for r in view["rows"]
                     if r["value"]["station"] == station),
                    key=lambda r: (r["t"], r["id"]))
    winners = []
    for row in points:
        if not winners or row["t"] != winners[-1]["t"]:
            winners.append(row)
    covered, integral = 0, Fraction(0)
    for a, b in zip(winners, winners[1:]):
        gap = b["t"] - a["t"]
        if not a["valid"] or not b["valid"] or gap > G:
            continue
        lo, hi = max(left, a["t"]), min(right, b["t"])
        if lo >= hi:
            continue
        slope = Fraction(b["reading"] - a["reading"], gap)
        ylo = a["reading"] + slope * (lo - a["t"])
        yhi = a["reading"] + slope * (hi - a["t"])
        covered += hi - lo
        integral += (ylo + yhi) * (hi - lo) / 2
    return {"snapshot": view["snapshot"], "covered": covered,
            "integral": ratio(integral),
            "mean": ratio(integral / covered) if covered else None}
