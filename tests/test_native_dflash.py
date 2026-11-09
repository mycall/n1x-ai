"""The capture adapter must expose completed HC states without changing the target."""
import importlib.util
from pathlib import Path
import types
import unittest

try:
    import torch
except ImportError:
    torch = None

path = Path(__file__).resolve().parents[1] / 'runtime/native/n1x_dflash_capture.py'
spec = importlib.util.spec_from_file_location('capture', path)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


@unittest.skipIf(torch is None, 'Native capture check needs the native PyTorch environment')
class CaptureTests(unittest.TestCase):
    def fixture(self):
        class Layer:
            def __init__(self, index):
                self.index = index
                self.mlp_hyper_connection = types.SimpleNamespace(
                    combine=lambda h, b, i: h + b * i)

            def forward(self, hidden_states, prev_block_output, prev_injection, positions, **kw):
                if prev_block_output is not None:
                    hidden_states = hidden_states + prev_block_output * prev_injection
                return hidden_states, torch.full_like(hidden_states, self.index + 1), 2

        class Model:
            def __init__(self):
                self.layers = [Layer(i) for i in range(3)]
                self.config = types.SimpleNamespace(hc_count=4)
                self.use_hc_sequence_parallel = False

            def forward(self, x):
                b = i = None
                for layer in self.layers:
                    x, b, i = layer.forward(x, b, i, None)
                return x + b * i

        class Causal:
            def __init__(self):
                self.model = Model()

        class Conditional:
            def __init__(self):
                self.language_model = Causal()

        module = types.SimpleNamespace(Qwen4ExpModel=Model, Qwen4ExpDecoderLayer=Layer,
            Qwen4ExpForCausalLM=Causal, Qwen4ExpForConditionalGeneration=Conditional,
            torch=torch, __name__='fixture')
        return module, Conditional()

    def test_completed_states_and_unchanged_target(self):
        module, target = self.fixture()
        model = target.language_model.model
        x = torch.arange(16, dtype=torch.float32).reshape(2, 8)
        expected = model.forward(x)
        capture.apply(module)
        target.set_aux_hidden_state_layers((1, 3))
        actual, states = model.forward(x)
        torch.testing.assert_close(actual, expected)
        self.assertEqual(len(states), 2)
        torch.testing.assert_close(states[0], (x + 2).reshape(2, 4, 2).mean(1))
        torch.testing.assert_close(states[1], (x + 12).reshape(2, 4, 2).mean(1))
        self.assertTrue(all(getattr(l, '_dflash_sink', None) is None for l in model.layers))
        before = module.Qwen4ExpModel.forward
        capture.apply(module)
        self.assertIs(before, module.Qwen4ExpModel.forward)

    def test_unconfigured_target_and_unsupported_parallelism(self):
        module, target = self.fixture()
        model = target.language_model.model
        x = torch.zeros(1, 8)
        expected = model.forward(x)
        capture.apply(module)
        torch.testing.assert_close(model.forward(x), expected)
        model.use_hc_sequence_parallel = True
        with self.assertRaisesRegex(RuntimeError, 'sequence parallelism'):
            target.set_aux_hidden_state_layers((1,))


if __name__ == '__main__':
    unittest.main()
