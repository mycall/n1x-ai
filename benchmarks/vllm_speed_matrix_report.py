"""Validate and summarize response-local and common vLLM matrix measurements."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics


def prom_value(path, metric):
    values = []
    for line in path.read_text().splitlines():
        if line.startswith(metric + '{') or line.startswith(metric + ' '):
            values.append(float(line.rsplit(' ', 1)[1]))
    return sum(values) if values else None


def summarize(folder, incomplete=False):
    manifest = json.loads((folder / 'manifest.json').read_text())
    receipts = [json.loads(p.read_text()) for p in sorted(folder.glob('*-receipt.json'))]
    receipts = [r for r in receipts if not r.get('warmup')]
    expected = {(r, c, n) for r in range(1, manifest['repeats'] + 1)
                for c in manifest['concurrency'] for n in manifest['contexts']}
    actual = {(r['repeat'], r['concurrency'], r['target_input']) for r in receipts}
    if not incomplete and (actual != expected or len(actual) != len(receipts)):
        raise ValueError(f'Incomplete/duplicate matrix: {len(actual)}/{len(expected)} waves')
    if any(not r['valid'] for r in receipts):
        raise ValueError('Invalid wave in measured matrix')
    for receipt in receipts:
        if len(receipt['responses']) != receipt['concurrency']:
            raise ValueError('Response count does not match concurrency')
        for row in receipt['responses']:
            usage, metrics = row.get('usage') or {}, row.get('metrics') or {}
            if not (row.get('done') and row.get('status') == 200
                    and row.get('finish_reason') == 'length'
                    and usage.get('completion_tokens') == 512
                    and receipt['target_input']-4 <= usage.get('prompt_tokens', 0) <= receipt['target_input']
                    and (usage.get('prompt_tokens_details') or {}).get('cached_tokens') == 0
                    and metrics.get('time_to_first_token_ms', 0) > 0
                    and metrics.get('generation_time_ms', 0) > 0):
                raise ValueError('Invalid response in matrix receipt')
    cells = []
    for n in manifest['contexts']:
        for c in manifest['concurrency']:
            waves = [r for r in receipts if r['target_input'] == n and r['concurrency'] == c]
            if not waves:
                continue
            rows = [x for w in waves for x in w['responses']]
            common = [json.loads((folder / f'{w["name"]}-vllm.json').read_text()) for w in waves]
            prompt_tokens = sum(x['usage']['prompt_tokens'] for x in rows)
            output_tokens = sum(x['usage']['completion_tokens'] for x in rows)
            pp = sum(x['metrics']['time_to_first_token_ms'] / 1000 for x in rows)
            decode = sum(x['metrics']['generation_time_ms'] / 1000 for x in rows)
            duration = sum(x['duration'] for x in common)
            read = prompt_tokens / pp
            write = (output_tokens - len(rows)) / decode
            wave_read = [sum(x['usage']['prompt_tokens'] for x in w['responses']) /
                         sum(x['metrics']['time_to_first_token_ms'] / 1000 for x in w['responses'])
                         for w in waves]
            wave_write = [sum(x['usage']['completion_tokens'] - 1 for x in w['responses']) /
                          sum(x['metrics']['generation_time_ms'] / 1000 for x in w['responses'])
                          for w in waves]
            burst_input = [sum(x['usage']['prompt_tokens'] for x in w['responses']) / b['duration']
                           for w, b in zip(waves, common)]
            burst_output = [sum(x['usage']['completion_tokens'] for x in w['responses']) / b['duration']
                            for w, b in zip(waves, common)]
            cell = dict(context=n, concurrency=c, waves=len(waves), requests=len(rows),
                        prompt_tokens_range=[min(x['usage']['prompt_tokens'] for x in rows),
                                             max(x['usage']['prompt_tokens'] for x in rows)],
                        read_tks=read, write_tks=write,
                        read_wave_range=[min(wave_read), max(wave_read)],
                        write_wave_range=[min(wave_write), max(wave_write)],
                        mean_pp_s=pp/len(rows), mean_decode_s=decode/len(rows),
                        mean_queue_s=statistics.mean(x['metrics']['queue_time_ms']/1000 for x in rows),
                        mean_client_ttft_s=statistics.mean(t for b in common for t in b['ttfts']),
                        client_read_tks=prompt_tokens/sum(t for b in common for t in b['ttfts']),
                        client_read_wave_range=[min(sum(x['usage']['prompt_tokens'] for x in w['responses']) / sum(b['ttfts']) for w, b in zip(waves, common)),
                                                max(sum(x['usage']['prompt_tokens'] for x in w['responses']) / sum(b['ttfts']) for w, b in zip(waves, common))],
                        mean_client_e2e_s=statistics.mean(t for b in common for t in b['latencies']),
                        common_mean_tpot_ms=statistics.mean(b['mean_tpot_ms'] for b in common),
                        common_input_throughput=prompt_tokens/duration,
                        common_output_throughput=output_tokens/duration,
                        common_input_wave_range=[min(burst_input), max(burst_input)],
                        common_output_wave_range=[min(burst_output), max(burst_output)],
                        common_duration_s=duration,
                        cached_tokens=sum(x['usage']['prompt_tokens_details']['cached_tokens'] for x in rows),
                        wave_names=[w['name'] for w in waves])
            preemptions = []
            observed_completions = []
            for wave in waves:
                paths = [folder / f'{wave["name"]}-{phase}.prom' for phase in ('before', 'after')]
                if all(p.exists() for p in paths):
                    before, after = [prom_value(p, 'vllm:num_preemptions_total') for p in paths]
                    if before is not None and after is not None:
                        preemptions.append(after-before)
                    first, last = [prom_value(p, 'vllm:request_success_total') for p in paths]
                    if first is not None and last is not None:
                        if last-first != wave['concurrency']:
                            raise ValueError('Unexpected server completion count; unrelated work or counter reset')
                        observed_completions.append(last-first)
            cell['preemptions'] = sum(preemptions) if len(preemptions) == len(waves) else None
            cell['observed_server_completions'] = (sum(observed_completions)
                if len(observed_completions) == len(waves) else None)
            cells.append(cell)
    return dict(protocol=manifest['protocol'], generated_utc=datetime.now(timezone.utc).isoformat(),
                manifest=manifest, complete=actual == expected, measured_waves=len(receipts),
                measured_requests=sum(c['requests'] for c in cells), cells=cells)


def table(data, key, digits=1):
    contexts = data['manifest']['contexts']
    lines = ['| Concurrency | 4K | 8K | 64K | 262K window |',
             '| --- | ---: | ---: | ---: | ---: |']
    lookup = {(x['concurrency'], x['context']): x for x in data['cells']}
    for c in data['manifest']['concurrency']:
        values = [f'{lookup[c,n][key]:,.{digits}f}' if (c,n) in lookup else 'pending'
                  for n in contexts]
        lines.append(f'| C{c} | ' + ' | '.join(values) + ' |')
    return '\n'.join(lines)


def markdown(data):
    return ('# qwen38fn-best read/write speed matrix\n\n'
            f'{data["measured_waves"]} measured bursts; {data["measured_requests"]} requests. '
            f'Complete: {data["complete"]}.\n\n'
            'C1–C8 counts submitted clients; requests may wait for capacity. '
            'Compare read rates including and excluding waiting before drawing conclusions about responsiveness.\n\n'
            'Read including waiting (tokens/s per request; input / client time to first token):\n\n'
            + table(data, 'client_read_tks') + '\n\n'
            'Read excluding queue time (tokens/s per request; input / scheduled-to-first-token time):\n\n'
            + table(data, 'read_tks') + '\n\n'
            'Write (tokens/s per request; 511 / first-to-last-token time):\n\n'
            + table(data, 'write_tks', 2) + '\n\n'
            'Aggregate output throughput (tokens/s across the complete burst, including prefill/queue):\n\n'
            + table(data, 'common_output_throughput', 2) + '\n\n'
            'Mean client time to first token (seconds, including queue):\n\n'
            + table(data, 'mean_client_ttft_s', 2) + '\n\n'
            'Mean server queue time (seconds):\n\n'
            + table(data, 'mean_queue_s', 2) + '\n')


def html(data):
    # Standalone interactive artifact: no CDN, install, or external data requests.
    template = '''<!doctype html><html lang="en"><meta charset="utf-8">
<title>qwen38fn-best speed matrix</title><style>
body{font:16px system-ui;max-width:1150px;margin:32px auto;padding:0 20px;background:#101827;color:#e4eaf3}
select,button{font:inherit;padding:8px;background:#223049;color:inherit;border:1px solid #718096;border-radius:5px}
svg{width:100%;background:#162238;border-radius:8px;margin:20px 0}text{fill:#e4eaf3;font:14px system-ui}
table{border-collapse:collapse;width:100%}th,td{padding:10px;text-align:right;border-bottom:1px solid #34445c}
td:first-child,th:first-child{text-align:left}small,p{color:#b7c8e0}.detail{min-height:50px}
section{border-top:1px solid #34445c;margin-top:36px;padding-top:12px}summary{cursor:pointer}
</style><h1>qwen38fn-best speed matrix</h1>
<p id="subtitle"></p>
<p><strong>C1–C8 counts submitted clients.</strong> Requests can wait for capacity; C8 does not mean eight simultaneously resident histories. Compare the first two charts to see the effect of excluding waiting. Point details show the sampled peak running count.</p>
<div id="panels"></div>
<script>
const data=__DATA__;
document.querySelector('#subtitle').textContent='C1–C8 • 4K / 8K / 64K / 262K window • fixed 512-token generation • '+data.manifest.repeats+' cold bursts per cell';
const choices={client_read_tks:['Read rate including waiting','tokens/s per request'],
read_tks:['Read rate excluding queue time','tokens/s per request'],write_tks:['Write rate per stream','tokens/s per request'],
common_output_throughput:['Aggregate output throughput (whole burst)','tokens/s'],
common_input_throughput:['Aggregate input throughput (whole burst)','tokens/s'],
mean_client_ttft_s:['Client time to first token','seconds'],mean_queue_s:['Server queue time','seconds'],
mean_client_e2e_s:['Client end-to-end latency','seconds']};
const explanations={
client_read_tks:'Input tokens divided by client time to first token. Includes server queueing and transport. Higher is better; this is the read rate that reflects waiting.',
read_tks:'Input tokens divided by scheduled-to-first-token time. Excludes queueing. A long prompt may look faster here because fewer requests run at once; this does not mean it responds sooner.',
write_tks:'Generated tokens after the first divided by first-to-last-token time. Includes pauses while other requests prefill, but excludes initial prefill and queueing. Higher is better.',
common_output_throughput:'All generated tokens divided by complete burst duration, including prefill, waiting and decode. Measures total output delivered across all clients. Higher is better.',
common_input_throughput:'All input tokens divided by complete burst duration, including decode. Measures total input processed for this fixed-output workload. Higher is better.',
mean_client_ttft_s:'Time from client submission until the first token arrives, including queueing. Lower is better.',
mean_queue_s:'Server time waiting before initial scheduling. Excluded from the scheduled read rate. Lower is better.',
mean_client_e2e_s:'Time from client submission until generation finishes. Includes prefill, queueing and decode. Lower is better.'};
const colors=['#5ac8fa','#fdb750','#ad8bfa','#5cdea6'];
const labels=['4K','8K','64K','262K window'];
function createPanel(defaultKey){
const panel=document.createElement('section');
panel.innerHTML='<h2></h2><p class="explanation"></p><label>Metric <select></select></label> <button>Download chart SVG</button><svg viewBox="0 0 1000 450" role="img"></svg><p class="detail">Hover, tap, or focus a point for waiting and scheduling details.</p><details><summary>Exact values</summary><table></table></details><p class="notes"></p>';
document.querySelector('#panels').append(panel);
const select=panel.querySelector('select');
for(const [key,value] of Object.entries(choices)){let o=document.createElement('option');o.value=key;o.textContent=value[0];select.append(o)}
select.value=defaultKey;
const svg=panel.querySelector('svg'), ns='http://www.w3.org/2000/svg';
function add(tag,attrs,text){let n=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);if(text)n.textContent=text;svg.append(n);return n}
function draw(){svg.replaceChildren();let key=select.value,rangeKey={client_read_tks:'client_read_wave_range',read_tks:'read_wave_range',write_tks:'write_wave_range',common_input_throughput:'common_input_wave_range',common_output_throughput:'common_output_wave_range'}[key];
panel.querySelector('h2').textContent=choices[key][0];
panel.querySelector('.explanation').textContent=explanations[key];
svg.setAttribute('aria-label',choices[key][0]+' across submitted client counts and input lengths');
panel.querySelector('.detail').textContent='Hover, tap, or focus a point for waiting and scheduling details.';
let max=Math.max(...data.cells.flatMap(x=>rangeKey?x[rangeKey]:[x[key]]))*1.12;
add('rect',{x:0,y:0,width:1000,height:450,fill:'#162238'});
add('text',{x:70,y:28},choices[key][0]+' ('+choices[key][1]+')');
for(let i=0;i<=5;i++){let y=365-i*60;add('line',{x1:75,x2:950,y1:y,y2:y,stroke:'#34445c'});add('text',{x:65,y:y+5,'text-anchor':'end'},(max*i/5).toFixed(1))}
for(let c=1;c<=8;c++)add('text',{x:95+(c-1)*118,y:390,'text-anchor':'middle'},'C'+c);
add('text',{x:500,y:410,'text-anchor':'middle'},'Submitted clients (some may be waiting)');
data.manifest.contexts.forEach((ctx,i)=>{let cells=data.cells.filter(x=>x.context===ctx).sort((a,b)=>a.concurrency-b.concurrency);
let points=cells.map(x=>[95+(x.concurrency-1)*118,365-x[key]/max*300]);
add('polyline',{points:points.map(x=>x.join(',')).join(' '),fill:'none',stroke:colors[i],'stroke-width':3});
cells.forEach((x,j)=>{if(rangeKey){let a=365-x[rangeKey][0]/max*300,b=365-x[rangeKey][1]/max*300,h=points[j][0];
add('line',{x1:h,x2:h,y1:a,y2:b,stroke:colors[i],'stroke-width':2,opacity:.65});
for(let y of [a,b])add('line',{x1:h-4,x2:h+4,y1:y,y2:y,stroke:colors[i],opacity:.65});}
let p=add('circle',{cx:points[j][0],cy:points[j][1],r:6,fill:colors[i],tabindex:0});
let detail=labels[i]+' / '+x.concurrency+' submitted clients: '+choices[key][0]+' '+x[key].toFixed(2)+' '+choices[key][1]+'. Mean wait '+x.mean_queue_s.toFixed(2)+' s; first token '+x.mean_client_ttft_s.toFixed(2)+' s. Sampled peak running: '+(x.sampled_peak_running??'unavailable')+' (sampling can miss peaks). '+x.requests+' measured requests.';
let show=()=>panel.querySelector('.detail').textContent=detail;
p.setAttribute('aria-label',detail);p.addEventListener('mouseenter',show);p.addEventListener('focus',show);p.addEventListener('click',show)});
add('text',{x:100+i*220,y:440,style:'fill:'+colors[i]},labels[i]);});
let rows='<tr><th>Submitted clients</th>'+labels.map(x=>'<th>'+x+'</th>').join('')+'</tr>';
for(let c=1;c<=8;c++){rows+='<tr><td>C'+c+'</td>';for(let n of data.manifest.contexts){let x=data.cells.find(x=>x.context===n&&x.concurrency===c);rows+='<td>'+(x?x[key].toFixed(2):'pending')+'</td>'}rows+='</tr>'}panel.querySelector('table').innerHTML=rows;
let full=data.cells.filter(x=>x.context===Math.max(...data.manifest.contexts)).flatMap(x=>x.prompt_tokens_range);
panel.querySelector('.notes').textContent=(rangeKey?'Vertical bars show the minimum and maximum of the three burst estimates, not confidence intervals. ':'')+'Rates use summed tokens / summed durations. The 262K window reserves 512 output tokens. Zero cached input tokens. Clock variation affects comparisons; these are speed measurements, not answer-quality scores.';
}
select.addEventListener('change',draw);draw();
panel.querySelector('button').onclick=()=>{let copy=svg.cloneNode(true);copy.setAttribute('xmlns',ns);copy.querySelectorAll('text').forEach(n=>{n.setAttribute('fill','#e4eaf3');n.setAttribute('font-family','system-ui');n.setAttribute('font-size','14')});let b=new Blob([new XMLSerializer().serializeToString(copy)],{type:'image/svg+xml'});let a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='qwen38fn-best-'+select.value+'.svg';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
}
['client_read_tks','read_tks','write_tks','common_output_throughput'].forEach(createPanel);
</script></html>'''
    return template.replace('__DATA__', json.dumps(data).replace('</', '<\\/'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-incomplete', action='store_true')
    args = parser.parse_args()
    data = summarize(args.folder, args.allow_incomplete)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix('.json').write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')
    args.output.with_suffix('.md').write_text(markdown(data), encoding='utf-8')
    args.output.with_suffix('.html').write_text(html(data), encoding='utf-8')
