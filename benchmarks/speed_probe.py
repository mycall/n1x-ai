"""Fixed-work speed by context depth against an already running service.

No model loading, downloads, server restarts, retries or cache flushing.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import threading
import time
import urllib.request
import uuid

try:
    from benchmarks.timing import phase_timing
    from benchmarks.speed_report import summarize, write_report
except ModuleNotFoundError:
    from timing import phase_timing
    from speed_report import summarize, write_report

PROTOCOL = 'n1x-speed-v1'
SYSTEM = 'Read the reference notes. Continue writing detailed reference notes when asked.'
INSTRUCTION = '\nContinue with a detailed technical explanation of request handling and data storage.\n'


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


class Client:
    def __init__(self, url, timeout=3600):
        self.url = url.rstrip('/')
        self.timeout = timeout

    def open(self, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data,
                                     headers={'Content-Type': 'application/json'})
        # Each concurrent stream owns its connection/opener. Ignore proxy env.
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=self.timeout)

    def get(self, path, body=None):
        with self.open(path, body) as response:
            data = response.read()
            return json.loads(data) if data.strip() else None

    def tokenize(self, text, thinking, reasoning_effort='xhigh'):
        body = dict(model='qwen/qwen38fn-best', messages=messages(text),
                    chat_template_kwargs=thinking_kwargs(thinking, reasoning_effort), add_generation_prompt=True)
        result = self.get('/tokenize', body)
        count = result.get('count')
        if type(count) is not int or count < 1:
            raise ValueError('/tokenize did not return a positive rendered token count')
        return count

    def generate(self, body):
        start = time.perf_counter()
        first = last = None
        usage, metrics, finish = None, {}, None
        packet_count = 0
        generated_chars = 0
        content, reasoning = [], []
        tool_calls = {}
        first_content = None
        done = False
        with self.open('/v1/chat/completions', body) as response:
            for raw in response:
                if not raw.startswith(b'data:'):
                    continue
                data = raw[5:].strip()
                if data == b'[DONE]':
                    done = True
                    break
                event = json.loads(data)
                usage = event.get('usage') or usage
                metrics = event.get('metrics') or metrics
                for choice in event.get('choices', []):
                    delta = choice.get('delta') or {}
                    for call in delta.get('tool_calls') or []:
                        index = call.get('index',0)
                        accumulated = tool_calls.setdefault(index,dict(id=None,type='function',function=dict(name='',arguments='')))
                        if call.get('id'):
                            accumulated['id'] = call['id']
                        function = call.get('function') or {}
                        for field in ('name','arguments'):
                            accumulated['function'][field] += function.get(field) or ''
                    text = ''.join(delta.get(k) or '' for k in ('content', 'reasoning', 'reasoning_content'))
                    if text:
                        now = time.perf_counter()
                        first = now if first is None else first
                        last = now
                        packet_count += 1
                        generated_chars += len(text)
                        if delta.get('content'):
                            content.append(delta['content'])
                            if first_content is None:
                                first_content = now
                        reasoning_text = delta.get('reasoning') or delta.get('reasoning_content')
                        if reasoning_text:
                            reasoning.append(reasoning_text)
                    finish = choice.get('finish_reason') or finish
        elapsed = time.perf_counter() - start
        timing = phase_timing(usage, metrics, elapsed, first-start if first is not None else None)
        # Keep the true client first-to-last packet interval as separate evidence;
        # the shared fallback includes the stream completion/transport tail.
        return dict(usage=usage, metrics=metrics, timing=timing, finish_reason=finish,
                    content=''.join(content), reasoning=''.join(reasoning),
                    tool_calls=[tool_calls[k] for k in sorted(tool_calls)],
                    first_content_s=first_content-start if first_content is not None else None,
                    stream_done=done, generated_packets=packet_count, generated_chars=generated_chars,
                    client_ttft_s=first-start if first is not None else None,
                    client_first_to_last_s=last-first if first is not None and last is not None else None)


def messages(text):
    return [dict(role='system', content=SYSTEM), dict(role='user', content=text)]


def thinking_kwargs(thinking, reasoning_effort='xhigh'):
    if reasoning_effort not in ('xhigh', 'medium', 'low', None):
        raise ValueError('Qwen reasoning effort must be xhigh, medium or low')
    result = {'enable_thinking': thinking}
    if thinking:
        result['reasoning_effort'] = reasoning_effort or 'xhigh'
    return result


def calibrate(client, target, thinking, stream, prefix='', tolerance=8, reasoning_effort='xhigh'):
    """Calibrate rendered tokens with the service tokenizer, never character estimates.

    Content is deterministic across profiles; stream IDs create independent histories.
    The measured extension preserves the prefix text exactly.
    """
    lead = f'\nReference stream {stream:04d}.\n'
    unit = 'The service validates input, reads indexed records, schedules work, and stores the resulting response.\n'
    size = max(256, target * 12)
    filler = (unit * (size // len(unit) + 1))[:size]
    def candidate(n):
        return prefix + lead + filler[:n] + INSTRUCTION
    base = client.tokenize(candidate(0), thinking, reasoning_effort)
    if base > target + tolerance:
        raise ValueError(f'Target {target} is below the rendered template/instruction size {base}')
    high = size
    for _ in range(4):
        if client.tokenize(candidate(high), thinking, reasoning_effort) >= target:
            break
        filler *= 2
        high = len(filler)
    else:
        raise ValueError('Could not bound rendered prompt length')
    low, best = 0, None
    while low <= high:
        middle = (low + high) // 2
        text = candidate(middle)
        count = client.tokenize(text, thinking, reasoning_effort)
        if best is None or abs(count-target) < abs(best[1]-target):
            best = text, count
        if abs(count-target) <= tolerance:
            return text, count
        if count < target:
            low = middle + 1
        else:
            high = middle - 1
    if best is not None and abs(best[1]-target) <= tolerance:
        return best
    raise ValueError(f'Cannot calibrate {target} tokens within {tolerance}')


def body(text, salt, output, thinking, reasoning_effort='xhigh'):
    return dict(model='qwen/qwen38fn-best', messages=messages(text), max_tokens=output, ignore_eos=True,
                temperature=0, seed=42, stream=True, stream_options={'include_usage': True},
                cache_salt=salt, chat_template_kwargs=thinking_kwargs(thinking, reasoning_effort))


def validate_response(result, expected_input, output, mode, tolerance):
    reasons = []
    usage = result.get('usage') or {}
    prompt = usage.get('prompt_tokens')
    cached = (usage.get('prompt_tokens_details') or {}).get('cached_tokens')
    if type(prompt) is not int or prompt != expected_input:
        reasons.append('rendered-input-mismatch')
    if usage.get('completion_tokens') != output:
        reasons.append('fixed-output-not-completed')
    if not result.get('stream_done') or result.get('finish_reason') not in ('length', 'stop') or not result.get('generated_packets'):
        reasons.append('incomplete-generation-stream')
    if type(cached) is not int or type(prompt) is not int or not 0 <= cached <= prompt:
        reasons.append('cache-coverage-unavailable')
    elif mode == 'cold' and cached != 0:
        reasons.append('cold-request-reused-cache')
    for name in ('pp_s', 'decode_s'):
        value = result.get('timing', {}).get(name)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            reasons.append('missing-' + name)
    return reasons


def plan(args):
    modes = ['incremental', 'cold'] if args.mode == 'both' else [args.mode]
    cells = []
    for mode in modes:
        for concurrency in args.concurrency:
            for depth in args.depths:
                required = depth + (args.extension_tokens if mode == 'incremental' else 0) + args.output_tokens
                status = ('not-applicable' if mode == 'cold' and depth == 0 else
                          'skipped' if required + args.tolerance*2 > args.context_limit else 'planned')
                cells.append(dict(mode=mode, concurrency=concurrency, depth=depth, status=status,
                                  measured_requests=args.repeats*concurrency if status == 'planned' else 0,
                                  prime_requests=args.repeats*concurrency if status == 'planned' and mode == 'incremental' and depth > 0 else 0,
                                  minimum_context_with_output=required))
    return dict(protocol=PROTOCOL, profile=args.profile, context_limit=args.context_limit,
                thinking=args.thinking, reasoning_effort=args.reasoning_effort if args.thinking else None,
                output_tokens=args.output_tokens, extension_tokens=args.extension_tokens,
                repeats=args.repeats, token_tolerance=args.tolerance, cells=cells,
                total_measured_requests=sum(c['measured_requests'] for c in cells),
                total_prime_requests=sum(c['prime_requests'] for c in cells),
                note='Plan only; calibration calls excluded; actual token counts, cache coverage and hardware are unmeasured.')


def run(args, client=None):
    # Exclusive directory prevents accidentally appending to/replacing first scores.
    args.out.mkdir(parents=True, exist_ok=False)
    save(args.out/'plan.json', plan(args))
    client = client or Client(args.url, args.timeout)
    modes = ['incremental', 'cold'] if args.mode == 'both' else [args.mode]
    settings = dict(protocol=PROTOCOL, profile=args.profile, depths=args.depths,
                    concurrency=args.concurrency, repeats=args.repeats, modes=modes,
                    extension_tokens=args.extension_tokens, output_tokens=args.output_tokens,
                    thinking=args.thinking, reasoning_effort=args.reasoning_effort if args.thinking else None,
                    context_limit=args.context_limit, tolerance=args.tolerance,
                    seed=42, prompt_recipe_sha256=hashlib.sha256((SYSTEM+INSTRUCTION+
                        'The service validates input, reads indexed records, schedules work, and stores the resulting response.\n').encode()).hexdigest(),
                    read_basis='added rendered tokens for incremental; full rendered prompt for cold',
                    timing_policy='direct-server-preferred; PP fallback e2e-minus-decode',
                    repeat_order='forward grid on even repeats, reverse on odd repeats',
                    fixed_output=True, correctness_claim=False)
    metadata = dict(started_utc=datetime.now(timezone.utc).isoformat(), run_id=uuid.uuid4().hex,
                    settings=settings, status='running', source_hashes={
                        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                        for name in ('speed_probe.py', 'speed_report.py', 'timing.py')})
    settings['generator_sha256'] = metadata['source_hashes']['speed_probe.py']
    if args.host_record:
        metadata['host'] = json.loads(args.host_record.read_text(encoding='utf-8-sig'))
    save(args.out/'run.json', metadata)
    rows = []
    log_lock = threading.Lock()
    def record(row):
        with log_lock:
            rows.append(row)
            with (args.out/'requests.jsonl').open('a', encoding='utf-8') as file:
                file.write(json.dumps(row, allow_nan=False)+'\n')
    try:
        client.get('/health')
        metadata['models'] = client.get('/v1/models')
        save(args.out/'run.json', metadata)
        grid = [(m, c, d) for m in modes for c in args.concurrency for d in args.depths]
        for repeat in range(args.repeats):
            for mode, concurrency, depth in grid if repeat % 2 == 0 else reversed(grid):
                cell = dict(mode=mode, concurrency=concurrency, depth=depth, repeat=repeat)
                if mode == 'cold' and depth == 0:
                    record(dict(**cell, status='not-applicable', reason='cold prompt cannot have zero rendered tokens'))
                    continue
                required = depth + (args.extension_tokens if mode == 'incremental' else 0) + args.output_tokens
                if required + args.tolerance*2 > args.context_limit:
                    record(dict(**cell, status='skipped', reason='context-limit-reserves-output'))
                    continue
                prepared = []
                for stream in range(concurrency):
                    salt = f'{metadata["run_id"]}-{mode}-{concurrency}-{depth}-{repeat}-{stream}'
                    prefix, history = ('', 0)
                    if mode == 'incremental' and depth > 0:
                        prefix, history = calibrate(client, depth, args.thinking, stream, tolerance=args.tolerance,
                                                    reasoning_effort=args.reasoning_effort)
                    target = history + args.extension_tokens if mode == 'incremental' else depth
                    text, actual = calibrate(client, target, args.thinking, stream, prefix, args.tolerance,
                                             reasoning_effort=args.reasoning_effort)
                    if actual + args.output_tokens > args.context_limit:
                        raise ValueError('Actual rendered input leaves insufficient room for output')
                    prepared.append(dict(stream=stream, prefix=prefix, text=text, salt=salt,
                                         history_tokens=history, input_tokens=actual))
                # Independent streams are primed concurrently; all primes complete
                # before the measured wave. Prime answers are never scored as speed.
                def prime(p):
                    if not p['history_tokens']:
                        return
                    request = body(p['prefix'], p['salt'], 1, args.thinking, args.reasoning_effort)
                    try:
                        result = client.generate(request)
                    except Exception as error:
                        record(dict(**cell, stream=p['stream'], phase='prime', status='failed',
                                    error=str(error), request=request))
                        raise
                    errors = validate_response(result, p['history_tokens'], 1, 'prime', args.tolerance)
                    # One generated token has no decode interval; it is a prime only.
                    errors = [e for e in errors if e not in ('missing-decode_s', 'missing-pp_s')]
                    record(dict(**cell, stream=p['stream'], phase='prime', status='invalid' if errors else 'ok',
                                errors=errors, request=request, **result))
                    if errors:
                        raise ValueError('Prefix prime failed: ' + ', '.join(errors))
                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    list(pool.map(prime, prepared))
                    def measure(p):
                        request = body(p['text'], p['salt'], args.output_tokens, args.thinking, args.reasoning_effort)
                        started = time.time()
                        try:
                            result = client.generate(request)
                            errors = validate_response(result, p['input_tokens'], args.output_tokens, mode, args.tolerance)
                            row = dict(**cell, stream=p['stream'], phase='measured', started_unix_s=started,
                                status='invalid' if errors else 'ok', errors=errors,
                                history_tokens=p['history_tokens'], expected_input_tokens=p['input_tokens'],
                                read_tokens=p['input_tokens']-p['history_tokens'],
                                prompt_sha256=hashlib.sha256(p['text'].encode()).hexdigest(), request=request, **result)
                        except Exception as error:
                            row = dict(**cell, stream=p['stream'], phase='measured', status='failed',
                                        error=str(error), request=request, started_unix_s=started)
                        # Persist in completion order. A slow/blocked earlier
                        # stream must not hide a later completed first attempt.
                        record(row)
                    list(pool.map(measure, prepared))
                print(f'{mode} C{concurrency} depth={depth} repeat={repeat+1}/{args.repeats}', flush=True)
        metadata['status'] = 'completed' if all(r['status'] in ('ok', 'not-applicable') for r in rows) else 'incomplete'
    except BaseException as error:
        metadata.update(status='interrupted' if isinstance(error, KeyboardInterrupt) else 'failed', error=str(error))
        raise
    finally:
        metadata['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save(args.out/'run.json', metadata)
        summary = summarize(metadata, rows)
        save(args.out/'summary.json', summary)
        write_report([summary], args.out/'comparison.md', args.out/'comparison.json')
    if metadata['status'] != 'completed':
        raise RuntimeError('Speed matrix incomplete; first attempts and missing coverage retained')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--host-record', type=Path)
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--depths', type=int, nargs='+', default=[0, 4096, 16384, 32768, 65536, 131072])
    parser.add_argument('--concurrency', type=int, nargs='+', default=[1])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--extension-tokens', type=int, default=2048)
    parser.add_argument('--output-tokens', type=int, default=256)
    parser.add_argument('--context-limit', type=int, required=True)
    parser.add_argument('--mode', choices=['incremental', 'cold', 'both'], default='incremental')
    parser.add_argument('--thinking', action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--reasoning-effort', choices=['xhigh', 'medium', 'low'],
                        help='Default xhigh when thinking is on; omitted when thinking is off')
    parser.add_argument('--timeout', type=float, default=3600)
    parser.add_argument('--tolerance', type=int, default=8)
    parser.add_argument('--plan-only', action='store_true', help='Write the grid without contacting any service')
    args = parser.parse_args()
    if not args.thinking and args.reasoning_effort is not None:
        parser.error('--reasoning-effort requires thinking enabled')
    if args.thinking and args.reasoning_effort is None:
        args.reasoning_effort = 'xhigh'
    if (any(d < 0 for d in args.depths) or any(c < 1 or c > 16 for c in args.concurrency)
            or args.repeats < 1 or args.extension_tokens < 128 or args.output_tokens < 2
            or args.context_limit < 128 or not 0 <= args.tolerance <= 32 or args.timeout <= 0
            or len(set(args.depths)) != len(args.depths) or len(set(args.concurrency)) != len(args.concurrency)):
        parser.error('Invalid/duplicate depths or concurrency, repeats, token budgets, tolerance or timeout')
    if args.plan_only:
        args.out.mkdir(parents=True, exist_ok=False)
        save(args.out/'plan.json', plan(args))
        print(args.out/'plan.json')
    else:
        run(args)


if __name__ == '__main__':
    main()
