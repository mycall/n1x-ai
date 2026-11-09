import copy
import unittest
from unittest.mock import Mock

from benchmarks.empty_final import required_content_result


def choice(content, finish='stop', **extra):
    return dict(message=dict(content=content, **extra), finish_reason=finish)


class EmptyFinalTests(unittest.TestCase):
    def test_retry_preserves_tool_history_and_original_failed_score(self):
        history = [dict(role='assistant', reasoning='Look up the item.', tool_calls=[
            dict(id='call-1', type='function', function=dict(name='lookup', arguments='{}'))]),
            dict(role='tool', tool_call_id='call-1', content='23')]
        original = copy.deepcopy(history)
        chat = Mock(side_effect=[choice('', reasoning='The answer is 23.'), choice('23')])
        result = required_content_result(chat, history, 'stable-salt',
            lambda c: c['finish_reason']=='stop' and c['message']['content']=='23',
            max_tokens=1024, tool_choice='none')
        self.assertFalse(result['correct'])
        self.assertTrue(result['retry_correct'])
        self.assertEqual(chat.call_count, 2)
        self.assertEqual(chat.call_args_list[0], chat.call_args_list[1])
        self.assertEqual(history, original)

    def test_persistent_empty_is_retried_only_once(self):
        chat = Mock(return_value=choice(''))
        result = required_content_result(chat, [], 'salt', lambda c: bool(c['message']['content']))
        self.assertEqual(chat.call_count, 2)
        self.assertFalse(result['correct'])
        self.assertFalse(result['retry_correct'])
        self.assertTrue(result['retry_empty_final'])

    def test_nonempty_wrong_answer_and_tool_calls_are_not_retried(self):
        for answer in (choice('wrong'), choice(None, 'tool_calls', tool_calls=[dict(id='call-1')])):
            with self.subTest(answer=answer):
                chat = Mock(return_value=answer)
                result = required_content_result(chat, [], 'salt', lambda c: False)
                self.assertEqual(chat.call_count, 1)
                self.assertFalse(result['retried_empty_final'])
                self.assertIsNone(result['retry_correct'])
