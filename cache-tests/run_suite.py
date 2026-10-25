"""One-container, standard-library client and service supervisor.

Keep model loads outside measured requests. Each cache group runs cold, GPU-warm,
then GPU-reset/external-restore. A separate no-connector phase is the baseline.
"""
import argparse
import base64
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import threading
import urllib.request
import uuid

# Apply before launching either service, including runs from older base images.
os.environ.update(LMCACHE_TRACK_USAGE='false', DO_NOT_TRACK='1',
                  VLLM_NO_USAGE_STATS='1', HF_HUB_DISABLE_TELEMETRY='1')

HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
BASE = 'http://127.0.0.1:8000'
MAX_CONTEXT = 262144
LONGBENCH_MAX_NEW_TOKENS = 1024

def request(path, body=None, base=BASE, timeout=3600):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data,
                                 headers={'Content-Type': 'application/json'})
    with HTTP.open(req, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw) if raw else None

def text_get(path, base=BASE):
    with HTTP.open(base + path, timeout=15) as response:
        return response.read().decode()

def metric_values(text):
    result = {}
    for line in text.splitlines():
        if line.startswith('#'):
            continue
        match = re.match(r'([\w:]+)(?:\{.*\})?\s+([-+\d.eE]+)$', line)
        if match:
            key, value = match.groups()
            result[key] = result.get(key, 0) + float(value)
    return result

def timestamp():
    return datetime.now(timezone.utc).isoformat()

def read_host_status(path):
    """Read one monitor snapshot despite a brief VIRTIOFS replacement gap."""
    for attempt in range(10):
        try:
            with path.open(encoding='utf-8-sig') as stream:
                modified = os.fstat(stream.fileno()).st_mtime
                state = json.load(stream)
            if time.time() - modified > 90:
                raise RuntimeError('Windows memory monitor missing or stale')
            return state
        except FileNotFoundError:
            if attempt == 9:
                raise RuntimeError('Windows memory monitor missing or stale') from None
            time.sleep(0.2)

def normalize_code_answer(text):
    """Allow a surrounding Markdown code fence, but no extra answer text."""
    text = text.strip()
    if text.startswith('```') and text.endswith('```') and len(text) >= 6:
        text = text[3:-3].strip()
    return text.rstrip('.')

