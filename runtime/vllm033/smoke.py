"""Run three matched sets of short greedy requests on an idle 0.33 server."""

import argparse
import json
import re
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

COPY_TEXT = " ".join(str(i) for i in range(1, 21))
CASES = (
    ("copy", "Repeat this line exactly, with no other text:\n" + COPY_TEXT, COPY_TEXT),
    (
        "recall",
        "The delivery record says North=19, East=41 and West=6. Return just the value for East.",
        "41",
    ),
    ("arithmetic", "What is 13 times 7? Reply with only the number.", "91"),
    (
        "json",
        "Return a JSON object with exactly the key color set to the string blue. No markdown.",
        {"color": "blue"},
    ),
)


def run(base, target_only=False):
    client = build_opener(ProxyHandler({}))

    def read(path, body=None):
        request = Request(
            base + path,
            data=json.dumps(body).encode() if body else None,
            headers={"Content-Type": "application/json"},
        )
        with client.open(request, timeout=300) as response:
            return response.read().decode()

    def counts():
        metrics = read("/metrics")
        result = []
        for counter in ("draft", "accepted"):
            rows = re.findall(
                rf"^vllm:spec_decode_num_{counter}_tokens_total(?:\{{[^}}]*\}})?\s+(\S+)",
                metrics,
                re.MULTILINE,
            )
            if not rows:
                raise RuntimeError(f"Missing DFlash {counter} token counter")
            result.append(sum(int(float(value)) for value in rows))
        return result

    read("/health")
    attempts = []
    before = None if target_only else counts()
    for trial in range(1, 4):
        answers = []
        for name, prompt, expected in CASES:
            request = {
                "model": "qwen/qwen38fn-best",
                "messages": [{"role": "user", "content": prompt}],
                "chat_template_kwargs": {"enable_thinking": False},
                "temperature": 0,
                "seed": 4321,
                "max_tokens": 96,
                "cache_salt": uuid4().hex,
            }
            try:
                reply = json.loads(read("/v1/chat/completions", request))["choices"][0]
                content = reply["message"]["content"]
                value = (content or "").strip()
                if isinstance(expected, dict):
                    try:
                        value = json.loads(value)
                    except ValueError:
                        value = None
                stopped = reply["finish_reason"]
                answers.append(
                    dict(
                        case=name,
                        content=content,
                        finish_reason=stopped,
                        correct=value == expected and stopped == "stop",
                    )
                )
            except (URLError, TimeoutError) as error:
                answers.append(dict(case=name, error=str(error), correct=False))

        draft = accepted = None
        if before is not None:
            deadline = time.monotonic() + 15
            while True:
                after = counts()
                draft, accepted = (end - start for start, end in zip(before, after))
                time.sleep(0.5)
                if (accepted > 0 and counts() == after) or time.monotonic() >= deadline:
                    break
            before = after
        correct = sum(row["correct"] for row in answers)
        attempts.append(
            dict(
                attempt=trial,
                answers=answers,
                correct=correct,
                draft_tokens=draft,
                accepted_tokens=accepted,
                passed=correct == len(CASES) and (target_only or 0 < accepted <= draft),
            )
        )

    proposed = None if target_only else sum(a["draft_tokens"] for a in attempts)
    accepted = None if target_only else sum(a["accepted_tokens"] for a in attempts)
    summary = dict(
        arm="target_only" if target_only else "dflash2_k3",
        attempts=attempts,
        correct=sum(a["correct"] for a in attempts),
        requests=sum(len(a["answers"]) for a in attempts),
        draft_tokens=proposed,
        accepted_tokens=accepted,
        acceptance_rate=accepted / proposed if proposed else None,
        passed_attempts=sum(a["passed"] for a in attempts),
    )
    print(json.dumps(summary))
    if summary["passed_attempts"] != len(attempts):
        raise RuntimeError("At least one qualification attempt failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:18133")
    parser.add_argument(
        "--target-only",
        action="store_true",
        help="check a dedicated target-only control",
    )
    args = parser.parse_args()
    run(args.base.rstrip("/"), args.target_only)
