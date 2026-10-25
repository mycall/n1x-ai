"""Backport local-directory loading from AIPerf main to the 0.13.0 client.

Upstream: ai-dynamo/aiperf@15585512a97840d8bb38966121aaa96326b48711
Only the offline snapshot resolver changes; metrics and request logic do not.
"""
from importlib.metadata import version
from pathlib import Path
import aiperf.common.tokenizer as module

assert version("aiperf") == "0.13.0"
path = Path(module.__file__)
source = path.read_text()
needle = "        candidates = [name]\n"
replacement = '''        from pathlib import Path
        if Path(name).is_absolute() or name.startswith("."):
            if Path(name).is_dir():
                return name
            raise OSError(f"Local tokenizer path '{name}' is not a directory.")

        candidates = [name]
'''
assert source.count(needle) == 1, "AIPerf resolver changed; review this backport"
path.write_text(source.replace(needle, replacement))
