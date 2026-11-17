"""Averages retain failed-but-completed work and do not invent missing samples."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks'))
import recipe_repeats


class RepeatReportTests(unittest.TestCase):
    def test_failed_completed_work_counts_but_missing_work_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            plan={'runs':[]}
            rows={}
            for pair in range(1,4):
                for batch in (4096,8192):
                    name=f'{pair}-{batch}'
                    plan['runs'].append(dict(name=name,pair=pair,batch=batch,seed=44+pair))
                    (folder/name).mkdir()
                    (folder/name/'status.json').write_text('{}')
                    row=dict(name=name,status=dict(stage='finished',success=batch==4096))
                    if pair==1 and batch==8192:
                        row['speed']=[dict(concurrency=1,depth=4096,recorded=1,valid=1,
                                           read_tokens_s=999,write_tokens_s=999)]
                    if not (pair==3 and batch==8192):
                        row['near_full']=[dict(concurrency=4,elapsed_s=90+10*pair-(10 if batch==8192 else 0),
                            correct_tasks=11 if batch==8192 else 12,planned_tasks=12,
                            cache_evidence={'tool-continuation':dict(requests=12,requests_with_cached_tokens=12)})]
                    rows[name]=row
            output=folder/'report.json'
            with patch.object(recipe_repeats,'summarize',side_effect=lambda p:rows[p.name]):
                recipe_repeats.report(folder,plan,output)
            result=json.loads(output.read_text())
            four=result['groups']['4096']; eight=result['groups']['8192']
            self.assertEqual(four['long_elapsed_s']['mean'],110)
            self.assertEqual(four['long_elapsed_s']['sample_sd'],10)
            self.assertEqual(eight['long_elapsed_s']['mean'],95)
            self.assertEqual(eight['long_elapsed_s']['n'],2)
            self.assertEqual(eight['long_correct'],22)
            self.assertEqual(eight['long_planned'],24)
            self.assertEqual(len(result['paired_results']),2)
            self.assertEqual(eight['restore_elapsed_s']['n'],0)
            self.assertIsNone(eight['restore_elapsed_s']['mean'])
            self.assertIsNone(eight['speed']['c1-d4096']['read_tokens_s']['mean'])

    def test_single_sample_does_not_claim_variance(self):
        self.assertIsNone(recipe_repeats.stats([3])['sample_sd'])


if __name__=='__main__':
    unittest.main()
