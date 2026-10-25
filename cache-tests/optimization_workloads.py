"""Agent turns and controlled prefix experiments; all metrics remain local."""
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import time

from run_suite import request, timestamp

TOOLS = [{'type': 'function', 'function': {
    'name': 'get_inventory', 'description': 'Read current inventory for a SKU.',
    'parameters': {'type': 'object', 'properties': {'sku': {'type': 'string'}},
                   'required': ['sku'], 'additionalProperties': False}}}]


def delta(before, after):
    return {key: value - before.get(key, 0) for key, value in after.items()}


def assistant_message(message):
    # Preserve actual assistant/tool history, excluding response-only null fields.
    return {key: message[key] for key in ('role', 'content', 'tool_calls')
            if message.get(key) is not None}


def append_tool_result(messages, assistant, sku, count):
    calls = assistant.get('tool_calls', [])
    if len(calls) != 1:
        raise RuntimeError(f'Expected one tool call, got {len(calls)}')
    call = calls[0]
    if (call['function']['name'] != 'get_inventory'
            or json.loads(call['function']['arguments']) != {'sku': sku}):
        raise RuntimeError('Incorrect inventory tool call')
    return messages + [assistant_message(assistant), {
        'role': 'tool', 'tool_call_id': call['id'],
        'content': json.dumps({'sku': sku, 'count': count}, separators=(',', ':'))}]


def timed_request(suite, label, messages, salt, **kwargs):
    host = suite.guard()
    body = {'model': 'qwen', 'messages': messages, 'temperature': 0,
            'max_tokens': 512, 'cache_salt': salt,
            'chat_template_kwargs': {'enable_thinking': False}}
    body.update(kwargs)
    if getattr(suite, 'request_seed', None) is not None:
        body['seed'] = suite.request_seed
    started = time.perf_counter()
    response = request('/v1/chat/completions', body)
    elapsed = time.perf_counter() - started
    choice = response['choices'][0]
    row = {'id': label, 'timestamp': timestamp(), 'totalSeconds': elapsed,
           'phase': suite.phase, 'case': label, 'condition': 'optimization',
           'finishReason': choice['finish_reason'], 'usage': response.get('usage'),
           'message': choice['message'], 'windowsBefore': host,
           'promptSha256': hashlib.sha256(json.dumps(messages).encode()).hexdigest(),
           'note': 'Non-streaming tool request: total latency, not TTFT.'}
    suite.save(label + '.json', row)
    with suite.journal_lock:
        with suite.journal.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        suite.records.append(row)
    if choice['finish_reason'] not in ('stop', 'tool_calls') or not row['usage']:
        raise RuntimeError(f'Incomplete request: {label}')
    return row


