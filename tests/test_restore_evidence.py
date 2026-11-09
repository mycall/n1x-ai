import unittest

from benchmarks.agent_cache_probe import (
    LAZY_RESTORE_COUNTERS, RESTORE_COUNTERS, required_counter_deltas, restore_summary,
)
from benchmarks.cache_restore_capacity import require_restore_capacity, restore_storage_envelope


class RestoreEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.before = dict.fromkeys(RESTORE_COUNTERS, 0)
        self.after = dict(self.before)
        self.after.update({RESTORE_COUNTERS[1]: 260000, RESTORE_COUNTERS[3]: 2,
                           RESTORE_COUNTERS[4]: 186})

    def test_first_real_prefetch_sample_can_qualify_without_a_baseline_sample(self):
        for key in LAZY_RESTORE_COUNTERS:
            self.before.pop(key)
        row = restore_summary(self.before, self.after, 130877, [True, True], 4)
        self.assertTrue(row['qualified'])
        self.assertEqual(row['delta'][RESTORE_COUNTERS[4]], 186)
        self.assertEqual(set(row['initially_absent_counters']), LAZY_RESTORE_COUNTERS)

    def test_saved_failure_stays_failed_with_two_correct_uncached_replies(self):
        self.before.pop(RESTORE_COUNTERS[4])
        self.after = dict(self.before)
        row = restore_summary(self.before, self.after, 130877, [True, True], 110)
        self.assertFalse(row['qualified'])
        self.assertEqual(row['correct'], 2)
        self.assertIn('Required restore counters missing', row['error'])

    def test_positive_ssd_counter_alone_does_not_prove_external_restore(self):
        for changes in ({RESTORE_COUNTERS[0]: 4096}, {RESTORE_COUNTERS[1]: 0},
                        {RESTORE_COUNTERS[3]: 1}, {RESTORE_COUNTERS[4]: 0}):
            with self.subTest(changes=changes):
                after = dict(self.after, **changes)
                self.assertFalse(restore_summary(self.before, after, 130877, [True, True], 1)['qualified'])
        self.assertFalse(restore_summary(self.before, self.after, 130877, [True, False], 1)['qualified'])

    def test_missing_vllm_baseline_reset_and_nonfinite_counters_are_rejected(self):
        for value in (-1, float('nan'), float('inf')):
            after = dict(self.after)
            after[RESTORE_COUNTERS[4]] = value
            self.assertFalse(restore_summary(self.before, after, 130877, [True, True], 1)['qualified'])
        before = dict(self.before)
        before[RESTORE_COUNTERS[3]] = 3
        self.assertFalse(restore_summary(before, self.after, 130877, [True, True], 1)['qualified'])
        self.before.pop(RESTORE_COUNTERS[0])
        self.assertFalse(restore_summary(self.before, self.after, 130877, [True, True], 1)['qualified'])
        with self.assertRaises(ValueError):
            required_counter_deltas({}, self.after, RESTORE_COUNTERS,
                                    allow_initially_absent={RESTORE_COUNTERS[0]})


class RestoreCapacityTests(unittest.TestCase):
    def test_observed_fp32_layout_needs_more_than_the_failed_ssd_budget(self):
        envelope = restore_storage_envelope([118226944, 53477376, 41943040],
                                            seed_tokens=130877, pressure_tokens=260877)
        self.assertEqual(envelope['working_set_bytes'] / 2**30, 50.9375)
        for gib in (16, 48):
            with self.subTest(gib=gib), self.assertRaises(ValueError):
                require_restore_capacity(gib * 2**30, envelope)
        require_restore_capacity(64 * 2**30, envelope)

    def test_partial_chunks_and_file_alignment_are_reserved(self):
        envelope = restore_storage_envelope([4097], seed_tokens=4097, pressure_tokens=1,
                                            seed_count=1, pressure_count=1, reserve_bytes=0)
        self.assertEqual(envelope['required_bytes'], 3 * 8192)
        require_restore_capacity(3 * 8192, envelope)
        with self.assertRaises(ValueError):
            require_restore_capacity(3 * 8192 - 1, envelope)

    def test_invalid_layout_and_counts_are_rejected(self):
        for groups in ([], [0], [-1], [True]):
            with self.subTest(groups=groups), self.assertRaises(ValueError):
                restore_storage_envelope(groups, seed_tokens=10, pressure_tokens=20)
