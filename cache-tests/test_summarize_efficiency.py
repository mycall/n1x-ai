"""The primary score counts correct turns, independent of verbosity and pauses."""
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone

from summarize_efficiency import score


class ScoreTests(unittest.TestCase):
    def test_warm_score_excludes_cold_restore_and_metrics_pause(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def save(name,data):
                (root/name).write_text(json.dumps(data),encoding='utf-8')
            turns=[]
            for turn in range(12):
                elapsed=100 if turn in (0,6) else 4
                sessions=[]
                for session in range(3):
                    sessions.append({'session':session,'correct':not (turn==1 and session==0),
                        'toolSeconds':1,'answerSeconds':elapsed-1})
                    for kind,end,duration in [('tool',1,1),('answer',elapsed,elapsed-1)]:
                        save(f'lmcache-agents-c3-turn-{turn}-session-{session}-{kind}.json',{
                            'timestamp':datetime.fromtimestamp(1800000000+turn*200+end,timezone.utc).isoformat(),
                            'totalSeconds':duration,'usage':{'completion_tokens':9999}})
                metrics={'vllm:prefix_cache_hits_total':258048 if turn<6 else 0,
                         'vllm:external_prefix_cache_hits_total':4096 if turn<6 else 262144,
                         'lmcache_mp_num_chunks_loaded_total':4 if turn<6 else 130}
                turns.append({'turn':turn,'gpuReset':turn==6,'wallSeconds':elapsed+60,
                              'sessions':sessions,'metricsDelta':metrics})
            save('agent-loops-c3.json',{'status':'complete','turns':turns,'metricsDelta':{}})
            row=score(root,{'agentTurns':12,'warmCohorts':[[1,2,3,4,5],[7,8,9,10,11]]})['agents'][0]
            self.assertEqual(row['concurrency'],3)
            self.assertTrue(row['complete'])
            self.assertFalse(row['allCorrect'])
            first,second=row['cohorts']
            self.assertEqual(first['httpWallSeconds'],20)
            self.assertEqual(first['correctTurns'],14)
            self.assertAlmostEqual(first['correctTurnsPerSecond'],.7)
            self.assertAlmostEqual(second['correctTurnsPerSecond'],.75)
            self.assertEqual(second['latencyP95Seconds'],4)
            self.assertEqual(first['cachePath'],'gpu-and-external')
            self.assertEqual(second['cachePath'],'external')
            self.assertEqual(second['loadedChunks'],650)


if __name__=='__main__':
    unittest.main()
