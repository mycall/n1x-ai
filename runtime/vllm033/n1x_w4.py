"""Eager-only support for the N1X W4 checkpoint and its external FP8 table."""
import json
import os
from pathlib import Path
import re
import struct

import numpy as np
import torch
from torch import nn


def external_embedding(default, prefix):
    if not os.environ.get("N1X_W4_PLE_DIR"):
        return default
    from vllm.config import get_current_vllm_config
    config = get_current_vllm_config()
    if not config.model_config.enforce_eager or config.parallel_config.world_size != 1:
        raise ValueError("External N1X PLE requires eager execution on one GPU")
    if not prefix.endswith(".layers.1.ple.ple_embedding.ngram_embedding"):
        raise ValueError(f"Unknown external PLE layer: {prefix}")
    return ExternalEmbedding


class ExternalEmbedding(nn.Module):
    supports_prefetch = False

    def __init__(self, rows, width, **kwargs):
        super().__init__()
        self.org_vocab_size = rows
        shards = {}
        scale = None
        pattern = re.compile(r"model\.language_model\.layers\.1\.ple\.ple_embedding\.ngram_embedding\.(?:shard_(\d+)\.weight|weight_scale)$")
        for path in sorted(Path(os.environ["N1X_W4_PLE_DIR"]).glob("*.safetensors")):
            with path.open("rb") as handle:
                length, = struct.unpack("<Q", handle.read(8))
                header = json.loads(handle.read(length))
                for name, info in header.items():
                    match = pattern.fullmatch(name)
                    if not match:
                        continue
                    start, end = info["data_offsets"]
                    offset = 8 + length + start
                    if match[1] is None:
                        if info["dtype"] != "BF16" or end - start != 2 or scale is not None:
                            raise ValueError("Unexpected external FP8 scale")
                        handle.seek(offset)
                        scale, = struct.unpack("<f", b"\0\0" + handle.read(2))
                        continue
                    index = int(match[1])
                    count, columns = info["shape"]
                    if (info["dtype"] != "F8_E4M3" or columns != width or
                            end - start != count * width or index in shards):
                        raise ValueError(f"Invalid FP8 embedding shard: {name}")
                    shards[index] = np.memmap(path, mode="r", dtype=np.uint8,
                                               offset=offset, shape=(count, width))
        if sorted(shards) != list(range(128)) or scale is None or not 0 < scale < float("inf"):
            raise ValueError("Incomplete external PLE table")
        self.shards = [shards[i] for i in range(len(shards))]
        self.rows_per_shard = len(self.shards[0])
        if any(len(s) != self.rows_per_shard for s in self.shards) or rows != len(shards) * self.rows_per_shard:
            raise ValueError("External PLE vocabulary differs from the target")
        self.scale = scale
        self.width = width
        # The stock constructor logs the storage dtype and device.
        self.register_buffer("weight", torch.empty(0, dtype=torch.float8_e4m3fn, device="cpu"), persistent=False)

    def forward(self, ids):
        flat = ids.detach().cpu().numpy().reshape(-1)
        if flat.size and (flat.min() < 0 or flat.max() >= self.org_vocab_size):
            raise IndexError("PLE index outside the external table")
        parts, offsets = np.divmod(flat, self.rows_per_shard)
        out = np.empty((len(flat), self.width), dtype=np.uint8)
        for part in np.unique(parts):
            mask = parts == part
            out[mask] = self.shards[part][offsets[mask]]
        return torch.from_numpy(out).to(ids.device).view(torch.float8_e4m3fn).reshape(*ids.shape, self.width)

    def dequantize(self, embeddings, output_dtype):
        return (embeddings.float() * self.scale).to(output_dtype)


def enable_hybrid(cls):
    if not os.environ.get("N1X_W4_PLE_DIR"):
        return
    from vllm.model_executor.layers.linear import LinearBase
    from vllm.model_executor.layers.quantization.fp8 import Fp8Config
    from vllm.transformers_utils.config import get_safetensors_params_metadata

    update, get_method = cls.maybe_update_config, cls.get_quant_method

    def update_config(self, model_name, hf_config=None, revision=None):
        update(self, model_name, hf_config=hf_config, revision=revision)
        metadata = get_safetensors_params_metadata(model_name, revision=revision)
        self.n1x_fp8_layers = {
            name.removeprefix("model.language_model.layers.").removesuffix(".weight")
            for name, info in metadata.items()
            if name.startswith("model.language_model.layers.") and name.endswith(".weight") and info["dtype"] == "F8_E4M3"
            and name.removesuffix(".weight") + ".weight_scale_inv" in metadata
        }
        if not self.n1x_fp8_layers:
            raise ValueError("The N1X W4 target has no FP8 side layers with block scales")

    def quant_method(self, layer, prefix):
        if isinstance(layer, LinearBase) and prefix.startswith("language_model.model.layers."):
            key = prefix.removeprefix("language_model.model.layers.")
            parent, _, leaf = key.rpartition(".")
            components = self.packed_modules_mapping.get(leaf, [leaf])
            if leaf == "qkv_proj" and parent.endswith(".self_attn"):
                # The quantizer retains the class mapping from before the model
                # instance selects separate BF16 indexer and FP8 QKV modules.
                components = ("q_proj", "k_proj", "v_proj")
            fp8 = [f"{parent}.{c}" in self.n1x_fp8_layers for c in components]
            if any(fp8) and not all(fp8):
                raise ValueError(f"Inconsistent checkpoint precision for fused layer {prefix}")
            if all(fp8):
                config = Fp8Config(is_checkpoint_fp8_serialized=True,
                                   activation_scheme="dynamic", weight_block_size=[128, 128])
                config.packed_modules_mapping = self.packed_modules_mapping
                return config.get_quant_method(layer, prefix)
        return get_method(self, layer, prefix)

    cls.maybe_update_config = update_config
    cls.get_quant_method = quant_method
