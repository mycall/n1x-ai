import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'metrics_probe', Path(__file__).resolve().parents[1] / 'benchmarks/agent_cache_probe.py')
probe_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe_module)


class MetricsEncodingTests(unittest.TestCase):
    def test_non_ascii_cache_metrics_are_saved_on_a_legacy_windows_locale(self):
        raw_vllm = '# HELP requests Timed requests\nrequests 7\n'
        raw_cache = '# HELP transfers L1 \u2192 L2\ntransfers 3\n'
        original_write = Path.write_text

        def legacy_write(path, text, *args, **kwargs):
            if not args and kwargs.get('encoding') is None:
                kwargs['encoding'] = 'cp1252'
            return original_write(path, text, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            probe = probe_module.Probe(SimpleNamespace(out=folder, url='http://unused'))
            with patch.object(probe_module, 'request', side_effect=[raw_vllm, raw_cache]), \
                 patch.object(Path, 'write_text', new=legacy_write):
                counters = probe.snapshot('before')
            self.assertEqual(counters, {'requests': 7.0, 'transfers': 3.0})
            self.assertEqual((folder / 'before-vllm.prom').read_text(encoding='utf-8'), raw_vllm)
            self.assertEqual((folder / 'before-lmcache.prom').read_text(encoding='utf-8'), raw_cache)
            self.assertIn('\u2192'.encode('utf-8'), (folder / 'before-lmcache.prom').read_bytes())
