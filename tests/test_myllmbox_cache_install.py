import unittest

from runtime.myllmbox.install_cache import EXPECTED_CORE, cache_constraints, source_build_options


class MyllmboxDependencyTests(unittest.TestCase):
    def test_source_rebuild_uses_installed_torch_and_rejects_cached_wheels(self):
        self.assertEqual(source_build_options('0'), [])
        self.assertEqual(source_build_options('1'), [
            '--no-binary', 'lmcache', '--no-build-isolation-package', 'lmcache',
            '--reinstall-package', 'lmcache', '--no-cache'])
        with self.assertRaises(ValueError):
            source_build_options('auto')

    def test_image_specific_constraints_preserve_vendor_core_and_other_pins(self):
        shared = 'torch==2.13.0\nnvidia-nccl-cu13==2.29.7\nlmcache==0.5.6\nnumpy==2.2.6\n'
        constraints, overrides = cache_constraints(shared, dict(EXPECTED_CORE))
        self.assertEqual(constraints, 'torch==2.13.0+cu130\nnvidia-nccl-cu13==2.30.7\nlmcache==0.5.6\nnumpy==2.2.6\n')
        self.assertEqual(overrides, 'nvidia-nccl-cu13==2.30.7\n')

    def test_unreviewed_base_or_shared_constraints_are_rejected(self):
        shared = 'torch==2.13.0\nnvidia-nccl-cu13==2.29.7\n'
        changed = dict(EXPECTED_CORE, torch='2.14.0')
        with self.assertRaisesRegex(RuntimeError, 'core versions changed'):
            cache_constraints(shared, changed)
        with self.assertRaisesRegex(RuntimeError, 'Unexpected shared constraint'):
            cache_constraints(shared + 'torch==2.13.0\n', dict(EXPECTED_CORE))
