"""Near-limit protocol/quality fixtures; no model, network or GPU."""
import argparse
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch

from benchmarks import context_capacity_probe as probe
from benchmarks.timing import phase_timing


class FixtureClient:
    def __init__(self, empty_first=False):
        self.calls=[]
        self.empty_first=empty_first
        self.lock=threading.Lock()

    def get(self,path,body=None):
        if path=='/tokenize':
            return {'count':len(json.dumps(body['messages']))//4+len(json.dumps(body.get('tools',[])))//4+20}
        if path=='/health':
            return None
        return {'data':[{'id':'qwen/qwen38fn-best','max_model_len':4096}]}

    def generate(self,payload):
        with self.lock:
            self.calls.append(payload)
            first=len(self.calls)==1
        index=int(re.search(r'Archive (\d{2}):',payload['messages'][1]['content'])[1])
        expected=probe.sample(index,100)['expected']
        content=json.dumps(expected) if isinstance(expected,dict) else expected
        if self.empty_first and first:
            content=''
        usage=dict(prompt_tokens=probe.token_count(self,payload),completion_tokens=41,prompt_tokens_details={'cached_tokens':0})
        return dict(content=content,reasoning='fixture reasoning',stream_done=True,finish_reason='stop',
                    usage=usage,timing=phase_timing(usage,{'time_to_first_token_ms':500,'generation_time_ms':1000},2),client_ttft_s=.5)


class CapacityTests(unittest.TestCase):
    def test_tokenization_matches_chat_reasoning_alias_without_mutating_history(self):
        bodies=[]
        class Tokenizer:
            def get(self,path,body):
                bodies.append(body)
                return {'count':170 if body['messages'][0].get('reasoning') else 153}
        payload={'model':'qwen/qwen38fn-best','messages':[{'role':'assistant','reasoning_content':'reason to retain'}]}
        self.assertEqual(probe.token_count(Tokenizer(),payload),170)
        self.assertEqual(bodies[-1]['messages'][0]['reasoning'],'reason to retain')
        self.assertNotIn('reasoning_content',bodies[-1]['messages'][0])
        self.assertEqual(payload['messages'][0],{'role':'assistant','reasoning_content':'reason to retain'})
        payload['messages'][0]['reasoning']='canonical value'
        probe.token_count(Tokenizer(),payload)
        self.assertEqual(bodies[-1]['messages'][0]['reasoning'],'canonical value')
        self.assertEqual(payload['messages'][0]['reasoning_content'],'reason to retain')

    def test_calibration_reserves_output_and_preserves_tool_ids(self):
        client=FixtureClient()
        for index in range(8):
            case=probe.calibrate(client,index,4096,512)
            self.assertLessEqual(case['input_tokens']+512,4096)
            self.assertLessEqual(abs(case['input_tokens']-(4096-512-8)),8)
            self.assertEqual(case['payload']['chat_template_kwargs'],{'enable_thinking':True,'reasoning_effort':'xhigh'})
            if index>=6:
                history=case['payload']['messages']
                self.assertEqual(history[-1]['tool_call_id'],history[-2]['tool_calls'][0]['id'])
                self.assertTrue(history[-2]['reasoning_content'])

    def test_quality_requires_content_and_normal_finish(self):
        result=dict(stream_done=True,finish_reason='stop',content='{"count": 7}')
        self.assertTrue(probe.score(result,{'count':7}))
        result['finish_reason']='length'
        self.assertFalse(probe.score(result,{'count':7}))
        self.assertFalse(probe.score(dict(stream_done=True,finish_reason='stop',content='',reasoning='correct thoughts'),''))

    def test_c1_c8_share_exact_tasks_and_first_scores_are_not_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination=Path(temporary)/'probe'
            client=FixtureClient(empty_first=True)
            options=argparse.Namespace(out=destination,url='http://unused.invalid',timeout=1,profile='fixture',context_limit=4096,output_tokens=512,host_record=None,repeats=1,concurrency=[1,8],prepared_from=None)
            empty_metrics=({'vllm:num_requests_running':0,'vllm:num_requests_waiting':0,'vllm:num_preemptions_total':0},'# fixture\n')
            with patch.object(probe,'metrics',return_value=empty_metrics):
                probe.run(options,client)
            summary=json.loads((destination/'summary.json').read_text())
            self.assertTrue(summary['complete'])
            self.assertFalse(summary['quality_passed'])
            self.assertEqual([g['first_attempt_correct'] for g in summary['groups']],[7,8])
            self.assertEqual(len(client.calls),17)  # 16 first attempts + one diagnostic
            c1=[json.loads(line) for line in (destination/'c1/responses.jsonl').read_text().splitlines()]
            c8=[json.loads(line) for line in (destination/'c8/responses.jsonl').read_text().splitlines()]
            by_id={r['task_id']:r for r in c8}
            for row in c1:
                other=by_id[row['task_id']]
                self.assertEqual(row['request']['messages'],other['request']['messages'])
                self.assertNotEqual(row['request']['cache_salt'],other['request']['cache_salt'])
            diagnostic=json.loads((destination/'c1/empty-final-diagnostics.jsonl').read_text())
            self.assertTrue(diagnostic['recovered'])
            self.assertTrue(diagnostic['first_score_unchanged'])

    def test_missing_response_usage_does_not_become_fast_rate(self):
        rows=[dict(correct=False,usage=None,timing={'pp_s':None,'decode_s':None}) for _ in range(8)]
        group=probe.summarize_group(rows,8,10,{}, {},[])
        self.assertEqual(group['read_write_tks'],[None,None])
        self.assertEqual(group['aggregate_input_output_tks'],[None,None])
        self.assertIsNone(group['preemptions'])

    def test_correct_answers_with_cache_hits_do_not_validate_cold_scaling(self):
        rows=[]
        for _ in range(8):
            usage=dict(prompt_tokens=1000,completion_tokens=41,prompt_tokens_details={'cached_tokens':0})
            rows.append(dict(correct=True,rendered_input_matches=True,usage=usage,
                timing=phase_timing(usage,{'time_to_first_token_ms':500,'generation_time_ms':1000},2),
                client_ttft_s=.5))
        self.assertTrue(probe.summarize_group(rows,8,10,{}, {},[])['cold_cache_evidence_passed'])
        for details in ({'cached_tokens':64},None):
            rows[0]['usage']['prompt_tokens_details']=details
            group=probe.summarize_group(rows,8,10,{}, {},[])
            self.assertFalse(group['cold_cache_evidence_passed'])
            self.assertEqual(group['first_attempt_correct'],8)
            self.assertEqual(group['read_write_tks'],[None,None])

    def test_c6_fallback_reuses_tasks_without_rerunning_or_overwriting_c1_c8(self):
        with tempfile.TemporaryDirectory() as temporary:
            first=Path(temporary)/'first'
            fallback=Path(temporary)/'fallback'
            client=FixtureClient()
            options=argparse.Namespace(out=first,url='http://unused.invalid',timeout=1,profile='fixture',context_limit=4096,output_tokens=512,host_record=None,repeats=1,concurrency=[1,8],prepared_from=None)
            observations=({'vllm:num_requests_running':0,'vllm:num_requests_waiting':0,'vllm:num_preemptions_total':0},'# fixture\n')
            with patch.object(probe,'metrics',return_value=observations):
                probe.run(options,client)
                original=(first/'c8/responses.jsonl').read_bytes()
                options.out=fallback
                options.concurrency=[6]
                options.prepared_from=first
                probe.run(options,client)
            self.assertEqual(len(client.calls),24)  # 8 at each of C1, C8, C6
            self.assertEqual(original,(first/'c8/responses.jsonl').read_bytes())
            self.assertFalse((fallback/'c1').exists())
            self.assertEqual(json.loads((first/'prepared-requests.json').read_text()),json.loads((fallback/'prepared-requests.json').read_text()))


if __name__=='__main__':
    unittest.main()
