"""Fresh prompts: distinguish queued HTTP calls from overlapping decode."""

import argparse
import asyncio
import json
import pathlib
import statistics
import time
import uuid
import aiohttp


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("/results"))
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--output-tokens", type=int, default=256)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--thinking", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    out = args.out
    out.mkdir(exist_ok=True, parents=True)
    salt = uuid.uuid4().hex
    samples = []
    rows = []
    stop = asyncio.Event()
    timeout = aiohttp.ClientTimeout(total=1800)
    async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:

        async def metrics():
            while not stop.is_set():
                async with session.get(args.url + "/metrics") as r:
                    r.raise_for_status()
                    data = await r.text()
                row = {"time": time.monotonic()}
                for line in data.splitlines():
                    for name in [
                        "num_requests_running",
                        "num_requests_waiting",
                        "num_preemptions_total",
                    ]:
                        if line.startswith("vllm:" + name + "{"):
                            row[name] = float(line.rsplit(" ", 1)[1])
                samples.append(row)
                await asyncio.sleep(0.1)

        async def ask(i):
            text = (
                f"Independent session {i}.\n"
                + (
                    "The service accepts requests, checks inputs, and returns a response. "
                    * 320
                )
                + "\nWrite a detailed fictional story about building a helpful robot."
            )
            body = {
                "model": "qwen",
                "messages": [{"role": "user", "content": text}],
                "max_tokens": args.output_tokens,
                "ignore_eos": True,
                "temperature": 0,
                "stream": True,
                "stream_options": {"include_usage": True},
                "cache_salt": salt,
                "chat_template_kwargs": {"enable_thinking": args.thinking},
            }
            start = time.monotonic()
            first = None
            usage = None
            content = ""
            async with session.post(
                args.url + "/v1/chat/completions", json=body
            ) as r:
                r.raise_for_status()
                async for line in r.content:
                    if (
                        not line.startswith(b"data: ")
                        or line.strip() == b"data: [DONE]"
                    ):
                        continue
                    event = json.loads(line[6:])
                    usage = event.get("usage") or usage
                    for choice in event.get("choices", []):
                        text = choice.get("delta", {}).get("content") or ""
                        delta = choice.get("delta", {})
                        if (text or delta.get("reasoning") or delta.get("reasoning_content")) and first is None:
                            first = time.monotonic()
                        content += text
            rows.append(
                {
                    "id": i,
                    "start": start,
                    "first": first,
                    "end": time.monotonic(),
                    "usage": usage,
                    "content": content,
                }
            )

        monitor = asyncio.create_task(metrics())
        try:
            await asyncio.gather(*(ask(i) for i in range(args.concurrency)))
        finally:
            stop.set()
            await monitor
    events = sorted([(r["first"], 1) for r in rows] + [(r["end"], -1) for r in rows])
    active = peak = 0
    overlap_seconds = {}
    previous = events[0][0]
    for stamp, delta in events:
        overlap_seconds[active] = overlap_seconds.get(active, 0) + stamp - previous
        active += delta
        peak = max(peak, active)
        previous = stamp
    duration = max(r["end"] for r in rows) - min(r["start"] for r in rows)
    result = {
        "concurrency": args.concurrency,
        "thinking": args.thinking,
        "output_tokens": args.output_tokens,
        "duration_s": duration,
        "output_tokens_s": sum(r["usage"]["completion_tokens"] for r in rows)
        / duration,
        "max_running": max(s.get("num_requests_running", 0) for s in samples),
        "max_overlapping_decode_intervals": peak,
        "generation_overlap_seconds": overlap_seconds,
        "mean_ttft_s": statistics.mean(r["first"] - r["start"] for r in rows),
        "mean_completion_s": statistics.mean(r["end"] - r["start"] for r in rows),
        "rows": rows,
        "samples": samples,
    }
    (out / "probe.json").write_text(json.dumps(result, indent=2))
    print(
        json.dumps({k: v for k, v in result.items() if k not in ["rows", "samples"]}),
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
