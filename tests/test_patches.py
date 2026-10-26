"""Guard failures must be explicit and must not write invalid source."""
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

RUNTIME = Path(__file__).resolve().parents[1] / 'runtime' / 'lmcache'
sys.path.insert(0, str(RUNTIME))
from n1x_patch import Patch


class PatchGuardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'target.py'

    def target(self, text):
        self.path.write_text(text, encoding='utf-8')
        return Patch(self.path, 'test-patch')

    def test_missing_and_duplicate_anchors_leave_file_unchanged(self):
        for text, count in [('other = 1\n', 0), ('value = 1\nvalue = 1\n', 2)]:
            with self.subTest(count=count):
                source = self.target(text)
                with self.assertRaisesRegex(RuntimeError, f'expected 1 matches, found {count}') as error:
                    source.replace('value = 1', 'value = 2')
                self.assertIn('test-patch', str(error.exception))
                self.assertIn(str(self.path), str(error.exception))
                self.assertEqual(self.path.read_text(), text)

    def test_sections_require_unique_ordered_boundaries(self):
        for text in ('start\n', 'start\nend\nend\n', 'end\nstart\n'):
            with self.subTest(text=text):
                source = self.target(text)
                with self.assertRaisesRegex(RuntimeError, 'Unexpected patch target: test-patch:'):
                    source.section('start', 'end')

    def test_section_edit_preserves_surrounding_code(self):
        source = self.target('before = 1\nvalue = 1\nafter = 1\n')
        section = source.section('value =', 'after =')
        section.replace('value = 1', 'value = 2')
        source.replace(section.original, section.text)
        source.write()
        self.assertEqual(self.path.read_text(), 'before = 1\nvalue = 2\nafter = 1\n')

    def test_invalid_python_is_rejected_before_write(self):
        source = self.target('value = 1\n')
        source.replace('value = 1', 'value = (')
        with self.assertRaisesRegex(RuntimeError, 'invalid Python at line 1'):
            source.write()
        self.assertEqual(self.path.read_text(), 'value = 1\n')

    def test_presence_and_absence_checks_do_not_edit(self):
        source = self.target('value = 1\nvalue = 2\n')
        source.require('value', count=None)
        source.require('missing', count=0)
        with self.assertRaisesRegex(RuntimeError, 'expected 0 matches, found 2'):
            source.require('value', count=0)
        self.assertEqual(source.original, source.text)

    def test_missing_file_has_patch_context(self):
        with self.assertRaisesRegex(RuntimeError, 'Unexpected patch target: missing-file:'):
            Patch(self.path, 'missing-file')

    def test_optimization_does_not_disable_guards(self):
        self.target('value = 1\n')
        result = subprocess.run(
            [sys.executable, '-O', '-c',
             'import sys; sys.path.insert(0, sys.argv[1]); '
             'from n1x_patch import Patch; '
             'Patch(sys.argv[2], "optimized").replace("missing", "replacement")',
             str(RUNTIME), str(self.path)], capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('expected 1 matches, found 0', result.stderr)
        self.assertEqual(self.path.read_text(), 'value = 1\n')

    def test_patch_order_is_checked_before_any_write(self):
        root = Path(self.directory.name)
        wrapper = root / 'lmcache/v1/platform/devices/cuda/ipc_wrapper.py'
        wrapper.parent.mkdir(parents=True)
        for script, source in (
            ('patch_segmented.py', 'class VmmCudaIPCWrapper: pass\n'),
            ('patch_vmm.py', 'from n1x_segmented import initialize_wrapper\n'),
        ):
            with self.subTest(script=script):
                wrapper.write_text(source, encoding='utf-8')
                with patch('site.getsitepackages', return_value=[str(root)]):
                    with self.assertRaisesRegex(RuntimeError, 'Unexpected patch target:.*ipc_wrapper.py'):
                        runpy.run_path(str(RUNTIME / script))
                self.assertEqual(wrapper.read_text(), source)


if __name__ == '__main__':
    unittest.main()
