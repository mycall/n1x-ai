"""Copy the pinned PLE table to a Linux volume, verifying destination hashes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import time


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


source = Path('/source-table')
target = Path('/native-table')
manifest_path = target / 'n1x-copy-manifest.json'
files = sorted(p for p in source.iterdir() if p.is_file())
if not files or not any(p.suffix == '.safetensors' for p in files):
    raise RuntimeError('Missing source table')
if shutil.disk_usage(target).free < sum(p.stat().st_size for p in files if not (target/p.name).exists()) + 1024**3:
    raise RuntimeError('Insufficient Linux-volume space')
records = []
started = time.monotonic()
for original in files:
    destination = target / original.name
    before = original.stat()
    if destination.exists():
        source_hash = digest(original)
        if destination.stat().st_size != before.st_size or digest(destination) != source_hash:
            raise RuntimeError(f'Existing destination differs: {destination}; inspect before replacing')
        status = 'verified existing'
    else:
        # A failed/interrupted copy leaves only an explicitly named partial file.
        partial = destination.with_name(destination.name + '.n1x-partial')
        hasher = hashlib.sha256()
        with original.open('rb') as reader, partial.open('wb') as writer:
            while chunk := reader.read(4*1024*1024):
                hasher.update(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        source_hash = hasher.hexdigest()
        if digest(partial) != source_hash:
            raise RuntimeError(f'Copy checksum mismatch: {partial}')
        partial.replace(destination)
        status = 'copied and verified'
    after = original.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError(f'Source changed during copy: {original}')
    records.append(dict(name=original.name, bytes=before.st_size, sha256=source_hash))
    print(f'{original.name}: {status}', flush=True)
manifest = dict(sourceRevision='50511b0a41aa1d34b8beb7e5d4bb06a0b650dc14',
                verification='Source and destination SHA256 compared; original Windows files retained.',
                seconds=time.monotonic()-started, files=records)
temporary = manifest_path.with_suffix('.partial')
temporary.write_text(json.dumps(manifest, indent=2))
temporary.replace(manifest_path)
print(f'Completed {len(records)} files in {manifest["seconds"]:.1f}s', flush=True)
