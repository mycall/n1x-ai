"""Add target capture to the pinned MyLLMBox v5.4 Linux ARM64 overlay."""
import hashlib
import json
from pathlib import Path
import shutil
import sys


# From the audited model.py layer of the digest pinned in the Dockerfile.
EXPECTED_MODEL_SHA256 = '120f024d1f94fe23340d45a0554f6ef35855ec1eaefcd1a01adc30683cbcd130'
GUARD = '"mtp",\n            "ngram",\n            "ngram_gpu",\n        }:'
ADAPTER = Path(__file__).with_name('n1x_dflash_capture.py')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch(site, manifest_path):
    site = Path(site)
    vllm = site / 'vllm'
    model = vllm / 'models/qwen4_exp/nvidia/model.py'
    config = vllm / 'model_executor/models/config.py'
    manifest = json.loads(Path(manifest_path).read_text())
    before = {path.relative_to(vllm).as_posix(): digest(path) for path in (model, config)}
    if before['models/qwen4_exp/nvidia/model.py'] != EXPECTED_MODEL_SHA256:
        raise RuntimeError('Unexpected MyLLMBox target source; do not reuse this capture patch')
    for name, value in before.items():
        if manifest.get(name) != value:
            raise RuntimeError(f'MyLLMBox source changed since dependency audit: {name}')
    source = config.read_text(encoding='utf-8')
    if source.count(GUARD) != 1:
        raise RuntimeError('Qwen4Exp speculation guard changed')
    adapter = ADAPTER
    adapter_source = adapter.read_text(encoding='utf-8')
    config_source = source.replace(GUARD, GUARD.replace('        }:', '            "dflash",\n        }:'))
    model_source = model.read_text(encoding='utf-8') + (
        '\n# n1x-ai: pinned DFlash2 target-feature capture\n'
        'import sys as _n1x_sys\n'
        'from n1x_dflash_capture import apply as _n1x_dflash_apply\n'
        '_n1x_dflash_apply(_n1x_sys.modules[__name__])\n')
    # Validate every proposed Python file before changing the installed overlay.
    for name, text in ((str(config), config_source), (str(model), model_source),
                       (str(adapter), adapter_source)):
        compile(text, name, 'exec')
    shutil.copyfile(adapter, site / adapter.name)
    config.write_text(config_source, encoding='utf-8', newline='\n')
    model.write_text(model_source, encoding='utf-8', newline='\n')
    record = dict(original_sha256=before,
                  patched_sha256={path.relative_to(vllm).as_posix(): digest(path) for path in (model, config)},
                  adapter_sha256=digest(adapter),
                  qualification='Source guards only; Linux GPU qualification pending')
    (site / 'n1x-myllmbox-dflash-patches.json').write_text(json.dumps(record, indent=2) + '\n')
    print('Applied pinned MyLLMBox DFlash2 capture; GPU qualification pending')


if __name__ == '__main__':
    patch(sys.argv[1], sys.argv[2])
