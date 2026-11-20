// Trial adapter for the installed FP8 asynchronous PLE table reader.
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <dlfcn.h>
#include <fcntl.h>
#include <list>
#include <mutex>
#include <stdexcept>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <unordered_map>
#include <vector>

namespace {
constexpr size_t width = 160, capacity = (16u << 20) / width;
using Read = int (*)(int, const int64_t*, int64_t, uint8_t*, uint8_t*, int, int, int);
using Clock = std::chrono::steady_clock;
struct Entry { int64_t key; std::array<uint8_t, width> row; };
struct Reader {
    Read read;
    uint64_t* stats; // epoch, enabled, calls, requested, hits, native calls, elapsed ns, resident rows
    uint64_t epoch = UINT64_MAX;
    dev_t device{};
    ino_t inode{};
    std::mutex mutex;
    std::list<Entry> lru;
    std::unordered_map<int64_t, std::list<Entry>::iterator> index;
    std::vector<int64_t> missed, positions;
    std::vector<uint8_t> buffer;

    Reader() {
        void* original = dlopen("/opt/mbx/lib/libmbx_ple_nvme.so", RTLD_NOW | RTLD_LOCAL);
        read = original ? reinterpret_cast<Read>(dlsym(original, "mbx_t_read")) : nullptr;
        if (!read) throw std::runtime_error("original reader unavailable");
        char file[96];
        snprintf(file, sizeof(file), "/tmp/ple-trial-%d.stats", getpid());
        int fd = open(file, O_CREAT | O_EXCL | O_RDWR | O_CLOEXEC, 0600);
        if (fd < 0) throw std::runtime_error("cannot create stats file");
        if (ftruncate(fd, 4096)) {
            close(fd);
            unlink(file);
            throw std::runtime_error("cannot size stats file");
        }
        stats = static_cast<uint64_t*>(mmap(nullptr, 4096, PROT_READ|PROT_WRITE, MAP_SHARED, fd, 0));
        close(fd);
        if (stats == MAP_FAILED) throw std::runtime_error("stats mmap failed");
    }

    void remember(int64_t id, const uint8_t* bytes) {
        auto found = index.find(id);
        if (found != index.end()) {
            lru.splice(lru.begin(), lru, found->second);
            return;
        }
        if (lru.size() == capacity) {
            auto last = std::prev(lru.end());
            index.erase(last->key);
            lru.splice(lru.begin(), lru, last);
        } else {
            lru.emplace_front();
        }
        lru.front().key = id;
        memcpy(lru.front().row.data(), bytes, width);
        index.emplace(id, lru.begin());
    }

    int run(int fd, const int64_t* ids, int64_t n, uint8_t* out, uint8_t* scales,
            int cp, int cs, int threads) {
        std::lock_guard<std::mutex> guard(mutex);
        auto start = Clock::now();
        uint64_t next = __atomic_load_n(stats, __ATOMIC_ACQUIRE);
        bool enabled = __atomic_load_n(stats+1, __ATOMIC_RELAXED);
        struct stat file{};
        if (fstat(fd, &file)) return -1;
        if (epoch != next || file.st_dev != device || file.st_ino != inode) {
            lru.clear(); index.clear();
            if (enabled) index.reserve(capacity);
            epoch = next; device = file.st_dev; inode = file.st_ino;
        }
        int rc = 0;
        int64_t hits = 0;
        bool issued = true;
        if (!enabled || cp != width || cs != 0 || n <= 0) {
            rc = read(fd, ids, n, out, scales, cp, cs, threads);
        } else {
            missed.clear(); positions.clear();
            for (int64_t i = 0; i < n; ++i) {
                auto item = index.find(ids[i]);
                if (item == index.end()) {
                    missed.push_back(ids[i]); positions.push_back(i);
                } else {
                    lru.splice(lru.begin(), lru, item->second);
                    memcpy(out + i*width, item->second->row.data(), width);
                    ++hits;
                }
            }
            issued = !missed.empty();
            if (issued) {
                uint8_t* dst = out;
                if (hits) {
                    buffer.resize(missed.size()*width);
                    dst = buffer.data();
                }
                rc = read(fd, missed.data(), missed.size(), dst, scales, cp, cs, threads);
                if (!rc) {
                    for (size_t j=0; j<missed.size(); ++j) {
                        auto row = dst + j*width;
                        if (hits) memcpy(out + positions[j]*width, row, width);
                        remember(missed[j], row);
                    }
                }
            }
        }
        auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-start).count();
        __atomic_fetch_add(stats+3, n, __ATOMIC_RELAXED);
        __atomic_fetch_add(stats+4, hits, __ATOMIC_RELAXED);
        __atomic_fetch_add(stats+5, issued, __ATOMIC_RELAXED);
        __atomic_fetch_add(stats+6, ns, __ATOMIC_RELAXED);
        __atomic_store_n(stats+7, lru.size(), __ATOMIC_RELAXED);
        __atomic_fetch_add(stats+2, 1, __ATOMIC_RELEASE);
        return rc;
    }
};
}
extern "C" int mbx_t_read(int fd, const int64_t* ids, int64_t n, uint8_t* out, uint8_t* scales,
                          int cp, int cs, int threads) {
    try {
        static Reader reader;
        return reader.run(fd, ids, n, out, scales, cp, cs, threads);
    } catch (const std::exception& e) {
        fprintf(stderr, "PLE trial reader failed: %s\n", e.what());
        return -1;
    }
}
