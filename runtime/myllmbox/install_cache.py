"""Install pinned LMCache dependencies without replacing the MBX vLLM overlay."""
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

EXPECTED_CORE = {'torch': '2.13.0+cu130', 'vllm': '0.32.0',
                 'flashinfer-python': '0.7.0.post1', 'triton': '3.7.1',
                 'nvidia-nccl-cu13': '2.30.7'}
SOURCE_BUILD_REQUIREMENTS = (
    'setuptools==80.10.2', 'setuptools-scm==10.3.4', 'ninja==1.13.2',
    'packaging==26.3', 'grpcio==1.78.0', 'grpcio-tools==1.78.0', 'wheel==0.48.0',
)


def source_build_options(value):
    if value not in ('0', '1'):
        raise ValueError('N1X_LMCACHE_FROM_SOURCE must be 0 or 1')
    # Use the image's existing Torch/CUDA ABI, not an isolated build's Torch.
    # Reinstall/no-cache avoids reusing an installed or locally cached wheel.
    return (['--no-binary', 'lmcache', '--no-build-isolation-package', 'lmcache',
             '--reinstall-package', 'lmcache', '--no-cache'] if value == '1' else [])


def cache_constraints(text, core_versions):
    if core_versions != EXPECTED_CORE:
        raise RuntimeError('Pinned MyLLMBox core versions changed; review the image')
    for old, new in [('torch==2.13.0', 'torch==2.13.0+cu130'),
                     ('nvidia-nccl-cu13==2.29.7', 'nvidia-nccl-cu13==2.30.7')]:
        lines = text.splitlines()
        if lines.count(old) != 1:
            raise RuntimeError(f'Unexpected shared constraint: {old}')
        text = '\n'.join(new if line == old else line for line in lines) + '\n'
    # The pinned image ships NCCL 2.30.7 although its installed Torch metadata
    # requires 2.29.7. Preserve that vendor bundle explicitly, scoped to this
    # image; resolving the rest of LMCache's dependency graph is still required.
    return text, 'nvidia-nccl-cu13==2.30.7\n'


def core_binaries():
    result = {}
    for name in EXPECTED_CORE:
        distribution = metadata.distribution(name)
        for file in distribution.files or []:
            if '.so' in Path(file).name:
                path = Path(distribution.locate_file(file))
                if path.is_file():
                    with path.open('rb') as stream:
                        result[str(path)] = hashlib.file_digest(stream, 'sha256').hexdigest()
    if not result:
        raise RuntimeError('No core runtime binaries found')
    return result


def source_hashes(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*.py'))}


def packages():
    return sorted((d.metadata['Name'],d.version) for d in metadata.distributions())


def main():
    if sys.platform!='linux' or platform.machine() not in ('aarch64','arm64'):
        raise RuntimeError('This installer is for the pinned Linux ARM64 image only')
    distribution=metadata.distribution('vllm')
    if distribution.version!='0.32.0':
        raise RuntimeError('Unexpected MyLLMBox vLLM version')
    root=Path(distribution.locate_file('vllm'))
    expected=Path('/usr/local/lib/python3.12/dist-packages/vllm')
    if root.resolve()!=expected:
        raise RuntimeError(f'Unexpected image Python layout: {root}')
    before=source_hashes(root)
    if not before:
        raise RuntimeError('Missing vLLM source')
    out=Path('/opt/n1x')
    (out/'mbx-base-packages.json').write_text(json.dumps(packages(),indent=2))
    core_before = {name: metadata.version(name) for name in EXPECTED_CORE}
    constraints, overrides = cache_constraints(
        (out/'lmcache-constraints.txt').read_text(), core_before)
    constraints_path = out/'mbx-cache-constraints.txt'
    overrides_path = out/'mbx-dependency-overrides.txt'
    constraints_path.write_text(constraints)
    overrides_path.write_text(overrides)
    binaries_before = core_binaries()
    build_source = os.environ.get('N1X_LMCACHE_FROM_SOURCE', '0')
    build_options = source_build_options(build_source)
    if build_source == '1':
        # Match v0.5.6 requirements/build.txt, with explicit tool versions.
        # Torch stays in the reviewed vendor bundle and is checked again below.
        subprocess.run(['uv','pip','install','--system','--python',sys.executable,
                        '-c',str(constraints_path),'--override',str(overrides_path)]
                       + list(SOURCE_BUILD_REQUIREMENTS),check=True)
    subprocess.run(['uv','pip','install','--system','--python',sys.executable,
                    '-c',str(constraints_path),'--override',str(overrides_path),
                    'lmcache==0.5.6','torch==2.13.0+cu130','vllm==0.32.0',
                    'flashinfer-python==0.7.0.post1'] + build_options,check=True)
    core_after = {name: metadata.version(name) for name in EXPECTED_CORE}
    binaries_after = core_binaries()
    if core_before != core_after or binaries_before != binaries_after:
        raise RuntimeError('LMCache installation replaced pinned MyLLMBox core versions or binaries')
    (out/'mbx-core-preservation.json').write_text(json.dumps(
        dict(versions=core_after, binary_sha256=binaries_after,
             metadata_exception='Pinned image Torch metadata requests NCCL 2.29.7; shipped NCCL 2.30.7 preserved by explicit override'), indent=2))
    after=source_hashes(root)
    if before!=after:
        changed=[p for p in before.keys()|after.keys() if before.get(p)!=after.get(p)]
        raise RuntimeError(f'Dependency installation replaced MBX vLLM source: {changed[:10]}')
    (out/'mbx-vllm-before-cache-patches.json').write_text(json.dumps(after,indent=2))
    (out/'mbx-installed-packages.json').write_text(json.dumps(packages(),indent=2))
    import torch
    # ABI/import check only: building does not require GPU access or model files.
    subprocess.run([sys.executable, '-c', 'import lmcache.cuda_ops'], check=True)
    nvcc = subprocess.run(['nvcc','--version'],check=True,capture_output=True,text=True).stdout
    (out/'lmcache-build.json').write_text(json.dumps(dict(
        lmcache=metadata.version('lmcache'), from_source=build_source == '1',
        python=platform.python_version(), torch=metadata.version('torch'),
        torch_cuda=torch.version.cuda, nvcc=nvcc,
        install_options=build_options,
        build_requirements=list(SOURCE_BUILD_REQUIREMENTS) if build_source == '1' else []),indent=2))
    print('LMCache installed; MBX vLLM source overlay preserved. GPU qualification is pending.')


if __name__=='__main__':
    main()
