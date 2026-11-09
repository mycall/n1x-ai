"""Keep the pinned Qwen QSA ring compatible with power-of-two cache blocks."""
import hashlib
import json
from pathlib import Path
import sys


EXPECTED_SHA256 = '56a790422da66bffa5aef3e16dff346a87e6d21c6d12231024d3a0326311f790'
OLD = '        capacity = self.compress_ratio * cdiv(span, self.compress_ratio)\n'
NEW = (
    '        # n1x-qsa-ring: retain all speculative rows without a 12-slot ring\n'
    '        # that cannot divide the power-of-two attention block.\n'
    '        groups = cdiv(span, self.compress_ratio)\n'
    '        capacity = self.compress_ratio * (1 << (groups - 1).bit_length())\n'
)


def rewrite(source):
    if source.count(OLD) != 1:
        raise RuntimeError('QSA ring source anchor changed')
    updated = source.replace(OLD, NEW)
    compile(updated, 'qsa_cache.py', 'exec')
    return updated


def patch(site):
    site = Path(site)
    path = site / 'vllm/models/qwen4_exp/common/qsa_cache.py'
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    if before != EXPECTED_SHA256:
        raise RuntimeError('Unexpected QSA cache source; review the ring patch before reuse')
    updated = rewrite(path.read_text(encoding='utf-8'))
    path.write_text(updated, encoding='utf-8', newline='\n')
    record = dict(original_sha256=before,
                  patched_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  contract='power-of-two-v1', qualification='GPU qualification required')
    (site / 'n1x-qsa-ring-patch.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record))


if __name__ == '__main__':
    patch(sys.argv[1])
