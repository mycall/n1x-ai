"""Matched end-to-end trials from inside the isolated service container."""

import hashlib
import json
import mmap
import re
import struct
import time
import urllib.request as http
from pathlib import Path

origin = "http://127.0.0.1:8000"
for attempt in range(240):
    try:
        with http.urlopen(origin + "/health", timeout=3) as resp:
            if resp.status == 200:
                break
    except OSError:
        pass
    time.sleep(5)
else:
    raise RuntimeError("Service failed to become healthy")

files = list(Path("/tmp").glob("ple-trial-*.stats"))
if not files:
    warmup = dict(
        model="qwen/qwen38fn-best",
        messages=[dict(role="user", content="Reply READY.")],
        max_tokens=32,
        temperature=0,
        chat_template_kwargs=dict(enable_thinking=False),
    )
    req = http.Request(
        origin + "/v1/chat/completions",
        data=json.dumps(warmup).encode(),
        headers={"Content-Type": "application/json"},
    )
    with http.urlopen(req, timeout=120) as resp:
        json.load(resp)
    files = list(Path("/tmp").glob("ple-trial-*.stats"))
assert len(files) == 1, files
f = files[0].open("r+b")
control = mmap.mmap(f.fileno(), 4096)


def snapshot():
    return struct.unpack_from("=6Q", control, 16)


def settle():
    # A prefetch job can finish just after the HTTP stream closes.
    last = snapshot()
    for _ in range(20):
        time.sleep(0.05)
        current = snapshot()
        if current == last:
            return current
        last = current
    return last


def mode(enabled):
    struct.pack_into("=Q", control, 8, int(enabled))


def validate(answer, expected):
    if isinstance(expected, str):
        return answer.strip() == expected
    clean = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", answer.strip(), flags=re.I)
    try:
        return json.loads(clean) == expected
    except ValueError:
        return False


def ask(case, pair, enabled, salt, concurrent=False):
    mode(enabled)
    msg = [dict(role="user", content=case["prompt"])]
    body = dict(
        model="qwen/qwen38fn-best",
        messages=msg,
        max_tokens=256,
        temperature=0,
        seed=1120,
        stream=True,
        stream_options=dict(include_usage=True),
        chat_template_kwargs=dict(enable_thinking=False),
        cache_salt=hashlib.sha256(salt.encode()).hexdigest(),
    )
    req = http.Request(
        origin + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    for attempt in range(2):
        a = snapshot()
        start = time.perf_counter()
        first = last = None
        answer = ""
        reason = None
        usage = {}
        with http.urlopen(req, timeout=240) as resp:
            for l in resp:
                if not l.startswith(b"data: ") or l.strip() == b"data: [DONE]":
                    continue
                event = json.loads(l[6:])
                for choice in event.get("choices", []):
                    val = choice["delta"].get("content") or ""
                    if val:
                        last = time.perf_counter()
                        if first is None:
                            first = last
                        answer += val
                    if choice.get("finish_reason"):
                        reason = choice["finish_reason"]
                usage = event.get("usage") or usage
        end = time.perf_counter()
        b = snapshot() if concurrent else settle()
        if answer.strip():
            break
    assert b[0] > a[0], "No PLE calls during request"
    return dict(
        pair=pair,
        kind=case["kind"],
        fixture=case["name"],
        hot=enabled,
        attempt=attempt + 1,
        prompt_tokens=usage["prompt_tokens"],
        cached=usage["prompt_tokens_details"]["cached_tokens"],
        generated=usage["completion_tokens"],
        first_ms=(first - start) * 1000 if first else None,
        end_ms=(end - start) * 1000,
        decode_ms=(last - first) * 1000 if first else None,
        correct=reason == "stop" and validate(answer, case["expected"]),
        finish=reason,
        answer=answer,
        calls=b[0] - a[0],
        requested_rows=b[1] - a[1],
        hits=b[2] - a[2],
        native_reads=b[3] - a[3],
        reader_ms=(b[4] - a[4]) / 1e6,
        resident=b[5],
    )


def emit(row):
    print(json.dumps(row), flush=True)


if __name__ == "__main__":
    data = json.loads(Path("/n1x-config/fixtures.json").read_text())
    warm = data["warm"]
    smoke = dict(
        prompt="Reply with exactly READY.", expected="READY", name="smoke", kind="prime"
    )
    settle()
    for j, on in enumerate([False, True, True]):
        observed = ask(smoke, -1, on, "sanity-warm-" + str(j))
        emit(observed)
    assert observed["hits"] > 0, "Repeated warm-up did not reuse a row"
    emit(ask(warm, -1, True, "shared-archive"))
    for i in range(12):
        for j, case in enumerate(
            [
                *data["cases"][2 * i : 2 * i + 2],
                dict(
                    warm,
                    prompt=warm["prompt"]
                    + f"\nAudit round {i + 1}. Return only the record ID.",
                ),
            ]
        ):
            order = [False, True] if (i + j) % 2 == 0 else [True, False]
            for on in order:
                salt = (
                    "shared-archive"
                    if case["kind"] == "warm-prefix"
                    else f"new-{i}-{j}-{on}"
                )
                emit(ask(case, i, on, salt))
    mode(False)
