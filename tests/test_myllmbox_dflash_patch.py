import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime.myllmbox import patch_dflash


class MyllmboxPatchTests(unittest.TestCase):
    def fixture(self, root):
        site = root / 'site'
        model = site / 'vllm/models/qwen4_exp/nvidia/model.py'
        config = site / 'vllm/model_executor/models/config.py'
        model.parent.mkdir(parents=True)
        config.parent.mkdir(parents=True)
        model.write_text('# pinned model fixture\n')
        config.write_text('if method in {\n            ' + patch_dflash.GUARD + '\n    pass\n')
        manifest = root / 'manifest.json'
        manifest.write_text(json.dumps({path.relative_to(site / 'vllm').as_posix():
                                        patch_dflash.digest(path) for path in (model, config)}))
        return site, model, config, manifest

    def test_patches_once_and_records_both_source_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            site, model, config, manifest = self.fixture(Path(directory))
            adapter = Path(__file__).resolve().parents[1] / 'runtime/native/n1x_dflash_capture.py'
            with patch.object(patch_dflash, 'EXPECTED_MODEL_SHA256', patch_dflash.digest(model)), \
                 patch.object(patch_dflash, 'ADAPTER', adapter), \
                 contextlib.redirect_stdout(io.StringIO()):
                patch_dflash.patch(site, manifest)
                saved = json.loads((site / 'n1x-myllmbox-dflash-patches.json').read_text())
                self.assertEqual(saved['adapter_sha256'], patch_dflash.digest(adapter))
                self.assertEqual(len(saved['original_sha256']), 2)
                self.assertIn('"dflash"', config.read_text())
                self.assertIn('_n1x_dflash_apply', model.read_text())
                self.assertTrue((site / adapter.name).exists())
                with self.assertRaisesRegex(RuntimeError, 'Unexpected MyLLMBox target source'):
                    patch_dflash.patch(site, manifest)

    def test_changed_guard_source_is_rejected_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            site, model, config, manifest = self.fixture(Path(directory))
            original_model = model.read_bytes()
            config.write_text(config.read_text() + '# unexpected replacement\n')
            changed_config = config.read_bytes()
            with patch.object(patch_dflash, 'EXPECTED_MODEL_SHA256', patch_dflash.digest(model)):
                with self.assertRaisesRegex(RuntimeError, 'source changed since dependency audit'):
                    patch_dflash.patch(site, manifest)
            self.assertEqual(model.read_bytes(), original_model)
            self.assertEqual(config.read_bytes(), changed_config)
            self.assertFalse((site / 'n1x_dflash_capture.py').exists())


if __name__ == '__main__':
    unittest.main()
