import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from serve_ab import ask, emit, mode, settle, snapshot

cases = json.loads(Path("/n1x-config/fixtures.json").read_text())["cases"]
with ThreadPoolExecutor(2) as pool:
    for i in range(12):
        for on in [False, True] if i % 2 == 0 else [True, False]:
            mode(on)
            start_gate = threading.Barrier(3)

            def submit(k):
                start_gate.wait()
                row = ask(
                    cases[2 * i + k], i, on, f"concurrent-{i}-{k}-{on}", concurrent=True
                )
                # Stats belong to the whole pair of simultaneous requests.
                return {
                    key: val
                    for key, val in row.items()
                    if key
                    not in [
                        "calls",
                        "requested_rows",
                        "hits",
                        "native_reads",
                        "reader_ms",
                        "resident",
                    ]
                }

            tasks = [pool.submit(submit, k) for k in range(2)]
            before = snapshot()
            start = time.perf_counter()
            start_gate.wait()
            rows = [task.result() for task in tasks]
            duration = (time.perf_counter() - start) * 1000
            after = settle()
            emit(
                dict(
                    pair=i,
                    hot=on,
                    requests=rows,
                    end_ms=duration,
                    calls=after[0] - before[0],
                    requested_rows=after[1] - before[1],
                    hits=after[2] - before[2],
                    native_reads=after[3] - before[3],
                    reader_ms=(after[4] - before[4]) / 1e6,
                    resident=after[5],
                )
            )
mode(False)
