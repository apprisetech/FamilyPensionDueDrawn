import unittest
from datetime import date
from pension_tool.conversions import separate_conversions
from pension_tool.engine import D, Rate, calculate
from test_tool import case


class MultipleConversions(unittest.TestCase):
    def test_latest_sanction_and_prior_beneficiary_rates(self):
        previous = dict(_conversion_order=True, effective='2024-01-01',
                        family='FIRST', enhanced='9000', enhanced_until='2025-12-31',
                        normal='8000', normal_from='2026-01-01', fma_after='500')
        latest = dict(previous, family='Miss. SECOND', effective='2026-09-03', normal='6000')
        current, history = separate_conversions([
            ('new.pdf', latest), ('old.pdf', previous),
            ('profile.json', {'family': 'SECOND', 'family_dob': '1978-07-10'}),
        ])
        self.assertEqual([name for name, _ in current], ['new.pdf', 'profile.json'])
        self.assertNotIn('dob', history[0])
        self.assertEqual(history[1]['dob'], '1978-07-10')
        c = case(conversion_history=history, normal='6000', enhanced_until='2025-12-31',
                 normal_from='2026-01-01')
        rates = [Rate(date(2026,9,1), date(2026,9,30), D(0), 'IDA')]
        with self.assertRaisesRegex(ValueError, 'Verify the DOB'):
            calculate(c, rates, [], '2026-09-30')
        c.previous_family_dob = '1940-01-01'
        rows = calculate(c, rates, [], '2026-09-30')['rows']
        self.assertEqual([r['base'] for r in rows], [8000, 6000])
        self.assertEqual([r['comm'] for r in rows], [0, 0])
        self.assertAlmostEqual(float(rows[0]['fma']),500*2/30)
        self.assertEqual(rows[1]['fma'],0)
        self.assertGreater(rows[0]['quantum'], 0)
        self.assertEqual(rows[1]['quantum'], 0)
