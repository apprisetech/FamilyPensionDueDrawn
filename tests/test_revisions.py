import unittest

from pension_tool.revisions import pay_revision


class RevisionFormatTests(unittest.TestCase):
    def authority(self, effective, header='Previous Amount Revised Amount Difference'):
        return ('Authority for Pay related Correction/Revision.\n'
                f'{effective}\n{header}\nRevised Pension 14870 15315 445\n')

    def test_effective_date_punctuation_and_wrapping(self):
        for label in ('w.e.f.', 'w.e.f', 'W.E.F', 'w. e. f.'):
            for separator in (' ', '\n'):
                with self.subTest(label=label, separator=separator):
                    result = pay_revision(self.authority(f'{label}{separator}23/09/2025'))
                    self.assertEqual(result, {'effective': '2025-09-23', 'basic': '15315'})

    def test_wrapped_previous_revised_headers(self):
        result = pay_revision(self.authority('w.e.f 23/09/2025',
            'Previous    Revised    Difference\nAmount    Amount    Amount'))
        self.assertEqual(result['basic'], '15315')
        reverse = ('Authority for Pay related Correction/Revision.\nw.e.f. 23/09/2025\n'
                   'Revised Previous Difference\nAmount Amount Amount\nRevised Pension 15315 14870 445')
        self.assertEqual(pay_revision(reverse)['basic'], '15315')

    def test_missing_or_conflicting_effective_date_requires_review(self):
        for effective in ('DATED: 23/09/2025', 'w.e.f 23/09/2025 and w.e.f. 01/10/2025'):
            with self.subTest(effective=effective):
                with self.assertRaisesRegex(ValueError, 'one verified effective date'):
                    pay_revision(self.authority(effective))


if __name__ == '__main__':
    unittest.main()
