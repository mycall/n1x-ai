import collections
import json
import random
import statistics
from pathlib import Path

d = Path(__file__).resolve().parent


def rows(file):
    return [
        json.loads(line)
        for line in (d / file).read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def matched(a, b):
    return all(
        a[k] == b[k]
        for k in ("prompt_tokens", "cached", "generated", "answer", "finish")
    )


def summary(records, concurrent=False):
    pairs = collections.defaultdict(list)
    for r in records:
        pairs[r["pair"]].append(r)
    report = {"pairs": len(pairs)}
    raw = []
    hot = []
    equivalent = []
    correct = 0
    exact = 0
    total = 0
    for pair in pairs.values():
        assert len(pair) == 2 and {r["hot"] for r in pair} == {True, False}
        a, b = sorted(pair, key=lambda x: x["hot"])
        raw.append(a)
        hot.append(b)
        ar = a["requests"] if concurrent else [a]
        br = b["requests"] if concurrent else [b]
        correct += sum(r["correct"] for r in ar + br)
        total += len(ar + br)
        exact += sum(x["answer"] == y["answer"] for x, y in zip(ar, br))
        if all(matched(x, y) for x, y in zip(ar, br)):
            equivalent.append((a, b, pair[0]["hot"]))
    report.update(
        correct_requests=correct,
        total_requests=total,
        identical_answer_pairs=exact,
        equal_work_pairs=len(equivalent),
        cached_token_counts=sorted(
            {
                i["cached"]
                for r in raw + hot
                for i in (r["requests"] if concurrent else [r])
            }
        ),
    )
    for label, arm in [("off", raw), ("on", hot)]:

        def total_for(k):
            return sum(r[k] for r in arm)

        report[label] = dict(
            whole_request_median_ms=statistics.median(r["end_ms"] for r in arm),
            calls=total_for("calls"),
            requested=total_for("requested_rows"),
            hits=total_for("hits"),
            reads=total_for("native_reads"),
            reader_ms=total_for("reader_ms"),
            peak_rows=max(r["resident"] for r in arm),
        )
    for group, subset in [
        ("all", [(a, b) for a, b in zip(raw, hot)]),
        ("equal_work", [(a, b) for a, b, _ in equivalent]),
    ]:
        detail = {}
        for metric in ["end_ms"] if concurrent else ["end_ms", "first_ms", "decode_ms"]:
            pct = [
                100 * (1 - b[metric] / a[metric])
                for a, b in subset
                if a[metric] and b[metric] is not None
            ]
            if not pct:
                continue
            rng = random.Random(1120)
            boot = sorted(
                statistics.median(rng.choices(pct, k=len(pct))) for _ in range(10000)
            )
            detail[metric] = dict(
                median_percent_faster=statistics.median(pct),
                bootstrap95=[boot[249], boot[9749]],
                faster_pairs=sum(x > 0 for x in pct),
                n=len(pct),
            )
        report[group] = detail
    for first in (False, True):
        deltas = [
            100 * (1 - b["end_ms"] / a["end_ms"])
            for a, b, hotfirst in equivalent
            if hotfirst == first
        ]
        if deltas:
            report["hot_first" if first else "off_first"] = statistics.median(deltas)
    return report


data = [r for r in rows("requests.jsonl") if r["pair"] >= 0]
report = {
    kind: summary([r for r in data if r["kind"] == kind])
    for kind in sorted({r["kind"] for r in data})
}
if (d / "concurrent.jsonl").is_file():
    report["concurrent"] = summary(rows("concurrent.jsonl"), concurrent=True)
if (d / "append.jsonl").is_file():
    report["append"] = summary([r for r in rows("append.jsonl") if r["pair"] >= 0])
for k in ("parity", "footprint"):
    report[k] = json.loads((d / (k + ".json")).read_text(encoding="utf-8-sig"))
report["protocol"] = json.loads((d / "protocol.json").read_text(encoding="utf-8-sig"))
(d / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
for k, v in report.items():
    if "equal_work" in v:
        print(
            k,
            v["correct_requests"],
            v["total_requests"],
            v["equal_work_pairs"],
            v["equal_work"].get("end_ms"),
            "hits",
            round(v["on"]["hits"] / v["on"]["requested"], 3),
        )
