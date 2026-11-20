"""Inspect an isolated Linux image against a mounted N1X target and draft configs.

Mount the target at /model and the installed DFlash2 checkpoint at /drafter. No model weights are loaded.
"""

import argparse
import importlib.metadata
import json
from pathlib import Path


def model(path):
    cfg = json.loads((Path(path) / "config.json").read_text())
    text = cfg.get("text_config", cfg)
    return {
        "architecture": cfg["architectures"],
        "width": text["hidden_size"],
        "vocab": text["vocab_size"],
        "layers": text["num_hidden_layers"],
        "capture_layers": cfg.get("dflash_config", {}).get("target_layer_ids"),
    }


def probe(target_dir, draft_dir):
    import torch
    from vllm.config import LoadConfig
    from vllm.model_executor.model_loader import get_model_loader
    from vllm.plugins import load_general_plugins

    installed = {}
    for package in ("vllm", "torch", "transformers", "lmcache"):
        try:
            installed[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            installed[package] = None
    try:
        load_general_plugins()
        loader = type(get_model_loader(LoadConfig(load_format="mbx"))).__name__
    except (ValueError, KeyError, RuntimeError) as error:
        loader = f"{type(error).__name__}: {error}"
    target, draft = model(target_dir), model(draft_dir)
    result = {
        "packages": installed,
        "cuda_build": torch.version.cuda,
        "mbx_loader": loader,
        "async_ple_reader": Path("/opt/mbx/lib/libmbx_ple_async.so").is_file(),
        "target": target,
        "local_dflash": draft,
    }
    if torch.cuda.is_available():
        result["gpu"] = torch.cuda.get_device_name(0)
        result["capability"] = torch.cuda.get_device_capability(0)
        try:
            a = torch.ones((32, 32), device="cuda", dtype=torch.bfloat16)
            result["bf16_matmul_correct"] = (a @ a).eq(32).all().item()
        except RuntimeError as error:
            result["gpu_error"] = str(error)
        try:
            from vllm import _custom_ops as ops

            values = torch.linspace(-2, 2, 4096, device="cuda", dtype=torch.float32).reshape(32, 128)
            quantized, scale = ops.scaled_fp8_quant(values)
            restored = quantized.float() * scale
            result["vllm_fp8_relative_rms"] = (
                torch.linalg.vector_norm(restored - values) / torch.linalg.vector_norm(values)
            ).item()
        except (ImportError, RuntimeError, NotImplementedError, AttributeError) as error:
            result["vllm_fp8_error"] = str(error)
    return result


def resolve_speculation(target, draft, tokens):
    from vllm.engine.arg_utils import EngineArgs

    try:
        config = EngineArgs(
            model=target,
            max_model_len=1024,
            max_num_seqs=2,
            speculative_config={
                "method": "dflash",
                "model": draft,
                "num_speculative_tokens": tokens,
            },
        ).create_engine_config()
        spec = config.speculative_config
        return {
            "method": spec.method,
            "draft_tokens": spec.num_speculative_tokens,
        }
    except Exception as error:
        return {"error": f"{type(error).__name__}: {error}"}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("model", "drafter"):
        p.add_argument("--" + name, default="/" + name)
    args = p.parse_args()
    result = probe(args.model, args.drafter)
    result["flash_next_dflash2_config"] = resolve_speculation(args.model, args.drafter, 3)
    print("N1X_COMPAT_RESULT " + json.dumps(result))
