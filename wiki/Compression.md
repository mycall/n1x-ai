# Compression on N1X

For repeated long documents, the 16 MiB PLE row cache was the most useful experiment. It reduced median whole-request latency by 18.1% on repeated prompts and 4.7% on resumed prompts with new material. BF16 recurrent state was the strongest capacity result, saving 19.9% in LMCache. Both remain experimental. The default W4 profile uses FP32 recurrent state, the stock asynchronous FP8 PLE reader and uncompressed SSD objects.

**Use `qwen38fn-w4-kv15-bf16` when host L1 or SSD capacity limits prefix retention.** On a prepared machine, stop the current service, run `.\n1x.ps1 setup -Profile qwen38fn-w4-kv15-bf16` once to create the dedicated L2 volume, then run `.\n1x.ps1 start -Profile qwen38fn-w4-kv15-bf16`. This selects the same 15 GiB geometry used in the paired test and a dedicated BF16 cache volume and namespace. Previously stored FP32 prefixes will need a cold prefill in the new namespace. For a workload dominated by reopened documents, run the optional PLE trial with representative text before integrating the row cache into a serving image.

## LMCache capacity and restore

The November 19 comparison held the GPU cache pool at 15 GiB, context at 262,144, DFlash2 at K3, KV dtype at hybrid FP8, and LMCache blocks and chunks at 4,096 tokens. Each precision arm started with its own empty SSD namespace. Two 16–17k-token prompts exercised cold prefill, immediate follow-up and SSD restore after a process restart.

| Measurement | FP32 recurrent state | BF16 recurrent state |
| --- | ---: | ---: |
| Reported live GPU cache tokens | 730,605 | 730,605 |
| Occupancy in each of host L1 and SSD L2 | 1,088 MiB | 872 MiB |
| Time to first content, cold A / B | 6.14 / 6.03 s | 6.03 / 5.98 s |
| Time to first content, reopened A / B | 1.98 / 0.56 s | 1.96 / 0.60 s |
| Restored tokens, A / B | 12,288 / 16,384 | 12,288 / 16,384 |

At this object mix, the same L1 or L2 budget holds approximately 25% more prefixes with BF16. GPU capacity stayed flat because vLLM padded recurrent-state pages to attention page size. Both arms passed exact recall and one inventory tool round trip. The sample is too small to qualify long-running agent quality under reduced precision. Native NVFP4 attention KV failed during model initialization in the pinned 0.32 image. Its Qwen QSA layer requires BF16 or FP8-e4m3 main KV.

No SSD reads were recorded for cold requests or immediate follow-ups. Each resumed prompt caused one SSD restore. An application-level L2 codec charges encode cost on store and decode cost on an SSD hit. Its payoff depends on how often extra retained prefixes avoid a cold prefill. These controlled trials do not measure deployment hit frequency.

## Lossless compression and batching

LZ4 on 4 KiB pages saved 0.8% on FP32-state L2 samples and 1.1% on BF16-state samples. These measurements used actual stored objects and userspace codecs. The trials did not enable kernel zram or change swap settings.

The original zram experiment measured swappable browser pages. Its 3.35:1 ratio describes that page mix. N1X stores L2 objects as files on SSD, so enabling compressed swap alone would leave those files at their original size. [Original experiment and zswap follow-up](https://curiousbits.nl/blog/do-not-buy-ram-compress/)

| Zstd level 1, FP32-state sample | 4 KiB | 64 KiB | 1 MiB |
| --- | ---: | ---: | ---: |
| Space saved | 12.4% | 13.8% | 13.8% |
| Decode throughput | 210 MiB/s | 603 MiB/s | 651 MiB/s |

On the SSD, an alternating raw/framed/framed/raw test read the same 133 MiB using direct I/O. Raw averaged 95 ms. Reading and decoding 1 MiB frames averaged 281 ms. BF16-state objects saved 19.0% at 1 MiB, with direct-read times of 86 ms raw and 284 ms framed for 105 MiB. These are single-reader timings.

For each of four prefixes, joining three 8 MiB object samples saved only 20 bytes over independent frames. Fetching all three and decoding the individual frames in parallel took 13–16 ms versus 33–41 ms serially. Independent frames also permit a single-group restore. SSD compression makes sense to revisit when measured capacity pressure justifies extra restore time. [Precision and codec measurements](data/compression-precision-20261119.json)

To decide from a deployment trace, count how many cold prefills the extra capacity would turn into restores. Multiply that count by the measured time saved per converted request. Compare it with the extra time spent decoding existing SSD hits and encoding objects on the request path. For scale, converting one of the tested cold prompts to a raw restore saved about 4–5.5 seconds to first content. The 133 MiB codec probe added 0.19 seconds per read. These measurements used different units of work, so estimating a break-even hit rate requires the bytes actually restored per request.

## PLE table precision and hot rows

PLE looks up n-gram embeddings during prefill and generation. Group-of-16 INT4 cut sampled row payload from 160 to 100 bytes. Across 131,072 real FP8 rows, median row cosine similarity was 0.9964 and relative RMS error was 8.6%. Small random native reads took about 1 ms for 16 rows in either layout. INT4 cost more CPU time to unpack. The prototype verified sample reads on explicitly constructed maps. It did not establish full-model answer quality or free GPU memory. The working FP8 table is already disk-backed.

The lossless hot-row trial instead cached 104,857 original FP8 rows in the asynchronous PLE read path. A standalone measurement found 23.3 MiB of additional resident memory for the 16 MiB payload and lookup structures. Direct parity checks covered 115,384 row requests, including duplicates and eviction.

| Serving workload | Median paired latency reduction | Faster pairs | PLE rows served from cache |
| --- | ---: | ---: | ---: |
| Repeated long prefix, short follow-up | 18.1% | 12/12 | 99.9% |
| Cached prefix plus about 800 new tokens | 4.7% | 10/12 | 35.2% |
| Fresh document lookup | 1.5% | 7/12 | 23.2% |
| Fresh code task | 1.9% | 8/12 | 36.3% |
| Two simultaneous requests, batch completion | 2.4% | 8/12 | 33.9% |

Each November 20 pair used the same live engine and prompt. Conditions alternated in order. Fresh requests used separate KV salts and resumed requests shared a salt. The repeated case reused 8,192 of 9,442 prompt tokens in both arms, leaving about 1,250 tokens of repeated text for PLE. All 144 scored responses were correct, and the 72 corresponding outputs matched exactly. The system speed changed during warm-up, before timed requests. The fresh and concurrent estimates had paired bootstrap intervals spanning zero. Use workload-specific A/B results before selecting the cache. [Serving measurements](data/ple-hot-20261120.json) · [Run the experiments](../benchmarks/compression/README.md)
