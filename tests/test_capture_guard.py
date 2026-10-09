import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pool.capture import FormulaCapture
from pool.common import PoolError


class CaptureGuardTests(unittest.TestCase):
    def test_penryn_proof_without_sse41_is_now_rejected(self):
        capture = FormulaCapture.__new__(FormulaCapture)
        capture.brew = SimpleNamespace(host_cpu_features=lambda: {'SSE2', 'SSE3', 'SSSE3', 'CX16', 'SSE4_1'})
        evidence = {'built_on': {'cpu_family': 'penryn'}}
        for field in ('formula', 'version', 'prefix', 'cellar', 'receipt_sha256', 'recipe_sha256', 'keg_tree_sha256', 'context'):
            evidence[field] = 'fixture'
        proof = {k: v for k, v in evidence.items() if k != 'built_on'}
        proof.update(schema=1, reviewed=True, producer='fixture', compiler_flags=[],
                     required_cpu_features=['SSE2', 'SSE3', 'SSSE3', 'CX16'])
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'proof.json'; path.write_text(json.dumps(proof))
            with self.assertRaises(PoolError): capture._proof(evidence, path)


if __name__ == '__main__': unittest.main()