class Suite:
    def __init__(self, args):
        self.args = args
        self.out = Path(args.output)
        self.out.mkdir(parents=True, exist_ok=True)
        self.children = []
        self.phase = 'preflight'
        self.run_id = args.run_id
        self.records = []
        self.journal = self.out / 'requests.jsonl'
        self.monitor_stop = threading.Event()
        self.monitor_error = None
        self.journal_lock = threading.Lock()
        if self.journal.exists():
            self.records = [json.loads(line) for line in self.journal.read_text().splitlines() if line]

    def save(self, name, value):
        path = self.out / name
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
        os.replace(temporary, path)

    def guard(self):
        if self.monitor_error:
            raise RuntimeError(self.monitor_error)
        path = self.out / 'host-status.json'
        state = read_host_status(path)
        if state['availableGiB'] < 4:
            raise RuntimeError(f"Windows headroom below 4 GiB: {state['availableGiB']:.2f}")
        if state['powerLineStatus'] != 'Online' and not getattr(self, 'allow_battery', False):
            raise RuntimeError('External power disconnected; stopping before the next request')
        if (self.out / 'STOP').exists():
            raise RuntimeError('Stop requested by host monitor/operator')
        return state

    def monitor(self):
        failures = 0
        while not self.monitor_stop.wait(5):
            try:
                self.guard()
                failures = 0
            except Exception as error:
                failures += 1
                if failures >= 3:
                    self.monitor_error = str(error)
                    self.save('memory-power-abort.json', {'timestamp': timestamp(), 'error': str(error)})
                    for process, _ in reversed(list(self.children)):
                        self.stop(process)
                    return

    def start(self, name, argv):
        self.guard()
        log = (self.out / f'{name}.log').open('a', buffering=1)
        process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        self.children.append((process, log))
        self.save(f'{name}-command.json', argv)
        return process

    def stop(self, process):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=45)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=15)

    def wait_ready(self, process, base, path, seconds=3600):
        deadline = time.monotonic() + seconds
        last_notice = 0
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f'Service exited with code {process.returncode}; inspect logs')
            self.guard()
            try:
                text_get(path, base)
                return
            except Exception:
                pass
            if time.monotonic() - last_notice > 30:
                print(f'{timestamp()} waiting for {base}{path}', flush=True)
                last_notice = time.monotonic()
            time.sleep(5)
        raise TimeoutError(f'{base} readiness timeout')

    def metrics(self, label):
        raw = text_get('/metrics')
        (self.out / f'{label}-vllm.txt').write_text(raw)
        result = metric_values(raw)
        if self.phase == 'lmcache':
            raw = text_get('/metrics', 'http://127.0.0.1:8080')
            (self.out / f'{label}-lmcache.txt').write_text(raw)
            result.update(metric_values(raw))
        return result

    def tokenize(self, messages):
        return request('/tokenize', {'model': 'qwen', 'messages': messages,
                       'add_generation_prompt': True,
                       'chat_template_kwargs': {'enable_thinking': False}})['count']

    def reset(self):
        # Reset GPU prefix state only. External-cache state must survive.
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            self.guard()
            result = request('/reset_prefix_cache?reset_external=false', {})
            if result.get('success') is True:
                return
            time.sleep(1)
        raise RuntimeError('GPU prefix reset remained busy for 120 seconds')

    def chat(self, case_id, condition, messages, salt, expected=None, score_answer=None):
        before_host = self.guard()
        label = f'{self.phase}-{case_id}-{condition}'
        before = self.metrics(label + '-before')
        body = {'model': 'qwen', 'messages': messages, 'temperature': 0,
                'max_tokens': LONGBENCH_MAX_NEW_TOKENS if score_answer else 128,
                'stream': True, 'stream_options': {'include_usage': True},
                'cache_salt': salt, 'chat_template_kwargs': {'enable_thinking': False}}
        if getattr(self, 'request_seed', None) is not None:
            body['seed'] = self.request_seed
        started = time.perf_counter()
        content, reasoning, usage, finish, first = '', '', {}, None, None
        req = urllib.request.Request(BASE + '/v1/chat/completions',
                                     data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
        with HTTP.open(req, timeout=3600) as response:
            for line in response:
                if not line.startswith(b'data: '):
                    continue
                payload = line[6:].strip()
                if payload == b'[DONE]':
                    break
                event = json.loads(payload)
                if event.get('usage'):
                    usage = event['usage']
                for choice in event.get('choices', []):
                    delta = choice.get('delta', {})
                    token_text = delta.get('content') or ''
                    token_reason = delta.get('reasoning') or delta.get('reasoning_content') or ''
                    if first is None and (token_text or token_reason):
                        first = time.perf_counter() - started
                    content += token_text
                    reasoning += token_reason
                    finish = choice.get('finish_reason') or finish
        elapsed = time.perf_counter() - started
        # Scrape repeatedly only for publication lag, not for more inference.
        time.sleep(1)
        after = self.metrics(label + '-after')
        delta = {key: value - before.get(key, 0) for key, value in after.items()}
        matched = re.search(r'The correct answer is\s*\(?([A-D])\)?', content.replace('*', ''))
        row = {'id': label, 'phase': self.phase, 'case': case_id, 'condition': condition,
               'timestamp': timestamp(), 'ttftSeconds': first, 'totalSeconds': elapsed,
               'usage': usage, 'finishReason': finish, 'content': content, 'reasoning': reasoning,
               'expected': expected, 'correct': all(code in content for code in expected) if expected else None,
               'answer': matched.group(1) if matched else None, 'expectedAnswer': score_answer,
               'scoreCorrect': bool(matched and matched.group(1) == score_answer) if score_answer else None,
               'metricsDelta': delta, 'windowsBefore': before_host,
               'promptSha256': hashlib.sha256(json.dumps(messages).encode()).hexdigest()}
        if first is not None and usage.get('completion_tokens', 0) > 1 and elapsed > first:
            row['approxDecodeTokensPerSecond'] = (usage['completion_tokens'] - 1) / (elapsed - first)
        with self.journal_lock:
            with self.journal.open('a', encoding='utf-8') as f:
                f.write(json.dumps(row) + '\n')
                f.flush()
                os.fsync(f.fileno())
            self.records.append(row)
        print(f"{label}: TTFT={first}, total={elapsed:.2f}, correct={row['correct']}, score={row['scoreCorrect']}", flush=True)
        if not usage or finish != 'stop' or (expected and not row['correct']):
            raise RuntimeError(f'Correctness/protocol gate failed: {label}; finish_reason={finish}')
        return row

    def synthetic(self, target, identity='A'):
        codes = [f'{identity}-RIVER-729', f'{identity}-MAPLE-418', f'{identity}-COMET-653']
        unit = 'Background note: the maintenance team reviewed routine schedules and filed its report.\n'
        def messages(n):
            parts = [f'Archive {identity}. Record the three secret codes.\n']
            for code in codes:
                parts += [unit * n, f'Important secret code: {code}.\n']
            parts += ['Return all three secret codes in order, separated by spaces, and nothing else.']
            return [{'role': 'user', 'content': ''.join(parts)}]
        # Estimate repeat count from a short tokenization, avoiding huge
        # multi-million-token probes when preparing the 262K case.
        base_count = self.tokenize(messages(0))
        step = max(1, self.tokenize(messages(10)) - base_count)
        low, high = 0, max(2, int((target - base_count) * 10 / step) + 20)
        while low + 1 < high:
            middle = (low + high) // 2
            if self.tokenize(messages(middle)) <= target:
                low = middle
            else:
                high = middle
        result = messages(low)
        count = self.tokenize(result)
        assert target - 100 <= count <= target and count + 128 < MAX_CONTEXT
        return result, codes, count

    def group(self, case_id, messages, expected=None, score_answer=None):
        group_before = self.metrics(f'{self.phase}-{case_id}-group-before')
        salt = f'{self.run_id}:{self.phase}:{case_id}:{uuid.uuid4().hex}'
        self.reset()
        cold = self.chat(case_id, 'cold', messages, salt, expected, score_answer)
        warm = self.chat(case_id, 'gpu-warm', messages, salt, expected, score_answer)
        self.reset()
        restored = self.chat(case_id, 'gpu-reset', messages, salt, expected, score_answer)
        if cold['scoreCorrect'] and not restored['scoreCorrect']:
            raise RuntimeError(f'Correct answer became incorrect after restore: {case_id}')
        if self.phase == 'lmcache':
            hits = sum(value for key, value in restored['metricsDelta'].items()
                       if 'num_chunks_loaded' in key and key.endswith('_total'))
            if hits <= 0:
                raise RuntimeError(f'No measured LMCache loads for {case_id}; inspect raw metrics')
        follow = messages + [{'role': 'assistant', 'content': warm['content']},
                             {'role': 'user', 'content': 'Repeat your previous final answer exactly.'}]
        self.chat(case_id, 'follow-up', follow, salt, expected, score_answer)
        if case_id.startswith('retrieval-') or case_id == 'cache-gate':
            time.sleep(12)  # vLLM speculative counters are periodically published.
            group_after = self.metrics(f'{self.phase}-{case_id}-group-after')
            draft_key = 'vllm:spec_decode_num_draft_tokens_total'
            accept_key = 'vllm:spec_decode_num_accepted_tokens_total'
            mtp = {'drafted': group_after.get(draft_key, 0) - group_before.get(draft_key, 0),
                   'accepted': group_after.get(accept_key, 0) - group_before.get(accept_key, 0)}
            self.save(f'{self.phase}-{case_id}-mtp.json', mtp)
            if mtp['drafted'] <= 0 and not getattr(self, 'disable_mtp', False):
                raise RuntimeError(f'No measured MTP drafts for {case_id}')
        return messages, expected, salt

    def features(self):
        evidence = []
        def chat(messages, **kwargs):
            self.guard()
            body = {'model': 'qwen', 'messages': messages, 'max_tokens': 256,
                    'temperature': 0, 'chat_template_kwargs': {'enable_thinking': False}}
            body.update(kwargs)
            if self.request_seed is not None:
                body['seed'] = self.request_seed
            return request('/v1/chat/completions', body)
        def check(name, response, passed):
            evidence.append({'test': name, 'passed': bool(passed), 'response': response})
            self.save(self.phase + '-features.json', evidence)
            if not passed:
                raise RuntimeError('Feature check failed: ' + name)
        result = chat([{'role': 'user', 'content': 'Return a JSON object: color is green and count is 7.'}],
                      response_format={'type': 'json_object'})
        check('json', result, json.loads(result['choices'][0]['message']['content']) == {'color': 'green', 'count': 7})
        tools = [{'type': 'function', 'function': {'name': 'get_inventory', 'description': 'Look up inventory for a SKU',
                  'parameters': {'type': 'object', 'properties': {'sku': {'type': 'string'}}, 'required': ['sku']}}}]
        messages = [{'role': 'user', 'content': 'Look up inventory for AX-42 using the tool. Then reply with only the count.'}]
        result = chat(messages, tools=tools, tool_choice='required')
        assistant = result['choices'][0]['message']
        call = assistant['tool_calls'][0]
        check('tool_call', result, call['function']['name'] == 'get_inventory' and
              json.loads(call['function']['arguments']) == {'sku': 'AX-42'})
        messages += [assistant, {'role': 'tool', 'tool_call_id': call['id'], 'content': '{"sku":"AX-42","count":23}'}]
        result = chat(messages, tools=tools, tool_choice='none')
        check('tool_result', result, result['choices'][0]['message']['content'].strip().rstrip('.') == '23')
        result = chat([{'role': 'user', 'content': 'A box has 9 rows of 7 marbles. Think through it, then give the total.'}],
                      max_tokens=512, chat_template_kwargs={'enable_thinking': True})
        message = result['choices'][0]['message']
        check('reasoning', result, (message.get('reasoning') or message.get('reasoning_content')) and
              re.search(r'\b63\b', message.get('content', '')))
        image = 'data:image/png;base64,' + base64.b64encode(Path('/data/vision-fixture.png').read_bytes()).decode()
        messages = [{'role': 'user', 'content': [
            {'type': 'text', 'text': 'Read the printed code at the bottom. Reply with only the code.'},
            {'type': 'image_url', 'image_url': {'url': image}}]}]
        result = chat(messages)
        check('vision_ocr', result, normalize_code_answer(result['choices'][0]['message']['content']) == 'N1X-742')
        messages[0]['content'][0]['text'] = 'Describe the shape and color on the left, then the right. Be brief.'
        result = chat(messages)
        answer = result['choices'][0]['message']['content'].lower()
        check('vision_shapes', result, all(word in answer for word in ('red', 'circle', 'blue', 'square')))
        # A text prefix long enough to offload, followed by the same image.
        # This tests multimodal restore correctness, not encoder-cache support.
        messages[0]['content'][0]['text'] = ('Ordinary archive entry with no special instruction.\n' * 600
                                             + 'Read the printed code at the bottom. Reply with only the code.')
        self.group('vision-restore', messages, ['N1X-742'])

    def workload(self):
        persisted = None
        for length in self.args.lengths:
            messages, codes, count = self.synthetic(length)
            persisted = self.group(f'retrieval-{count}', messages, codes)
        data = json.loads(Path(self.args.dataset).read_text(encoding='utf-8'))
        self.save('dataset-manifest.json', {k: v for k, v in data.items() if k != 'samples'})
        for item in ([] if getattr(self, 'capacity_check', False) else data['samples']):
            messages = [{'role': 'user', 'content': item['prompt']}]
            count = self.tokenize(messages)
            if count + LONGBENCH_MAX_NEW_TOKENS >= MAX_CONTEXT:
                self.save(f"{self.phase}-longbench-{item['id']}-skipped.json",
                          {'id': item['id'], 'tokens': count, 'reason': 'Beyond native context; no truncation'})
                continue
            self.group('longbench-' + item['id'], messages, score_answer=item['answer'])
        if self.args.concurrency:
            self.reset()
            prompts = [self.synthetic(self.parallel_context_tokens, chr(ord('B') + index))
                       for index in range(self.parallel_sessions)]
            self.save(f'{self.phase}-parallel-config.json', {
                'promptTokens': [count for _, _, count in prompts],
                'concurrency': self.parallel_sessions, 'restoreChecks': self.parallel_restore,
                'note': 'Global external hits measured per stage; per-request intervals overlap. Misses may recompute within the fixed L1 cap.'})
            conditions = ('cold', 'gpu-warm', 'gpu-reset') if self.parallel_restore else ('cold',)
            for condition in conditions:
                if condition == 'gpu-reset':
                    self.reset()
                before = self.metrics(f'{self.phase}-parallel-{condition}-group-before')
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.parallel_sessions) as executor:
                    futures = [executor.submit(self.chat, f'parallel-{index}', condition, messages,
                               f'{self.run_id}:{self.phase}:parallel:{index}', codes)
                               for index, (messages, codes, _) in enumerate(prompts)]
                    rows = [future.result() for future in futures]
                after = self.metrics(f'{self.phase}-parallel-{condition}-group-after')
                self.save(f'{self.phase}-parallel-{condition}.json', {
                    'requests': [row['id'] for row in rows],
                    'allCorrect': all(row['correct'] for row in rows),
                    'metricsDelta': {key: value-before.get(key, 0) for key, value in after.items()},
                    'note': 'Global counters overlap per-request intervals; use this group delta once.'})
        if getattr(self, 'optimization_config', None):
            from optimization_workloads import run_experiments
            run_experiments(self, self.optimization_config)
        return persisted

    def run(self):
        started = time.monotonic()
        config = json.loads(Path(self.args.config).read_text())
        self.disable_mtp = config.get('disableMtp', False)
        self.request_seed = config.get('requestSeed')
        self.optimization_config = config if config.get('optimizations') else None
        os.environ['N1X_RESTORE_WAIT_MS'] = str(config.get('restoreWaitMs', 0))
        self.allow_battery = config.get('allowBattery', False)
        self.parallel_context_tokens = config.get('parallelContextTokens', 129000)
        self.parallel_sessions = config.get('parallelSessions', 2)
        self.parallel_restore = config.get('parallelRestore', False)
        chunk_size = str(config.get('lmcacheChunkSize', 1616 if config.get('kvCacheDtype') == 'fp8_e4m3' else 816))
        self.save('run-manifest.json', {'runId': self.run_id, 'started': timestamp(), 'config': config,
                  'lengths': self.args.lengths, 'client': 'Python standard library; no torch import',
                  'note': 'Bounded cache correctness/latency canary, not a full LongBench score. PLE file cache is not flushed.'})
        lm_server = None
        monitor = threading.Thread(target=self.monitor, daemon=True)
        monitor.start()
        try:
            with (self.out / 'cuda-ipc-preflight.log').open('w') as log:
                probe_script = '/suite/test_vmm_wrapper.py' if config.get('useVmm') else '/suite/probe_ipc_roundtrip.py'
                probe = subprocess.run([sys.executable, probe_script],
                                       stdout=log, stderr=subprocess.STDOUT, timeout=120)
            if probe.returncode:
                raise RuntimeError('CUDA IPC roundtrip failed before model loading; see cuda-ipc-preflight.log')
            self.capacity_check = config.get('capacityCheck', False)
            for phase in (('lmcache',) if self.capacity_check else ('lmcache', 'baseline')):
                self.phase = phase
                if phase == 'baseline' and lm_server is not None:
                    self.stop(lm_server)
                    lm_server = None
                argv = [sys.executable, '-m', 'vllm.entrypoints.openai.api_server'] + config['modelArgs']
                if phase == 'lmcache':
                    lm_server = self.start('lmcache-server', [sys.executable, '-m',
                        'lmcache.v1.multiprocess.http_server', '--host', '127.0.0.1', '--port', '5555',
                        '--http-host', '127.0.0.1', '--http-port', '8080', '--l1-size-gb', str(config.get('lmcacheL1GiB', 0.5)),
                        '--eviction-policy', 'LRU', '--chunk-size', chunk_size, '--separate-object-groups',
                        '--l2-prefetch-max-in-flight', '1', '--l2-adapter',
                        json.dumps({'type': 'fs', 'base_path': '/lmcache/' + self.run_id, 'use_odirect': True})])
                    self.wait_ready(lm_server, 'http://127.0.0.1:8080', '/metrics', 180)
                    connector = {'kv_connector': 'LMCacheMPConnector', 'kv_role': 'kv_both',
                                 'kv_connector_module_path': 'lmcache.integration.vllm.lmcache_mp_connector',
                                 'kv_connector_extra_config': {'lmcache.mp.host': '127.0.0.1', 'lmcache.mp.port': 5555}}
                    if config.get('useVmm'):
                        connector['kv_connector_extra_config']['lmcache.mp.use_vmm_api'] = True
                    if config.get('eagerPrefetch'):
                        connector['kv_connector_extra_config']['lmcache.mp.eager_prefetch'] = True
                    argv += ['--mamba-cache-mode', 'align', '--kv-transfer-config', json.dumps(connector)]
                model = self.start(phase + '-model', argv)
                self.wait_ready(model, BASE, '/health')
                # Fail fast on restore integration before long workloads.
                # MTP can back off one recurrent checkpoint block. A sub-4K
                # prompt with 2K blocks can store attention without any reusable
                # recurrent state; exercise multiple prefill chunks instead.
                short, codes, _ = self.synthetic(16384, 'GATE')
                self.group('cache-gate', short, codes)
                self.features()
                self.workload()
                if phase == 'lmcache' and not self.capacity_check:
                    # One engine restart, rather than one restart per context.
                    persisted = self.group('restart-canary', short, codes)
                    self.stop(model)
                    model = self.start('lmcache-restarted-model', argv)
                    self.wait_ready(model, BASE, '/health')
                    row = self.chat('restart-canary', 'engine-restarted', persisted[0], persisted[2], persisted[1])
                    if not any(v > 0 and 'num_chunks_loaded' in k and k.endswith('_total')
                               for k, v in row['metricsDelta'].items()):
                        raise RuntimeError('No LMCache hit after engine restart')
                self.stop(model)
            self.save('summary.json', {'status': 'complete', 'scope': 'capacity-check' if self.capacity_check else 'full-suite', 'wallSeconds': time.monotonic() - started,
                      'requests': len(self.records), 'records': self.records})
        except Exception as error:
            self.save('summary.json', {'status': 'failed', 'phase': self.phase, 'error': repr(error),
                      'wallSeconds': time.monotonic() - started, 'requests': len(self.records)})
            raise
        finally:
            self.monitor_stop.set()
            monitor.join(timeout=60)
            for process, log in reversed(self.children):
                self.stop(process)
                log.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='/results')
    parser.add_argument('--config', default='/suite/run-config.json')
    parser.add_argument('--dataset', default='/data/longbench-canary.json')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--lengths', type=int, nargs='+', default=[32000, 128000, 261000])
    parser.add_argument('--concurrency', action='store_true')
    Suite(parser.parse_args()).run()
