"""The primary score counts correct turns, independent of verbosity and pauses."""
import json
import copy
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone

from summarize_efficiency import score, qualify


class ScoreTests(unittest.TestCase):
    def test_qualification_checks_launch_context_and_restore_evidence(self):
        protocol={'requestSeed':0,'agentTurns':12,
            'fixed':{'lmcacheL1GiB':8,'gpuKvGiB':8,'agentContextTarget':131000},
            'constraints':{'windowsGuardGiB':4,'windowsTargetGiB':6},
            'profiles':[{'batch':2048,'mtp':True,'concurrencies':[1],'twoNear262K':True}]}
        run={'directory':'fixture','status':'complete','config':{
            'requestSeed':0,'agentTurns':12,'prefillBatchTokens':2048,'disableMtp':False,
            'lmcacheL1GiB':8,'parallelSessions':2,'parallelContextTokens':261000,
            'modelArgs':['--max-num-batched-tokens','2048','--max-model-len','262144',
                '--max-num-seqs','16','--kv-cache-memory-bytes','8589934592',
                '--kv-cache-dtype','fp8_e4m3','--mamba-ssm-cache-dtype','bfloat16']},
            'image':{'id':'sha256:'+'a'*64},'powerStates':['Online'],'powerSamples':5,
            'featuresPassed':True,'allWindowsMinimumGiB':9,
            'memory':{'gpuReportedCapacityGiB':88,'lowestWindowsSample':{'availableGiB':9}},
            'agents':[{'concurrency':1,'complete':True,'allCorrect':True,
                'historyPromptTokens':{'0':list(range(131000,131012))},
                'metrics':{'draftTokens':12,'preemptions':0,'prefetchFailureChunks':0},
                'restore':[{'turn':6,'metrics':{'loadedChunks':1}}]}],
            'parallel':[{'stage':stage,'allCorrect':True,'allResponsesCorrect':True,
                'requestCount':2,'promptTokens':[260988,260988],
                'metrics':{'externalHitTokens':520192,'loadedChunks':256}}
                for stage in ('cold','gpu-warm','gpu-reset')]}
        self.assertEqual(qualify([run],protocol),([],[]))
        invalid=copy.deepcopy(run)
        invalid['config']['modelArgs'][3]='32768'
        invalid['parallel'][2]['promptTokens']=[32000,32000]
        invalid['parallel'][2]['metrics']['externalHitTokens']=258048
        invalid['agents'][0]['historyPromptTokens']['0']=[131000]*12
        invalid['agents'][0]['restore'][0]['turn']=7
        invalid['allWindowsMinimumGiB']=3.9
        errors,_=qualify([invalid],protocol)
        for fragment in ('launch argument','direct response','two full external',
                         'growing histories','required turn','below guard'):
            self.assertTrue(any(fragment in error for error in errors),errors)
        # Correct bounded fallback remains eligible, with its measured cost.
        pressure=copy.deepcopy(run)
        pressure['agents'][0]['metrics'].update(preemptions=2,prefetchFailureChunks=3)
        errors,warnings=qualify([pressure],protocol)
        self.assertEqual(errors,[])
        self.assertEqual(len(warnings),2)
        reference=copy.deepcopy(run)
        reference['featuresPassed']=False
        reference['config'].update(collectRejectedReference=True,prefillBatchTokens=8192)
        reference['config']['modelArgs'][1]='8192'
        reference['referenceWrapperVerified']=True
        reference['referenceFeatureRejection']={'qualified':False,'error':'Feature check failed: vision_ocr'}
        reference_protocol=copy.deepcopy(protocol)
        reference_protocol['profiles'][0].update(name='batch8192-mtp',batch=8192)
        errors,_=qualify([reference],reference_protocol)
        self.assertEqual(errors,[])
        self.assertFalse(reference['qualified'])
        reference['referenceWrapperVerified']=False
        errors,_=qualify([reference],reference_protocol)
        self.assertTrue(any('feature checks incomplete' in error for error in errors))

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