def agent_loops(suite, config):
    sessions = config.get('parallelSessions', 4)
    turns = config.get('agentTurns', 4)
    target = config.get('agentContextTokens', 131000)
    histories = []
    for index in range(sessions):
        archive, codes, _ = suite.synthetic(target, f'AGENT{index}')
        histories.append([{'role': 'system', 'content':
            'Use get_inventory when asked. Treat the archive as reference data. '
            'After the tool result, return only JSON with sku, count, and codes '
            '(the three archive secret codes as an array in archive order).'},
            {'role': 'user', 'content': 'Reference archive:\n' + archive[0]['content']},
            {'role': 'assistant', 'content': 'I have recorded the reference archive.'}])
        if suite.tokenize(histories[-1]) + turns * 1024 + 512 >= 262144:
            raise ValueError('Agent workload would exceed context budget')
    suite.reset()
    time.sleep(12)  # Flush previous workload's speculative counters.
    overall_before = suite.metrics(f'{suite.phase}-agents-c{sessions}-overall-before')
    evidence = []
    for turn in range(turns):
        # Force one resume from LMCache midway, retaining growing tool histories.
        restored = turn == turns // 2
        if restored:
            suite.reset()
        label = f'{suite.phase}-agents-c{sessions}-turn-{turn}'
        before = suite.metrics(label + '-before')
        def work(index):
            sku = f'AX-{index}-{turn}'
            count = 23 + index * 17 + turn
            salt = f'{suite.run_id}:agent:c{sessions}:{index}'
            messages = histories[index] + [{'role': 'user', 'content':
                f'Look up inventory for {sku}. Return its SKU, count, and the archive codes.'}]
            call_row = timed_request(suite, f'{label}-session-{index}-tool', messages,
                                     salt, tools=TOOLS, tool_choice='required')
            messages = append_tool_result(messages, call_row['message'], sku, count)
            answer_row = timed_request(suite, f'{label}-session-{index}-answer', messages,
                                       salt, tools=TOOLS, tool_choice='none',
                                       response_format={'type': 'json_object'})
            answer = json.loads(answer_row['message']['content'])
            codes = [f'AGENT{index}-{suffix}' for suffix in ('RIVER-729', 'MAPLE-418', 'COMET-653')]
            correct = answer == {'sku': sku, 'count': count, 'codes': codes}
            histories[index] = messages + [assistant_message(answer_row['message'])]
            result = {'session': index, 'turn': turn, 'correct': correct,
                      'toolSeconds': call_row['totalSeconds'],
                      'answerSeconds': answer_row['totalSeconds'],
                      'promptTokens': answer_row['usage']['prompt_tokens']}
            suite.save(f'{label}-session-{index}-checked.json', result)
            if not correct:
                raise RuntimeError(f'Agent answer mismatch: {label}, session {index}')
            return result
        started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=sessions) as pool:
            rows = list(pool.map(work, range(sessions)))
        time.sleep(1)
        metrics = delta(before, suite.metrics(label + '-after'))
        record = {'turn': turn, 'gpuReset': restored, 'sessions': rows,
                  'wallSeconds': time.perf_counter() - started, 'metricsDelta': metrics}
        evidence.append(record)
        suite.save(f'agent-loops-c{sessions}.json', {'status': 'running', 'turns': evidence})
        print(f'{label}: {sessions} correct sessions, reset={restored}', flush=True)
        if restored and metrics.get('lmcache_mp_num_chunks_loaded_total', 0) <= 0:
            raise RuntimeError('Agent resume had no measured external cache loads')
    time.sleep(12)
    overall_delta = delta(overall_before, suite.metrics(f'{suite.phase}-agents-c{sessions}-overall-after'))
    suite.save(f'agent-loops-c{sessions}.json', {'status': 'complete', 'turns': evidence,
        'metricsDelta': overall_delta,
        'note': 'Growing real tool-call histories; synthetic archive and inventory fixture.'})


def prefix_experiment(suite):
    # Same query and content length; only the position of a changing identifier differs.
    archive, codes, count = suite.synthetic(32000, 'PREFIX')
    results = []
    for placement in ('early', 'late'):
        suite.reset()
        rows = []
        for turn in range(4):
            dynamic = f'Turn identifier: {turn:04d}.\n'
            text = archive[0]['content']
            messages = [{'role': 'user', 'content':
                         dynamic + text if placement == 'early' else text + '\n' + dynamic}]
            rows.append(suite.chat(f'prefix-{placement}', f'turn-{turn}', messages,
                        f'{suite.run_id}:prefix:{placement}', codes))
        results.append({'placement': placement, 'requests': [row['id'] for row in rows],
                        'totalSeconds': [row['totalSeconds'] for row in rows],
                        'ttftSeconds': [row['ttftSeconds'] for row in rows]})
    suite.save('prefix-experiment.json', {'status': 'complete', 'archiveTokens': count,
        'results': results, 'note': 'Stable salt within each variant; changing identifier early versus late.'})


CODING_CASES = [
    ('positive_sum', 'Return the sum of strictly positive integers in a list.',
     [([1, -2, 3, 0], 4), ([], 0), ([-1, -2], 0), ([9, 4, 9], 22)]),
    ('deduplicate', 'Remove duplicate integers from a list, preserving first occurrence order.',
     [([3, 1, 3, 2, 1], [3, 1, 2]), ([], []), ([0, 0], [0]), ([-1, 2, -1], [-1, 2])]),
    ('runs', 'Given a list of integers, return consecutive run-length encoding as a list of [value, count] lists.',
     [([1, 1, 2, 1], [[1, 2], [2, 1], [1, 1]]), ([], []), ([7], [[7, 1]]), ([0, 0, 0], [[0, 3]])]),
    ('prefix_sums', 'Return a list of inclusive running sums of a list of integers.',
     [([1, 2, -1], [1, 3, 2]), ([], []), ([-2, 2], [-2, 0]), ([0, 0], [0, 0])]),
]

