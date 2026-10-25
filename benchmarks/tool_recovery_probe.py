"""Thinking-enabled tool selection, transient retries, and argument repair."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time

from agent_cache_probe import Probe, save


def run(args):
    probe = Probe(args)
    tools = [dict(type='function', function=dict(
        name=name, description=description,
        parameters=dict(type='object', properties=dict(sku=dict(type='string')),
                        required=['sku'], additionalProperties=False)))
        for name, description in [('lookup_inventory', 'Get current stock count.'),
                                  ('lookup_price', 'Get current price in cents.')]]

    def session(number):
        salt=f'{probe.salt}-recovery-{number}'
        messages=[dict(role='system',content=(
            'Use the appropriate lookup tool; never guess values. Retry a transient tool error once. '
            'If the service gives a canonical_sku, retry with that exact SKU. '
            'After success, return only the requested CODE:VALUE.'))]
        rows=[]
        def chat():
            return probe.chat(messages,salt,tools=tools,tool_choice='auto',
                              chat_template_kwargs={'enable_thinking':True},max_tokens=1024)
        for turn in range(6):
            name='lookup_inventory' if turn%2==0 else 'lookup_price'
            field='count' if turn%2==0 else 'price_cents'
            mode=('normal','transient','canonical')[turn%3]
            sku=f'AX-{number}-{turn}'
            expected_sku=sku
            code=f'CASE-{number}-{turn}'
            value=137+number*11+turn*3
            messages.append(dict(role='user',content=(
                f'Look up the {"stock count" if field=="count" else "price in cents"} '
                f'for SKU {sku}. Return only {code}:VALUE with the value from the tool.')))
            passed=False
            reason='No final answer'
            successful_tool=False
            calls_seen=0
            for step in range(4):
                choice=chat()
                message=choice['message']
                calls=message.get('tool_calls') or []
                if calls:
                    assistant=dict(role='assistant',content=message.get('content'),tool_calls=calls)
                    if message.get('reasoning'):
                        assistant['reasoning']=message['reasoning']
                    messages.append(assistant)
                    try:
                        valid=(choice['finish_reason']=='tool_calls' and len(calls)==1
                               and calls[0]['function']['name']==name
                               and json.loads(calls[0]['function']['arguments'])=={'sku':expected_sku}
                               and not successful_tool)
                    except (ValueError,KeyError,TypeError):
                        valid=False
                    if not valid:
                        # Close every tool call so subsequent turns remain well formed.
                        for call in calls:
                            messages.append(dict(role='tool',tool_call_id=call['id'],
                                                 content='{"error":"unexpected_tool_call"}'))
                        reason='Incorrect tool, arguments, or duplicate successful call'
                        break
                    calls_seen+=1
                    if calls_seen==1 and mode=='transient':
                        result=dict(error='temporary_unavailable',retryable=True)
                    elif calls_seen==1 and mode=='canonical':
                        expected_sku=sku+'-CANON'
                        result=dict(error='noncanonical_sku',canonical_sku=expected_sku)
                    else:
                        successful_tool=True
                        result=dict(sku=expected_sku,**{field:value})
                    messages.append(dict(role='tool',tool_call_id=calls[0]['id'],content=json.dumps(result)))
                else:
                    answer=(message.get('content') or '').strip()
                    messages.append(dict(role='assistant',content=answer))
                    passed=successful_tool and choice['finish_reason']=='stop' and answer==f'{code}:{value}'
                    reason='pass' if passed else 'Incorrect or premature final answer'
                    break
            rows.append(dict(session=number,turn=turn,mode=mode,tool=name,passed=passed,
                             calls=calls_seen,reason=reason))
        return rows

    before=probe.snapshot('before')
    start=time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows=[row for group in pool.map(session,range(4)) for row in group]
    elapsed=time.monotonic()-start
    after=probe.snapshot('after')
    summary=dict(correct=sum(row['passed'] for row in rows),planned=len(rows),
                 elapsed_s=elapsed,thinking=True,concurrency=4,max_output_tokens=1024,
                 preemptions=after.get('vllm:num_preemptions_total',0)-before.get('vllm:num_preemptions_total',0),
                 rows=rows)
    save(args.out/'summary.json',summary)
    print(json.dumps(summary),flush=True)
    if summary['correct']!=summary['planned']:
        raise RuntimeError('Tool recovery qualification failed; inspect summary and responses')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8000')
    parser.add_argument('--out',type=Path,required=True)
    run(parser.parse_args())
