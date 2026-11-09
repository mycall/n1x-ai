"""QSA capacity and rejection-wraparound checks without importing CUDA code."""
import importlib.util
from pathlib import Path
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('qsa_patch', ROOT / 'runtime/myllmbox/patch_qsa_ring.py')
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)


class QsaRingTests(unittest.TestCase):
    def capacity_function(self):
        source = ('def capacity(self, config):\n'
                  '    if True:\n'
                  '        span = self.compress_ratio + config.num_speculative_tokens\n'
                  + PATCH.OLD +
                  '        assert self.block_size % capacity == 0\n'
                  '        return capacity\n')
        scope = {'cdiv': lambda a, b: (a + b - 1) // b}
        exec(PATCH.rewrite(source), scope)
        return scope['capacity']

    def test_all_depths_fit_blocks_and_preserve_existing_depths(self):
        capacity = self.capacity_function()
        for ratio in (1, 2, 4, 8):
            owner = types.SimpleNamespace(compress_ratio=ratio, block_size=4096)
            for depth in range(8):
                with self.subTest(ratio=ratio, depth=depth):
                    ring = capacity(owner, types.SimpleNamespace(num_speculative_tokens=depth))
                    self.assertGreaterEqual(ring, ratio + depth)
                    self.assertEqual(ring % ratio, 0)
                    self.assertEqual(4096 % ring, 0)
                    if ratio == 4 and depth <= 4:
                        self.assertEqual(ring, ratio * ((ratio + depth + ratio - 1) // ratio))

    def test_rejected_drafts_do_not_overwrite_committed_open_group(self):
        capacity = self.capacity_function()
        for depth in range(1, 8):
            ring = capacity(types.SimpleNamespace(compress_ratio=4, block_size=4096),
                            types.SimpleNamespace(num_speculative_tokens=depth))
            for next_position in range(4, 129):
                group_start = (next_position // 4) * 4
                committed = list(range(group_start, next_position))
                cache = {position % ring: position for position in committed}
                # The target writes the bonus token and every draft before
                # acceptance is known. Even rejecting all drafts must leave
                # the previously committed open group available for replay.
                for position in range(next_position, next_position + depth + 1):
                    cache[position % ring] = position
                for position in committed:
                    self.assertEqual(cache[position % ring], position,
                                     (depth, next_position, position, ring))

    def test_missing_or_duplicate_anchor_rejected(self):
        for source in ('pass\n', PATCH.OLD * 2):
            with self.assertRaisesRegex(RuntimeError, 'anchor changed'):
                PATCH.rewrite(source)

    def test_unreviewed_source_is_not_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            target = site / 'vllm/models/qwen4_exp/common/qsa_cache.py'
            target.parent.mkdir(parents=True)
            target.write_text('unreviewed source\n')
            before = target.read_bytes()
            with self.assertRaisesRegex(RuntimeError, 'Unexpected QSA cache source'):
                PATCH.patch(site)
            self.assertEqual(target.read_bytes(), before)
            self.assertFalse((site / 'n1x-qsa-ring-patch.json').exists())


if __name__ == '__main__':
    unittest.main()
