"""Install the N1X target adapter into the pinned upstream 0.33.0 image."""
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
import shutil
import sysconfig


site = Path(sysconfig.get_path("purelib"))
base = site / "vllm"
source = Path(__file__).parent
hashes = {
    "model_executor/models/config.py": "850156ca9540bdd899ab0a3d4e8bcc5a790acd07b6c2b1848fd906a67eb7424a",
    "models/qwen4_exp/nvidia/model.py": "e9d9c2a6d4201331f6a16cbf08aa46f513397393f02e12e4c746a345f089a1c0",
    "models/qwen4_exp/nvidia/ngram_embedding.py": "8442e161d90d09ccc0aab06aea809e8f1fc387c8af348a32a9424bfa1f755533",
    "model_executor/layers/quantization/auto_gptq.py": "328fded6916796f03b491e600141a1c071c156004dd4b7d79716a74a73087f0f",
    "models/qwen4_exp/nvidia/qsa.py": "7254b2f0137f00b4aff7588b4c9e0444aebc6a9ee3246c94a5f7553435412fd9",
}
if version("vllm") != "0.33.0":
    raise RuntimeError("This adapter requires upstream vLLM 0.33.0")
for name, expected in hashes.items():
    if sha256((base / name).read_bytes()).hexdigest() != expected:
        raise RuntimeError(f"Unexpected upstream 0.33.0 source: {name}")


def replace(name, old, new, count=1):
    path = base / name
    text = path.read_text()
    if text.count(old) != count:
        raise RuntimeError(f"Unexpected patch context in {name}")
    patched = text.replace(old, new)
    compile(patched, str(path), "exec")
    path.write_text(patched)


config_file = "model_executor/models/config.py"
guard = '"mtp",\n            "ngram",\n            "ngram_gpu",\n        }:'
replace(config_file, "import json\n", "import json\nimport os\n")
replace(config_file, guard, guard[:-1] + """ and not (
            spec_config.method == "dflash"
            and os.environ.get("N1X_QWEN4_DFLASH") == "1"
            and current_platform.is_cuda()
            and parallel_config.world_size == 1
        ):""")
for target in ("models/qwen4_exp/nvidia/qsa.py", "models/qwen4_exp/nvidia/model.py"):
    replace(target, "import torch\n", "import os\nimport torch\n")
# The hybrid checkpoint keeps the QSA indexer BF16 and its Q/K/V weights FP8.
replace("models/qwen4_exp/nvidia/qsa.py", "self.fuse_indexer_projection = vllm_config.lora_config is None",
        'self.fuse_indexer_projection = vllm_config.lora_config is None and not os.getenv("N1X_W4_PLE_DIR")')
replace("models/qwen4_exp/nvidia/model.py", "if vllm_config.lora_config is not None:\n            # LoRA",
        'if vllm_config.lora_config is not None or os.getenv("N1X_W4_PLE_DIR"):\n            # LoRA', count=2)
head = '            prefix=maybe_prefix(prefix, "lm_head"),'
replace("models/qwen4_exp/nvidia/model.py", head,
        '            quant_config=vllm_config.quant_config if os.getenv("N1X_W4_PLE_DIR") else None,\n' + head)
for module in ("n1x_dflash_capture.py", "n1x_w4.py"):
    shutil.copyfile(source / module, site / module)
with (base / "models/qwen4_exp/nvidia/model.py").open("a") as model:
    model.write('\nif os.environ.get("N1X_QWEN4_DFLASH") == "1":\n'
                '    import sys\n    from n1x_dflash_capture import apply as _capture\n'
                '    _capture(sys.modules[__name__])\n')
choice = "        # A TP reduce-scatter covers all vocabulary owners only when ETP=TP."
replace("models/qwen4_exp/nvidia/ngram_embedding.py", choice, """        from n1x_w4 import external_embedding
        embedding_cls = external_embedding(embedding_cls, embedding_prefix)
""" + choice)
with (base / "model_executor/layers/quantization/auto_gptq.py").open("a") as gptq:
    gptq.write("\nfrom n1x_w4 import enable_hybrid\nenable_hybrid(AutoGPTQConfig)\n")
