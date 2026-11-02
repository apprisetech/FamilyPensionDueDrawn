import unittest
from pension_tool.death_review import reconcile,signature_key,PREFIX
from pension_tool.extract import parse_text,merge_candidates
from test_tool import case,rates
from pension_tool.engine import calculate,Payment,D,dt

class DeathReviewTests(unittest.TestCase):
    def test_matching_record_is_accepted(self):
        s=reconcile('2026-09-03',[('2026-09-02','Form14.pdf')],'2026-09-02')
        self.assertTrue(s['accepted']);self.assertEqual(s['expected'],'2026-09-02');self.assertFalse(s['notes'])
    def test_mismatch_needs_review(self):
        s=reconcile('2026-09-03',[('2026-09-01','profile.txt')])
        self.assertFalse(s['accepted']);self.assertEqual(s['status'],'mismatch');self.assertIn('2026-09-01 [profile.txt]',s['notes'][0]);self.assertIn('2026-09-02',s['notes'][0])
    def test_missing_record_never_automatically_proves_expected_date(self):
        s=reconcile('2026-09-03',[],'2026-09-02');self.assertFalse(s['accepted']);self.assertEqual(s['status'],'missing_record')
    def test_conflicting_sources_even_if_one_matches(self):
        s=reconcile('2026-09-03',[('2026-09-02','Form14.pdf'),('2026-09-01','profile.txt')],'2026-09-02')
        self.assertFalse(s['accepted']);self.assertEqual(s['status'],'conflict');self.assertIn('Form14.pdf',s['notes'][0]);self.assertIn('profile.txt',s['notes'][0])
    def test_two_matching_documents(self):
        s=reconcile('2026-09-03',[('2026-09-02','one.pdf'),('2026-09-02','two.pdf')]);self.assertTrue(s['accepted'])
    def test_selected_date_cannot_silently_override_matching_sources(self):
        s=reconcile('2026-09-03',[('2026-09-02','Form14.pdf')],'2026-09-01');self.assertFalse(s['accepted']);self.assertTrue(s['notes'])
    def test_month_year_and_leap_boundaries(self):
        for effective,expected in [('2026-01-01','2025-12-31'),('2024-03-01','2024-02-29')]:self.assertEqual(reconcile(effective,[])['expected'],expected)
    def test_confirmation_invalidates_after_any_evidence_change(self):
        a=signature_key(reconcile('2026-09-03',[('2026-09-01','source')],'2026-09-02'))
        variants=[('2026-09-04',[('2026-09-01','source')],'2026-09-02'),('2026-09-03',[('2026-09-01','source')],'2026-09-01'),('2026-09-03',[('2026-09-02','source')],'2026-09-02')]
        for args in variants:self.assertNotEqual(a,signature_key(reconcile(*args)))
    def test_conflicting_dates_inside_one_pdf_are_preserved(self):
        fields,_=parse_text('Date of Death: 02/09/2026\nDate of Death: 01/09/2026','original')
        values,sources,_=merge_candidates([('profile.pdf',fields)]);self.assertNotIn('death',values);self.assertEqual(len(sources['death']),2)
        self.assertEqual(reconcile('2026-09-03',sources['death'])['status'],'conflict')
    def test_switch_uses_conversion_effective_date_not_recorded_death(self):
        r=calculate(case(death='2026-09-01'),rates(),[Payment(dt('2026-09-23'),'MONTHLY BILL',D(32660))],'2026-09-30')
        self.assertEqual(r['rows'][0]['end'],dt('2026-09-02'));self.assertEqual(r['difference'],4041)

if __name__=='__main__':unittest.main()
