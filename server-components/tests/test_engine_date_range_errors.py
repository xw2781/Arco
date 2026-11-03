from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
for source in (REPO_ROOT / 'server-components' / 'src', REPO_ROOT / 'python-api' / 'src', REPO_ROOT / 'frontend'):
    sys.path.insert(0, str(source))

import pandas as pd

from arcrho_engine import data_processing as engine
from app_server.services import engine_calculation_service


class EngineDateRangeErrorTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({'origin': [201702], 'development': [202609], 'paid': [123.0]})
        self.settings = {
            'origin_start': 201701, 'origin_end': 202612,
            'dev_end': 202608, 'date_granularity': 'monthly',
        }
        self.args = {
            'Function': 'ArcRhoTri', 'ProjectName': 'Test',
            'OriginLength': 12, 'DevelopmentLength': 12,
        }
        patches = [
            patch.object(engine, '_get_dataset_info', side_effect=lambda _: (
                self.frame, ['origin', 'development'], ['paid'], {}, {}, [],
                'paid', 'Triangle', self.settings['dev_end'],
            )),
            patch.object(engine, '_load_project_settings', return_value=self.settings),
            patch.object(engine, 'build_weighted_source_frame', side_effect=lambda *a, **kw: self.frame.copy()),
            patch.dict(engine.PROJECT_CONFIG, {'Test': {'Dataset Types': []}}),
            patch.object(engine, 'DLOOKUP', return_value='Triangle'),
            patch.object(engine, 'eval_triangle_formula', side_effect=lambda triangles, _: triangles['paid']),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        export = patch.object(engine, '_export_dataframe')
        self.export = export.start()
        self.addCleanup(export.stop)

    def test_cutoff_mismatch_names_both_months_and_correction(self):
        with self.assertRaises(engine.DataProcessingConfigurationError) as caught:
            engine.UDF_ADASTri(self.args)
        message = str(caught.exception)
        self.assertIn('through September 2026', message)
        self.assertIn('Development End Date is August 2026', message)
        self.assertIn('Project Settings > General Settings', message)
        self.assertIn('then refresh the data', message)
        self.assertNotIn('min()', message)
        self.export.assert_not_called()

    def test_corrected_cutoff_preserves_values(self):
        self.settings['dev_end'] = 202609
        engine.UDF_ADASTri(self.args)
        result = self.export.call_args.args[0]
        self.assertEqual(result.loc[2017, 117], 123.0)

    def test_rows_outside_the_origin_range_are_left_out(self):
        # A start-of-year date change leaves the year that dropped out in the
        # source table; its rows must not stop the triangle from building.
        self.settings.update(origin_start=201801, origin_end=202612, dev_end=202609)
        self.frame = pd.DataFrame({
            'origin': [201712, 201802, 202701],
            'development': [202609, 202609, 202609],
            'paid': [5.0, 123.0, 7.0],
        })
        engine.UDF_ADASTri(self.args)
        result = self.export.call_args.args[0]
        self.assertEqual(list(result.index), list(range(2018, 2027)))
        self.assertEqual(result.loc[2018, 105], 123.0)
        self.assertEqual(float(result.sum().sum()), 123.0)

    def test_development_ages_reach_the_development_end(self):
        def labels(start, end, dev_end, dev_len=12):
            return engine._development_age_labels(
                {'origin_start': start, 'origin_end': end, 'dev_end': dev_end, 'date_granularity': 'monthly'},
                dev_len,
            )

        # Whole years are unchanged.
        self.assertEqual(labels(201701, 202612, 202612), list(range(12, 121, 12)))
        self.assertEqual(labels(201701, 202612, 202605), list(range(5, 114, 12)))
        # A January project: ten annual origins need ten ages, up to 109 months.
        self.assertEqual(labels(201801, 202701, 202701), list(range(1, 110, 12)))
        self.assertEqual(labels(201801, 202701, 202701, 3)[-1], 109)
        # Development End after Origin End still reaches the oldest origin's age.
        self.assertEqual(labels(201801, 202612, 202701)[-1], 109)

    def test_empty_development_axis_gives_date_settings_guidance(self):
        self.settings.update(origin_end=201703, dev_end=201703)
        self.frame['development'] = 201703
        # A three-month origin span now has its one development age (3 months);
        # the rounding that used to leave it with none no longer applies.
        self.assertEqual(engine._development_age_labels(self.settings, 12), [3])
        with patch.object(engine, '_development_age_labels', return_value=[]):
            with self.assertRaises(engine.DataProcessingConfigurationError) as caught:
                engine.UDF_ADASTri(self.args)
        self.assertIn('Origin Start Date, Origin End Date, and Development End Date', str(caught.exception))
        self.export.assert_not_called()

    def test_import_exchange_passes_actionable_message_to_ui(self):
        pairs = [
            ['Function', 'ArcRhoTri'], ['ProjectName', 'Test'],
            ['Path', 'Class'], ['DatasetName', 'Paid'],
            ['OriginLength', '12'], ['DevelopmentLength', '12'],
        ]
        with patch.object(engine_calculation_service, '_in_process_calculator',
                          side_effect=lambda _: engine.UDF_ADASTri(self.args)):
            outcome = engine_calculation_service.calculate_in_process(pairs, 'unused.csv')
        self.assertFalse(outcome['ok'])
        self.assertIn('September 2026', outcome['message'])
        self.assertIn('Development End Date is August 2026', outcome['message'])
        self.assertNotIn('min()', outcome['message'])


if __name__ == '__main__':
    unittest.main()
