from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for source in (REPO_ROOT / 'server-components' / 'src', REPO_ROOT / 'python-api' / 'src', REPO_ROOT / 'frontend'):
    sys.path.insert(0, str(source))

import pandas as pd

from arcrho_engine import data_processing as engine


def _tri(value):
    return pd.DataFrame([[value, value]], index=[2025], columns=[12, 24], dtype=float)


class EngineFormulaNameTests(unittest.TestCase):
    def test_source_column_with_spaces_evaluates(self):
        triangles = {
            'Earned Premium': _tri(100.0),
            'Remaining Budget Premium': _tri(20.0),
            'Earned Exposure': _tri(4.0),
        }
        result = engine.eval_triangle_formula(
            triangles, '(Earned Premium + Remaining Budget Premium) / Earned Exposure * 1000')
        self.assertEqual(result.iloc[0, 0], 30000.0)

    def test_single_spaced_column_evaluates(self):
        result = engine.eval_triangle_formula({'Earned Exposure': _tri(4.0)}, 'Earned Exposure')
        self.assertEqual(result.iloc[0, 1], 4.0)

    def test_name_inside_a_longer_name_is_not_split(self):
        triangles = {'reported': _tri(10.0), 'reported_ex_50k': _tri(3.0), 'CWOP': _tri(2.0)}
        result = engine.eval_triangle_formula(triangles, '(reported - CWOP) / reported_ex_50k')
        self.assertAlmostEqual(result.iloc[0, 0], 8.0 / 3.0)

    def test_quoted_name_evaluates(self):
        result = engine.eval_triangle_formula(
            {'Earned Premium': _tri(5.0), 'gross_paid': _tri(1.0)}, 'gross_paid / "Earned Premium"')
        self.assertEqual(result.iloc[0, 0], 0.2)


if __name__ == '__main__':
    unittest.main()
