"""Fast completeness check for a previously verified native PLE copy."""
import json
from pathlib import Path

root = Path('/table')
manifest = json.loads((root / 'n1x-copy-manifest.json').read_text())
assert manifest['sourceRevision'] == '50511b0a41aa1d34b8beb7e5d4bb06a0b650dc14'
records = {row['name']: row for row in manifest['files']}
for number in range(5, 38):
    name = f'model-{number:05d}-of-00131.safetensors'
    assert records[name]['bytes'] > 0
    assert (root / name).stat().st_size == records[name]['bytes']
print('Native PLE revision and file sizes verified.')
