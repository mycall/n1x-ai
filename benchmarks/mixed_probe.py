"""Concurrent long retrieval, vision, arithmetic, and tool use with thinking."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import re
import time

from PIL import Image, ImageDraw
from agent_cache_probe import Probe, request, save


def run(args):
    p=Probe(args)
    archives={n:p.archive(n)[0] for n in (65000,131000)}
    lengths={n:json.loads(request(args.url+'/tokenize',dict(model='qwen',messages=m,
             chat_template_kwargs={'enable_thinking':True})))['count'] for n,m in archives.items()}
    picture=Image.new('RGB',(320,160),'white')
    draw=ImageDraw.Draw(picture)
    draw.ellipse((20,20,130,130),fill='red')
    draw.rectangle((190,20,300,130),fill='blue')
    buffer=io.BytesIO()
    picture.save(buffer,format='PNG')
    uri='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()
    tools=[dict(type='function',function=dict(name='lookup_inventory',description='Get stock by SKU.',
           parameters=dict(type='object',properties=dict(sku=dict(type='string')),
                           required=['sku'],additionalProperties=False)))]

    def chat(messages,salt,**extra):
        return p.chat(messages,salt,max_tokens=1024,chat_template_kwargs={'enable_thinking':True},**extra)

    def archive(cycle):
        length=65000 if cycle%2==0 else 131000
        choice=chat(archives[length],f'{p.salt}-archive-{cycle}')
        answer=choice['message'].get('content') or ''
        return dict(kind='archive',correct=choice['finish_reason']=='stop' and
                    bool(re.search(r'CEDAR-5831.*MAPLE-9264.*BIRCH-1748',answer,re.S)),
                    prompt_tokens=lengths[length])

    def vision(cycle):
        choice=chat([dict(role='user',content=[dict(type='text',text=
            'Name the color and shape on the left, then on the right. Be brief.'),
            dict(type='image_url',image_url=dict(url=uri))])],f'{p.salt}-vision-{cycle}')
        answer=(choice['message'].get('content') or '').lower()
        return dict(kind='vision',correct=choice['finish_reason']=='stop' and
                    bool(re.search(r'red\s+circle.*blue\s+square',answer,re.S)))

    def arithmetic(cycle):
        choice=chat([dict(role='user',content=f'Return only the integer result of {9+cycle} times 7.')],
                    f'{p.salt}-short-{cycle}')
        return dict(kind='arithmetic',correct=choice['finish_reason']=='stop' and
                    (choice['message'].get('content') or '').strip()==str((9+cycle)*7))

    def tool(cycle):
        sku=f'MIX-{cycle}'
        messages=[dict(role='user',content=f'Use lookup_inventory to look up SKU {sku}. '
                       'After its result return only the integer count. Do not guess.')]
        salt=f'{p.salt}-tool-{cycle}'
        choice=chat(messages,salt,tools=tools,tool_choice='auto')
        calls=choice['message'].get('tool_calls') or []
        try:
            valid=choice['finish_reason']=='tool_calls' and len(calls)==1 and \
                calls[0]['function']['name']=='lookup_inventory' and \
                json.loads(calls[0]['function']['arguments'])=={'sku':sku}
        except (ValueError,KeyError,TypeError):
            valid=False
        if not valid:
            return dict(kind='tool',correct=False)
        assistant=dict(role='assistant',content=choice['message'].get('content'),tool_calls=calls)
        if choice['message'].get('reasoning'):
            assistant['reasoning']=choice['message']['reasoning']
        messages.extend([assistant,dict(role='tool',tool_call_id=calls[0]['id'],
                         content=json.dumps(dict(sku=sku,count=23+cycle)))])
        answer=chat(messages,salt,tools=tools,tool_choice='none')
        return dict(kind='tool',correct=answer['finish_reason']=='stop' and
                    (answer['message'].get('content') or '').strip()==str(23+cycle))

    before=p.snapshot('before')
    rows=[]
    start=time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for cycle in range(12):
                cycle_start=time.monotonic()
                checks=list(pool.map(lambda fn:fn(cycle),(archive,vision,arithmetic,tool)))
                if cycle in (7,11):
                    revisit=archive(cycle-3)
                    revisit['kind']='revisit'
                    checks.append(revisit)
                rows.append(dict(cycle=cycle+1,elapsed_s=time.monotonic()-cycle_start,checks=checks))
                save(args.out/'cycles.json',rows)
                print(json.dumps(rows[-1]),flush=True)
                if not all(check['correct'] for check in checks):
                    raise RuntimeError('Mixed-workload correctness failed; inspect responses')
    finally:
        after=p.snapshot('after')
        counters={k:after.get(k,0)-before.get(k,0) for k in (
            'vllm:num_preemptions_total','vllm:external_prefix_cache_hits_total',
            'lmcache_mp_num_finished_retrieves_total','lmcache_mp_l2_prefetch_load_completed_chunks_total')}
        checks=[check for row in rows for check in row['checks']]
        save(args.out/'summary.json',dict(completed_cycles=len(rows),planned_cycles=12,
             correct=sum(check['correct'] for check in checks),checks=len(checks),
             elapsed_s=time.monotonic()-start,thinking=True,max_output_tokens=1024,
             concurrency=4,prompt_tokens=lengths,counters=counters))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8000')
    parser.add_argument('--out',type=Path,required=True)
    run(parser.parse_args())
