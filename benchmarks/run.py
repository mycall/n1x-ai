"""Benchmark the existing service; never load a second model.

Raw artifacts are deliberately separate from the curated wiki results.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import urllib.request
import uuid

HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(url, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with HTTP.open(req, timeout=3600) as response:
        return response.read().decode()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def command(args, directory, name):
    directory.mkdir(parents=True, exist_ok=True)
    save(directory / f"{name}-command.json", list(map(str, args)))
    print(f"Starting {name}: {directory.name}", flush=True)
    start = time.monotonic()
    with (directory / f"{name}.log").open("w") as log:
        result = subprocess.run(list(map(str, args)), stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        tail = (directory / f"{name}.log").read_text()[-6000:]
        raise RuntimeError(f"{name} exited {result.returncode}\n{tail}")
    print(f"Finished {name} in {time.monotonic() - start:.1f}s", flush=True)


def snapshot(args, directory, label):
    for name, url in (("vllm", args.url + "/metrics"), ("lmcache", "http://127.0.0.1:8080/metrics")):
        try:
            text = request(url)
        except Exception as error:
            text = f"# unavailable: {error}\n"
        (directory / f"{label}-{name}.prom").write_text(text)


def vllm(args):
    for length in args.input_lengths:
        for concurrency in args.concurrency:
            directory = args.out / f"vllm-{length}-c{concurrency}"
            directory.mkdir(parents=True)
            snapshot(args, directory, "before")
            extra = {"chat_template_kwargs": {"enable_thinking": False},
                     "cache_salt": f"{args.run_id}-vllm-{length}-{concurrency}"}
            command(["vllm", "bench", "serve", "--base-url", args.url,
                     "--backend", "openai-chat", "--endpoint", "/v1/chat/completions",
                     "--model", "qwen", "--tokenizer", "/model", "--dataset-name", "random",
                     "--random-input-len", length, "--random-output-len", args.output_tokens,
                     "--random-range-ratio", "0", "--num-prompts", args.requests,
                     "--max-concurrency", concurrency, "--seed", args.seed,
                     "--num-warmups", "1", "--ignore-eos", "--extra-body", json.dumps(extra),
                     "--save-result", "--save-detailed", "--result-dir", directory,
                     "--result-filename", "result.json", "--metric-percentiles", "50,95",
                     "--percentile-metrics", "ttft,tpot,e2el", "--disable-tqdm"], directory, "vllm")
            snapshot(args, directory, "after")
            result = json.loads((directory / "result.json").read_text())
            if result.get("completed") != args.requests:
                raise RuntimeError(f"Incomplete vLLM benchmark: {directory}")
            print(f"  {length} tokens / C{concurrency}: {result['output_throughput']:.2f} output tokens/s; "
                  f"mean TTFT {result['mean_ttft_ms'] / 1000:.2f}s; {result['completed']} completed", flush=True)


def aiperf(args):
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained("/model", local_files_only=True)
    # Natural prose, with independent lookup codes in each session.
    prose = "Reference notes: the service accepts requests, checks inputs, and returns a response. "
    filler = tokenizer.decode(tokenizer.encode(prose * 3000, add_special_tokens=False)[:16000])
    for concurrency in args.agent_concurrency:
        directory = args.out / f"aiperf-c{concurrency}"
        directory.mkdir(parents=True)
        dataset, expected = [], {}
        for session in range(args.conversations):
            codes = [f"K{session}{turn}Z{args.seed}" for turn in range(4)]
            context = "\n".join(f"Key {i + 1}: {code}" for i, code in enumerate(codes))
            turns = []
            for turn in range(4):
                text = (f"Session {session}. Memorize these lookup keys.\n{context}\n{filler}\n"
                        if turn == 0 else "")
                text += f"Return only the exact value for Key {turn + 1} from this session."
                turns.append({"text": text, "output_length": 32})
            dataset.append({"session_id": f"session-{session}", "turns": turns})
            expected[f"session-{session}"] = codes
        path = directory / "conversations.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in dataset))
        save(directory / "expected.json", expected)
        snapshot(args, directory, "before")
        command(["/opt/aiperf/bin/aiperf", "profile", "--model", "qwen",
                 "--tokenizer", "/model", "--url", args.url, "--endpoint-type", "chat",
                 "--endpoint", "/v1/chat/completions", "--streaming",
                 "--input-file", path, "--custom-dataset-type", "multi_turn",
                 "--conversation-num", args.conversations, "--concurrency", concurrency,
                 "--random-seed", args.seed, "--extra-inputs", json.dumps({
                     "temperature": 0, "chat_template_kwargs": {"enable_thinking": False},
                     "cache_salt": f"{args.run_id}-aiperf-{concurrency}"}),
                 "--artifact-dir", directory / "artifacts", "--export-level", "raw",
                 "--ui", "simple", "--no-server-metrics", "--workers-max", "1"], directory, "aiperf")
        snapshot(args, directory, "after")
        summarize_agent(directory, args.conversations * 4)


def summarize_agent(directory, expected_count):
    expected = json.loads((directory / "expected.json").read_text())
    rows = []
    raw = directory / "artifacts" / "profile_export_raw.jsonl"
    for line in raw.read_text().splitlines():
        record = json.loads(line)
        meta = record["metadata"]
        if meta["benchmark_phase"] != "profiling":
            continue
        text, finish, first_token = "", None, None
        for response in record.get("responses", []):
            for packet in response.get("packets", []):
                if packet.get("name") != "data" or packet["value"] == "[DONE]":
                    continue
                event = json.loads(packet["value"])
                for choice in event.get("choices", []):
                    content = choice.get("delta", {}).get("content") or ""
                    if content and first_token is None:
                        first_token = response["perf_ns"]
                    text += content
                    finish = choice.get("finish_reason") or finish
        answer = expected[meta["conversation_id"]][meta["turn_index"]]
        rows.append({"session": meta["conversation_id"], "turn": meta["turn_index"],
                     "text": text, "expected": answer, "finish_reason": finish,
                     "correct": record.get("status") == 200 and finish == "stop" and text.strip() == answer,
                     "start_ns": meta["request_start_ns"], "end_ns": meta["request_end_ns"],
                     "latency_s": (meta["request_end_ns"] - meta["request_start_ns"]) / 1e9,
                     "ttft_s": (first_token - record["start_perf_ns"]) / 1e9 if first_token else None})
    if len(rows) != expected_count:
        raise RuntimeError(f"Expected {expected_count} turns, found {len(rows)}; inspect AIPerf errors")
    duration = (max(r["end_ns"] for r in rows) - min(r["start_ns"] for r in rows)) / 1e9
    correct = sum(r["correct"] for r in rows)
    summary = {"turns": len(rows), "correct": correct, "duration_s": duration,
               "correct_turns_per_s": correct / duration,
               "first_turn_mean_ttft_s": statistics.mean(r["ttft_s"] for r in rows if r["turn"] == 0 and r["ttft_s"] is not None),
               "followup_mean_ttft_s": statistics.mean(r["ttft_s"] for r in rows if r["turn"] > 0 and r["ttft_s"] is not None),
               "responses": rows}
    save(directory / "accuracy.json", summary)
    print(f"  {correct}/{len(rows)} correct turns; {summary['correct_turns_per_s']:.3f} correct turns/s; "
          f"follow-up TTFT {summary['followup_mean_ttft_s']:.2f}s", flush=True)


def ruler(args):
    # Use the upstream generator and scoring function unchanged. The HTTP adapter
    # applies the server's chat template; this is a subset, not the full leaderboard.
    spec = importlib.util.spec_from_file_location("ruler_metrics", "/opt/RULER/scripts/eval/synthetic/constants.py")
    metrics = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(metrics)
    summaries = []
    for length in args.context_lengths:
        for task in ("niah_single_1", "vt"):
            output_limit = 512 if task == "vt" else 128
            directory = args.out / f"ruler-{length}-{task}"
            directory.mkdir(parents=True)
            command([sys.executable, "/opt/RULER/scripts/data/prepare.py",
                     "--save_dir", directory / "data", "--benchmark", "synthetic",
                     "--task", task, "--tokenizer_path", "/model", "--tokenizer_type", "hf",
                     "--max_seq_length", length - output_limit - 128, "--model_template_type", "base",
                     "--num_samples", args.samples, "--random_seed", args.seed], directory, "prepare")
            dataset = directory / "data" / task / "validation.jsonl"
            rows = [json.loads(line) for line in dataset.read_text().splitlines()]
            if len(rows) != args.samples:
                raise RuntimeError("RULER generation returned wrong sample count")
            snapshot(args, directory, "before")
            results = []
            for row in rows:
                body = {"model": "qwen", "messages": [{"role": "user", "content": row["input"]}],
                        "temperature": 0, "max_tokens": output_limit, "chat_template_kwargs": {"enable_thinking": False},
                        "cache_salt": f"{args.run_id}-{task}-{length}-{row['index']}"}
                count = json.loads(request(args.url + "/tokenize", {k: v for k, v in body.items()
                                   if k in ("model", "messages", "chat_template_kwargs")}))["count"]
                if count + output_limit > length:
                    raise RuntimeError(f"Rendered input {count} exceeds {length} minus output budget")
                start = time.monotonic()
                response = json.loads(request(args.url + "/v1/chat/completions", body))
                choice = response["choices"][0]
                row.update(pred=choice["message"].get("content") or "", elapsed_s=time.monotonic() - start,
                           usage=response["usage"], finish_reason=choice["finish_reason"])
                results.append(row)
                with (directory / "predictions.jsonl").open("a") as output:
                    output.write(json.dumps(row) + "\n")
                print(f"RULER {task} {length}: {len(results)}/{len(rows)}; {count} input tokens", flush=True)
            score = metrics.string_match_all([r["pred"] for r in results], [r["outputs"] for r in results])
            summary = {"task": task, "context_budget": length, "output_limit": output_limit,
                       "samples": len(results), "score_percent": score,
                       "prompt_tokens_min": min(r["usage"]["prompt_tokens"] for r in results),
                       "prompt_tokens_max": max(r["usage"]["prompt_tokens"] for r in results),
                       "mean_elapsed_s": statistics.mean(r["elapsed_s"] for r in results),
                       "truncated": sum(r["finish_reason"] == "length" for r in results)}
            save(directory / "summary.json", summary)
            print(f"  {task}: {score:.1f}% on {len(results)} samples; {summary['truncated']} truncated", flush=True)
            summaries.append(summary)
            save(args.out / "ruler-summary.json", summaries)
            snapshot(args, directory, "after")


def scheduler(args):
    command([sys.executable, "/benchmarks/scheduler_probe.py", "--out", args.out / "scheduler",
             "--concurrency", args.scheduler_concurrency, "--output-tokens", args.scheduler_output_tokens,
             "--url", args.url],
            args.out, "scheduler-probe")
    result = json.loads((args.out / "scheduler" / "probe.json").read_text())
    print(json.dumps({key: value for key, value in result.items() if key not in ("rows", "samples")}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["all", "vllm", "aiperf", "ruler", "scheduler", "speculation"], default="all")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--out", type=Path, default=Path("/results"))
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4, 8, 16])
    parser.add_argument("--input-lengths", type=int, nargs="+", default=[4096, 16384])
    parser.add_argument("--requests", type=int, default=16)
    parser.add_argument("--output-tokens", type=int, default=128)
    parser.add_argument("--agent-concurrency", type=int, nargs="+", default=[1, 2, 4, 8, 16])
    parser.add_argument("--conversations", type=int, default=16)
    parser.add_argument("--context-lengths", type=int, nargs="+", default=[16384, 65536, 131072, 262144])
    parser.add_argument("--samples", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--scheduler-concurrency", type=int, default=4)
    parser.add_argument("--scheduler-output-tokens", type=int, default=256)
    args = parser.parse_args()
    args.run_id = uuid.uuid4().hex
    args.out.mkdir(parents=True, exist_ok=True)
    save(args.out / "settings.json", {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()})
    request(args.url + "/health")
    command(["uv", "pip", "freeze", "--python", sys.executable], args.out, "client-packages")
    command(["uv", "pip", "freeze", "--python", "/opt/aiperf/bin/python"], args.out, "aiperf-packages")
    for name in ("vllm", "aiperf", "ruler"):
        if args.suite in ("all", name):
            globals()[name](args)
    if args.suite == "scheduler":
        scheduler(args)
    if args.suite == "speculation":
        command([sys.executable, "/benchmarks/speculation_probe.py", "--out", args.out / "speculation",
                 "--url", args.url], args.out, "speculation-probe")
    save(args.out / "complete.json", {"completed": True, "suite": args.suite})


if __name__ == "__main__":
    main()
