import unittest
from unittest.mock import Mock, patch
from collect_rejected_reference import RejectedReferenceSuite


class ReferenceTests(unittest.TestCase):
    def test_records_ocr_rejection_without_claiming_qualification(self):
        suite=object.__new__(RejectedReferenceSuite)
        suite.save=Mock()
        with patch('run_suite.Suite.features',side_effect=RuntimeError('Feature check failed: vision_ocr')):
            suite.features()
        self.assertIs(suite.save.call_args.args[1]['qualified'],False)

    def test_does_not_catch_memory_or_other_feature_failures(self):
        suite=object.__new__(RejectedReferenceSuite)
        for message in ('Windows headroom below 4 GiB','Feature check failed: tool_call'):
            with patch('run_suite.Suite.features',side_effect=RuntimeError(message)):
                with self.assertRaises(RuntimeError):
                    suite.features()


if __name__=='__main__':
    unittest.main()
