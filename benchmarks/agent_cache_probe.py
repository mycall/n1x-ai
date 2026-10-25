"""Bounded agent, simultaneous restore, and mixed-workload qualification."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import threading
import time
import urllib.request
import uuid


def request(url, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=3600) as response:
        return response.read().decode()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


class Probe:
    def __init__(self, args):
        self.args = args
        self.out = args.out
        self.out.mkdir(parents=True, exist_ok=True)
        self.salt = uuid.uuid4().hex
        self.rows = []
        self.lock = threading.Lock()

    def chat(self, messages, salt, **extra):
        body = dict(model='qwen', messages=messages, temperature=0, max_tokens=128,
                    cache_salt=salt, chat_template_kwargs={'enable_thinking': False})
        body.update(extra)
        start = time.monotonic()
        response = json.loads(request(self.args.url + '/v1/chat/completions', body))
        with self.lock:
            with (self.out / 'responses.jsonl').open('a') as file:
                file.write(json.dumps(dict(salt=salt, elapsed_s=time.monotonic()-start, response=response))+'\n')
        return response['choices'][0]

    def snapshot(self, name):
        values = {}
        for service, url in [('vllm', self.args.url+'/metrics'), ('lmcache', 'http://127.0.0.1:8080/metrics')]:
            raw = request(url)
            (self.out / f'{name}-{service}.prom').write_text(raw)
            for line in raw.splitlines():
                match = re.match(r'^([^#\s{]+)(?:\{.*\})?\s+([\d.eE+-]+)$', line)
                if match:
                    key, value = match.groups()
                    values[key] = values.get(key, 0) + float(value)
        return values

    def archive(self, target):
        count = max(10, target // 18)
        for _ in range(5):
            lines = [f'Record {i:06d}: warehouse item has batch {(i*7919+137)%999983:06d} and status archived.' for i in range(count)]
            for position, tree, code in [(0.1,'cedar','CEDAR-5831'),(0.5,'maple','MAPLE-9264'),(0.9,'birch','BIRCH-1748')]:
                lines[int(count*position)] = f'SPECIAL RECORD: The {tree} access code is {code}.'
            text = 'Read this archive and answer the question at its end.\n'+'\n'.join(lines)+'\nQuestion: Return the cedar, maple, and birch access codes, in that order, and nothing else.'
            messages = [dict(role='user', content=text)]
            tokens = json.loads(request(self.args.url+'/tokenize', dict(model='qwen', messages=messages, chat_template_kwargs={'enable_thinking':False})))['count']
            if target*.95 <= tokens <= target:
                return messages, tokens
            count = max(10, round(count*(target-128)/tokens))
        raise RuntimeError('Unable to size archive')

    def retrieve(self, messages, salt):
        choice = self.chat(messages, salt)
        correct = choice['finish_reason']=='stop' and bool(re.search(r'CEDAR-5831.*MAPLE-9264.*BIRCH-1748', choice['message'].get('content',''), re.S))
        if not correct:
            raise RuntimeError('Archive retrieval failed')
        return True

    def agents(self):
        thinking = getattr(self.args, 'agent_thinking', False)
        def chat(messages, salt, **extra):
            return self.chat(messages, salt, max_tokens=1024 if thinking else 128,
                             chat_template_kwargs={'enable_thinking': thinking}, **extra)
        tools = [dict(type='function', function=dict(name='lookup_inventory', description='Look up stock by SKU.', parameters=dict(type='object', properties=dict(sku=dict(type='string')), required=['sku'], additionalProperties=False)))]
        for repeat, order in enumerate(([1,2,4], [4,2,1])):
            for concurrency in order:
                sessions = []
                for number in range(4):
                    filler = '\n'.join(f'Archive item {i:06d}: reference batch {(i*7919)%999983:06d}; status archived.' for i in range(450))
                    messages = [dict(role='system',content='Use lookup_inventory whenever asked for inventory. Preserve the exact requested SKU. After its result, return only the requested CODE:COUNT format.'), dict(role='user',content=f'{filler}\nSession code is AGENT-{number:04d}. Remember it. Reply only READY.')]
                    salt=f'{self.salt}-agent-{repeat}-{concurrency}-{number}'
                    choice=chat(messages,salt,tools=tools,tool_choice='auto')
                    if choice['finish_reason']!='stop' or choice['message']['content'].strip()!='READY':
                        raise RuntimeError('Agent warmup failed')
                    messages.append(dict(role='assistant',content=choice['message']['content']))
                    sessions.append((number,messages,salt))
                def session(item):
                    number,messages,salt=item
                    correct=0
                    for turn in range(3):
                        sku=f'AX-{number}-{turn}'
                        messages.append(dict(role='user',content=f'Look up inventory for SKU {sku}. Then return the session code and inventory count separated by a colon, with no other text.'))
                        choice=chat(messages,salt,tools=tools,tool_choice='auto')
                        calls=choice['message'].get('tool_calls',[])
                        if choice['finish_reason']!='tool_calls' or len(calls)!=1 or calls[0]['function']['name']!='lookup_inventory' or json.loads(calls[0]['function']['arguments'])!={'sku':sku}:
                            messages.append(dict(role='assistant',content=choice['message'].get('content') or ''))
                            continue
                        assistant=dict(role='assistant',content=choice['message'].get('content'),tool_calls=calls)
                        if choice['message'].get('reasoning'):
                            assistant['reasoning']=choice['message']['reasoning']
                        messages.append(assistant)
                        count=23+number*7+turn
                        messages.append(dict(role='tool',tool_call_id=calls[0]['id'],content=json.dumps(dict(sku=sku,count=count))))
                        choice=chat(messages,salt,tools=tools,tool_choice='none')
                        answer=(choice['message'].get('content') or '').strip()
                        messages.append(dict(role='assistant',content=answer))
                        correct+=int(choice['finish_reason']=='stop' and answer==f'AGENT-{number:04d}:{count}')
                    return correct
                before=self.snapshot(f'agent-{repeat}-c{concurrency}-before')
                start=time.monotonic()
                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    correct=sum(pool.map(session,sessions))
                elapsed=time.monotonic()-start
                after=self.snapshot(f'agent-{repeat}-c{concurrency}-after')
                row=dict(repeat=repeat,concurrency=concurrency,planned_tasks=12,correct_tasks=correct,elapsed_s=elapsed,correct_tasks_s=correct/elapsed,preemptions=after.get('vllm:num_preemptions_total',0)-before.get('vllm:num_preemptions_total',0))
                row.update(thinking=thinking, max_output_tokens=1024 if thinking else 128)
                self.rows.append(row)
                save(self.out/'summary.json',self.rows)
                print(json.dumps(row),flush=True)

    def restores(self):
        messages,tokens=self.archive(131000)
        salts=[f'{self.salt}-restore-{i}' for i in range(2)]
        for salt in salts:
            self.retrieve(messages,salt)
        pressure,_=self.archive(261000)
        for i in range(3):
            self.retrieve(pressure,f'{self.salt}-pressure-{i}')
            print(f'Eviction pressure {i+1}/3 complete',flush=True)
        before=self.snapshot('restore-before')
        start=time.monotonic()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda salt:self.retrieve(messages,salt),salts))
        after=self.snapshot('restore-after')
        keys=['vllm:prefix_cache_hits_total','vllm:external_prefix_cache_hits_total','vllm:num_preemptions_total','lmcache_mp_num_finished_retrieves_total','lmcache_mp_l2_prefetch_load_completed_chunks_total']
        delta={key:after.get(key,0)-before.get(key,0) for key in keys}
        qualified=all(results) and delta[keys[0]]==0 and delta[keys[1]]>2*(tokens-4096) and delta[keys[3]]>=2 and delta[keys[4]]>0
        row=dict(prompt_tokens_each=tokens,correct=len(results),elapsed_s=time.monotonic()-start,qualified=qualified,delta=delta)
        save(self.out/'summary.json',row)
        print(json.dumps(row),flush=True)
        if not qualified:
            raise RuntimeError('Simultaneous external restores not established; inspect counters')

    def soak(self):
        from PIL import Image, ImageDraw
        import io
        picture=Image.new('RGB',(320,160),'white')
        draw=ImageDraw.Draw(picture)
        draw.ellipse((20,20,130,130),fill='red')
        draw.rectangle((190,20,300,130),fill='blue')
        buffer=io.BytesIO()
        picture.save(buffer,format='PNG')
        uri='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()
        archives={length:self.archive(length)[0] for length in (65000,131000)}
        before=self.snapshot('soak-before')
        start=time.monotonic()
        for cycle in range(12):
            messages=archives[65000 if cycle%2==0 else 131000]
            self.retrieve(messages,f'{self.salt}-soak-{cycle}')
            choice=self.chat([dict(role='user',content=[dict(type='text',text='Name the color and shape on the left, then on the right. Be brief.'),dict(type='image_url',image_url=dict(url=uri))])],f'{self.salt}-vision-{cycle}')
            answer=choice['message'].get('content','').lower()
            if choice['finish_reason']!='stop' or not all(word in answer for word in ('red','circle','blue','square')):
                raise RuntimeError('Mixed-workload vision check failed')
            choice=self.chat([dict(role='user',content='Return only the result of 9 times 7.')],f'{self.salt}-short-{cycle}')
            if choice['finish_reason']!='stop' or choice['message']['content'].strip()!='63':
                raise RuntimeError('Mixed-workload short check failed')
            if cycle>=4 and cycle%4==3:
                self.retrieve(archives[65000],f'{self.salt}-soak-{cycle-3}')
            self.rows.append(dict(cycle=cycle+1,elapsed_s=time.monotonic()-start,passed=True))
            save(self.out/'summary.json',self.rows)
            print(json.dumps(self.rows[-1]),flush=True)
        after=self.snapshot('soak-after')
        save(self.out/'counters.json',{key:after.get(key,0)-before.get(key,0) for key in ['vllm:num_preemptions_total','lmcache_mp_num_finished_retrieves_total','lmcache_mp_l2_prefetch_load_completed_chunks_total']})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=['agents','restores','soak'],required=True)
    parser.add_argument('--url',default='http://127.0.0.1:8000')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--agent-thinking',action='store_true')
    args=parser.parse_args()
    probe=Probe(args)
    getattr(probe,args.phase)()


if __name__=='__main__':
    main()
