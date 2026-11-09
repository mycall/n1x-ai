"""Conservative SSD working-set envelope for the external restore workload."""
import math


def restore_storage_envelope(group_object_bytes, *, seed_tokens, pressure_tokens,
                             seed_count=2, pressure_count=3, chunk_tokens=4096,
                             reserve_bytes=4 * 2**30):
    values = [*group_object_bytes, seed_tokens, pressure_tokens, seed_count,
              pressure_count, chunk_tokens]
    if not group_object_bytes or any(type(value) is not int or value <= 0 for value in values):
        raise ValueError('Restore layout sizes and workload counts must be positive integers')
    if type(reserve_bytes) is not int or reserve_bytes < 0:
        raise ValueError('Restore storage reserve must be nonnegative')
    # The bounded adapter reserves filesystem-aligned bytes. Count every object
    # group at every chunk, including partial end chunks; do not assume that
    # transient L1 residency or sparse checkpoints will reduce SSD demand.
    per_chunk = sum(math.ceil(size / 4096) * 4096 for size in group_object_bytes)
    chunks = seed_count * math.ceil(seed_tokens / chunk_tokens)
    chunks += pressure_count * math.ceil(pressure_tokens / chunk_tokens)
    working = chunks * per_chunk
    return dict(bytes_per_chunk=per_chunk, chunks=chunks,
                working_set_bytes=working, reserve_bytes=reserve_bytes,
                required_bytes=working + reserve_bytes,
                scope='Upper envelope; assumes all groups stored at every chunk')


def require_restore_capacity(capacity_bytes, envelope):
    if type(capacity_bytes) is not int or capacity_bytes <= 0:
        raise ValueError('SSD capacity must be a positive integer')
    if capacity_bytes < envelope['required_bytes']:
        raise ValueError('SSD budget cannot retain the restore workload and its reserve')
