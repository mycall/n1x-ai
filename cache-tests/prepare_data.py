"""Prepare the same pinned LongBench-v2 canary as halo-ai, before model startup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.request

REVISION = '2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9'
SHA256 = '15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2'
SIZE = 465490535
URL = f'https://huggingface.co/datasets/zai-org/LongBench-v2/resolve/{REVISION}/data.json'
PROMPT = '''Please read the following text and answer the question below.

<text>
{context}
</text>

What is the correct answer to this question: {question}
Choices:
(A) {choice_A}
(B) {choice_B}
(C) {choice_C}
(D) {choice_D}

Format your response as follows: "The correct answer is (insert answer here)".'''

def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def prepare(directory):
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / 'longbench-v2.json'
    if not source.exists():
        partial = source.with_suffix('.part')
        offset = partial.stat().st_size if partial.exists() else 0
        request = urllib.request.Request(URL, headers={'Range': f'bytes={offset}-'} if offset else {})
        with urllib.request.urlopen(request, timeout=120) as response:
            append = offset > 0 and response.status == 206
            with partial.open('ab' if append else 'wb') as out:
                while chunk := response.read(8 * 1024 * 1024):
                    out.write(chunk)
        if partial.stat().st_size != SIZE or digest(partial) != SHA256:
            raise RuntimeError('Dataset checksum/size mismatch; partial retained')
        os.replace(partial, source)
    if source.stat().st_size != SIZE or digest(source) != SHA256:
        raise RuntimeError('Pinned dataset verification failed')
    # Preparation runs on Windows before the model: the inference client loads
    # only these six selected samples, not the complete 465 MB dataset.
    items = json.loads(source.read_text(encoding='utf-8'))
    assert len(items) == 503
    cells = {}
    for item in sorted(items, key=lambda x: x['_id']):
        cells.setdefault((item['difficulty'], item['length']), item)
    selected = []
    for cell in sorted(cells):
        item = cells[cell]
        selected.append({'id': item['_id'], 'answer': item['answer'],
                         'difficulty': item['difficulty'], 'length': item['length'],
                         'domain': item['domain'], 'prompt': PROMPT.format(**item)})
    result = {'revision': REVISION, 'sha256': SHA256, 'source': URL,
              'selection': 'Smallest sample ID in each difficulty/length cell; matches halo-ai canary',
              'samples': selected}
    destination = directory / 'longbench-canary.json'
    destination.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    print(f'Prepared {len(selected)} pinned samples: {destination}', flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    prepare(parser.parse_args().directory)
