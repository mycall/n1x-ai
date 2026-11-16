"""Create an indexed MTP view with ten routed experts; target weights stay untouched."""
import json
from pathlib import Path
import sys

target, output = map(Path, sys.argv[1:3])
if output.exists():
    raise SystemExit('Draft destination already exists; use a fresh directory')
config=json.loads((target/'config.json').read_text())
text=config.get('text_config',config)
if text['num_experts_per_tok']!=5 or text['shared_expert_intermediate_size']!=1280:
    raise SystemExit('Expected FP4-Local-AZ five-expert target with padded MTP shared expert')
text['num_experts_per_tok']=10
index=json.loads((target/'model.safetensors.index.json').read_text())['weight_map']
keep={k:v for k,v in index.items() if k.startswith(('mtp.','lm_head.')) or k.endswith('embed_tokens.weight')}
if not keep or not any(k.startswith('mtp.') for k in keep):
    raise SystemExit('No MTP tensors found')
output.mkdir(parents=True)
for item in target.iterdir():
    if item.name not in ('config.json','model.safetensors.index.json','.cache'):
        (output/item.name).symlink_to(item, target_is_directory=item.is_dir())
(output/'config.json').write_text(json.dumps(config,indent=2)+'\n')
(output/'model.safetensors.index.json').write_text(json.dumps(dict(metadata={},weight_map=keep))+'\n')
print(json.dumps(dict(draft=str(output),tensors=len(keep),shards=sorted(set(keep.values())))))
