"""Request phase rates; never attribute shared counters to concurrent requests."""
import math


def phase_timing(usage, metrics, e2e_s, first_token_s=None):
    """first_token_s is client seconds from send to first reasoning/content token.

    The pinned vLLM 0.32 per-request time_to_first_token_ms measures scheduled
    to first token (excludes queue); generation_time_ms measures first to last.
    Server metrics must belong to this response, never a Prometheus batch delta.
    """
    usage, metrics = usage or {}, metrics or {}

    def positive(value):
        return isinstance(value, (int, float)) and math.isfinite(value) and value > 0

    pp = metrics.get('time_to_first_token_ms')
    decode = metrics.get('generation_time_ms')
    pp = pp / 1000 if positive(pp) else None
    decode = decode / 1000 if positive(decode) else None
    decode_source = 'server-first-to-last-token' if decode is not None else None
    if decode is None and positive(first_token_s) and positive(e2e_s) and first_token_s < e2e_s:
        decode = e2e_s - first_token_s
        decode_source = 'client-first-token-to-completion'
    pp_source = 'server-scheduled-to-first-token' if pp is not None else None
    if pp is None and decode is not None and positive(e2e_s) and e2e_s > decode:
        pp = e2e_s - decode
        pp_source = 'derived-e2e-minus-decode-includes-overhead'
    prompt = usage.get('prompt_tokens')
    completion = usage.get('completion_tokens')
    cached = (usage.get('prompt_tokens_details') or {}).get('cached_tokens')
    read = prompt / pp if pp and isinstance(prompt, int) and prompt >= 0 else None
    write = (completion - 1) / decode if decode and isinstance(completion, int) and completion > 1 else None
    return dict(e2e_s=e2e_s, pp_s=pp, decode_s=decode, pp_source=pp_source,
                decode_source=decode_source, prompt_tokens=prompt, completion_tokens=completion,
                cached_tokens=cached, read_tks=read, write_tks=write,
                read_write_tks=[read, write], aggregation='per-request phase rates',
                read_basis='full prompt including cached tokens', decode_token_offset=1)
