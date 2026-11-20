"""Run inside the GPU trial image with the FP8 PLE volume mounted read-only."""
import torch

from n1x_prefetch import PrefetchedEmbedding


def main():
    table = PrefetchedEmbedding(320001536, 160, max_total_tokens=4, num_ngram_heads=16)
    checked = 0
    for size in (1, 2, 4):
        ids = torch.zeros((size, 16), device="cuda", dtype=torch.long)

        def lookup():
            table.start_prefetch(ids)
            return table.finalize_prefetch(size).view(torch.uint8).clone()

        lookup()
        torch.cuda.synchronize()
        graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(graph):
            output = lookup()
        previous = None
        for start in (0, table.rows_per_shard - 1, table.org_vocab_size - ids.numel(), 17, 0):
            ids.copy_(torch.arange(start, start + ids.numel(), device="cuda").reshape_as(ids))
            graph.replay()
            reference = table.forward(ids).view(torch.uint8).reshape_as(output)
            assert torch.equal(output, reference)
            assert previous is None or not torch.equal(output, previous)
            previous = output.clone()
            checked += ids.numel()
    print(f"15 CUDA graph replays matched {checked} original FP8 rows")


if __name__ == "__main__":
    main()