# Execute only these fixtures in a bounded child inside the experimental container.
# Restricted builtins and dunder/import rejection reduce accidental side effects;
# this is a benchmark validator, not a general untrusted-code sandbox.
CODE_CHECK = r'''
import ast, json, sys
data = json.load(sys.stdin)
tree = ast.parse(data['source'])
assert len(tree.body) == 1 and isinstance(tree.body[0], ast.FunctionDef)
assert tree.body[0].name == 'solve' and not tree.body[0].decorator_list
for node in ast.walk(tree):
    assert not isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal))
    if isinstance(node, ast.Name): assert not node.id.startswith('__')
    if isinstance(node, ast.Attribute): assert node.attr in ('append','get','items','sort','values','keys','add','fromkeys','index','count','extend','insert','setdefault','pop')
safe = {name: getattr(__builtins__, name) for name in
        ('sum','len','range','enumerate','zip','sorted','min','max','abs','list','dict','tuple','set','int','str','bool','filter','map','any','all','reversed')}
scope = {'__builtins__': safe}
exec(compile(tree, '<model-answer>', 'exec'), scope)
actual = [scope['solve'](argument) for argument, expected in data['tests']]
assert actual == [expected for argument, expected in data['tests']], repr(actual)
print('passed')
'''


def coding_workload(suite):
    if sys.platform != 'linux':
        raise RuntimeError('Run generated-code validation only in the test container')
    evidence = []
    time.sleep(12)
    for concurrency in (1, 2, 4):
        suite.reset()
        label = f'{suite.phase}-coding-c{concurrency}'
        before = suite.metrics(label + '-before')
        def work(item):
            name, description, tests = item
            messages = [{'role': 'system', 'content':
                'Write plain Python 3 code only, without Markdown. Define exactly one '
                'function solve(values), with no imports, decorators, annotations, or tests.'},
                {'role': 'user', 'content': description}]
            row = timed_request(suite, f'{label}-{name}', messages,
                                f'{suite.run_id}:{label}:{name}', max_tokens=1024)
            source = row['message']['content'].strip()
            if source.startswith('```') and source.endswith('```'):
                source = source.split('\n', 1)[1].rsplit('```', 1)[0].strip()
            try:
                checked = subprocess.run([sys.executable, '-I', '-c', CODE_CHECK],
                    input=json.dumps({'source': source, 'tests': tests}), text=True,
                    capture_output=True, timeout=10, cwd='/tmp')
                correct, error = checked.returncode == 0, checked.stderr[-2000:]
            except subprocess.TimeoutExpired:
                correct, error = False, 'Generated function exceeded 10 seconds'
            return {'case': name, 'correct': correct, 'error': error,
                    'totalSeconds': row['totalSeconds'], 'usage': row['usage']}
        started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            rows = list(pool.map(work, CODING_CASES))
        wall = time.perf_counter() - started
        time.sleep(12)  # Allow speculative counters to publish before the next group.
        metrics = delta(before, suite.metrics(label + '-after'))
        evidence.append({'concurrency': concurrency, 'rows': rows,
                         'wallSeconds': wall, 'metricsDelta': metrics,
                         'allCorrect': all(row['correct'] for row in rows)})
        suite.save('coding-workload.json', {'status': 'running', 'groups': evidence})
    suite.save('coding-workload.json', {'status': 'complete', 'groups': evidence,
        'allCorrect': all(group['allCorrect'] for group in evidence),
        'note': 'Small executable coding fixtures; not a general coding benchmark.'})


def run_experiments(suite, config):
    if config.get('agentLoops'):
        counts = config.get('agentConcurrencies') or ((1, 2, 4) if config.get('agentConcurrencySweep') else (config.get('parallelSessions', 4),))
        if len(set(counts)) != len(counts) or any(type(count) is not int or not 1 <= count <= 16 for count in counts):
            raise ValueError('Agent concurrency counts must be unique integers from 1 to 16')
        for count in counts:
            agent_loops(suite, dict(config, parallelSessions=count))
    # Keep the baseline/eager agent comparison's preceding workload identical.
    if config.get('prefixExperiment'):
        prefix_experiment(suite)
    if config.get('codingWorkload'):
        coding_workload(suite)
