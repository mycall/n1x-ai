"""Measure resumed turns with a block-aligned cached prefix and genuinely new material."""

import json
from pathlib import Path

from serve_ab import ask, emit, mode
from tokenizers import Tokenizer

base = Path("/n1x-config")
tok = Tokenizer.from_file("/model/tokenizer.json")
warm = json.loads((base / "fixtures.json").read_text())["warm"]
prefix = tok.decode(
    tok.encode(warm["prompt"], add_special_tokens=False).ids[:8210],
    skip_special_tokens=False,
)
salt = "append-archive-1120"
prime = dict(
    name="aligned-archive",
    kind="append",
    expected="READY",
    prompt=prefix + "\nReply with exactly READY.",
)
emit(ask(prime, -1, True, salt))
for i, item in enumerate(json.loads((base / "new-turns.json").read_text())):
    tag = f"REV-{8042 + i * 31}"
    excerpt = tok.decode(
        tok.encode(item["text"], add_special_tokens=False).ids[:800],
        skip_special_tokens=False,
    )
    case = dict(
        kind="append",
        name=item["name"],
        expected=tag,
        prompt=prefix
        + f"\nNew review event {i}. The current revision is {tag}.\n"
        + excerpt
        + "\nReturn only the current revision from the new review event.",
    )
    for on in [False, True] if i % 2 == 0 else [True, False]:
        emit(ask(case, i, on, salt))
mode(False)
