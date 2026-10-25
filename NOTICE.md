# Third-party software and models

The MIT license covers this repository's original scripts and documentation.
It does not replace licenses for dependencies, upstream code, or model weights.

- [magi-v5-public](https://github.com/Saren-Arterius/qwen3.8-Flash-DGX-AutoRound/tree/magi-v5-public): Apache-2.0. The build uses the pinned upstream recipe and its hybrid-weight and PLE patches.
- [vLLM](https://github.com/vllm-project/vllm) and [LMCache](https://github.com/LMCache/LMCache): Apache-2.0. The optional runtime applies local compatibility modifications to their installed code. A copy of the license is in [licenses/Apache-2.0.txt](licenses/Apache-2.0.txt).
- NVIDIA CUDA, PyTorch, FlashInfer, and other dependencies retain their respective licenses inside the runtime images and packages.
- Model weights are downloaded separately from Hugging Face. Review their repository licenses and terms before use or redistribution. No model weights are included here.
