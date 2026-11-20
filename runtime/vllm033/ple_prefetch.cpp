#include <cuda_runtime_api.h>
#include <cstdint>
#include <cstring>

// One immutable descriptor per input size. All operations touching a reader's
// staging buffers are ordered on its private CUDA stream.
struct Gather {
    const uint8_t* const* shards;
    const int64_t* ids;
    uint8_t* output;
    int32_t* valid;
    int64_t count, rows, rows_per_shard, width;
};

static void CUDART_CB gather(void* argument) {
    const auto& task = *static_cast<const Gather*>(argument);
    *task.valid = 1;
    for (int64_t i = 0; i < task.count; ++i) {
        const int64_t id = task.ids[i];
        auto dst = task.output + i * task.width;
        if (id < 0 || id >= task.rows) {
            *task.valid = 0;
            std::memset(dst, 0, task.width);
        } else {
            auto src = task.shards[id / task.rows_per_shard];
            std::memcpy(dst, src + (id % task.rows_per_shard) * task.width, task.width);
        }
    }
}

extern "C" int submit_gather(cudaStream_t stream, Gather* descriptor) {
    return cudaLaunchHostFunc(stream, gather, descriptor);
}
