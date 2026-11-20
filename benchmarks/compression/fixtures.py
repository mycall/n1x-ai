"""Recreate the original trial corpus from versioned Git blobs."""

import json
import re
import subprocess
from pathlib import Path

directory = Path(__file__).resolve().parent
revision = "571337a20851bf9ac3b435888a98e905f42ab4f4"


def tracked(pattern):
    parent = Path(pattern).parent.as_posix()
    names = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", revision, "--", parent], text=True
    ).splitlines()
    return [Path(x) for x in names if Path(x).match(pattern)]


def content(path):
    return subprocess.check_output(
        ["git", "show", f"{revision}:{path.as_posix()}"]
    ).decode("utf-8-sig")


docs = [p for p in tracked("wiki/*.md") if len(content(p).encode("utf-8")) >= 5000]
functions = []
for p in tracked("scripts/*.ps1"):
    source = content(p)
    for m in re.finditer(r"^function\s+([\w-]+)\b", source, flags=re.I | re.M):
        excerpt = source[m.start() :].splitlines()[:7]
        excerpt = [excerpt[0]] + [
            line for line in excerpt[1:] if not re.search(r"^function\s", line, re.I)
        ]
        functions.append((m[1], "\n".join(excerpt)))

cases = []
for i in range(12):
    p = docs[i % len(docs)]
    tag = f"N1X-{7301 + i * 67}-A"
    snippet = content(p)[:12000]
    # Factual retrieval with a checkable, unique answer.
    insert = snippet.find("\n", int(len(snippet) * 0.55))
    note = (
        snippet[:insert]
        + f"\nRelease verification identifier: {tag}\n"
        + snippet[insert:]
    )
    cases.append(
        dict(
            kind="document",
            name=p.name,
            expected=tag,
            prompt=note
            + "\nReturn only the release verification identifier in this document.",
        )
    )
    # Read real function declarations. Excerpts vary independently of the document workload.
    selected = [functions[(i * 9 + j) % len(functions)] for j in range(9)]
    cases.append(
        dict(
            kind="code",
            name=f"functions-{i}",
            expected=[name for name, _ in selected],
            prompt="List every PowerShell function declared in the excerpts below, in declaration order. "
            "Return only a JSON array of the exact function names.\n\n"
            + "\n\n".join(s for _, s in selected),
        )
    )
assert len(docs) >= 17
archive = "\n\n".join(content(p)[:7500] for p in docs[12:17])
warm = dict(
    kind="warm-prefix",
    name="wiki-pack",
    expected="N1X-9041-W",
    prompt=archive
    + "\nThe deployment record ID is N1X-9041-W. Return just the deployment record ID.",
)
(directory / "fixtures.json").write_text(
    json.dumps(dict(cases=cases, warm=warm)), encoding="utf-8"
)

new_turns = []
for path in tracked("benchmarks/Client/*.cs"):
    source = content(path)
    if len(source) > 4300:
        new_turns.append(dict(name=path.name, text=source[:9000]))
    if len(new_turns) == 12:
        break
if len(new_turns) != 12:
    raise ValueError("Need twelve distinct source excerpts")
(directory / "new-turns.json").write_text(json.dumps(new_turns), encoding="utf-8")
