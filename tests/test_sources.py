import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from pension_tool.sources import tables_to_fields, gc_fields, clean_name
from pension_tool.extract import parse_text, merge_candidates
from pension_tool.diagnostics import Recorder, safe_url

PPO='123456789012345'


class StructuredSources(unittest.TestCase):
    def test_honorific_removal_preserves_names_starting_with_mr(self):
        self.assertEqual(clean_name('Mr. MRINAL  SEN'),'MRINAL SEN')

    def test_equal_monetary_values_with_different_precision_are_not_conflicts(self):
        values,sources,notes=merge_candidates([('a',{'commuted':'6168'}),('b',{'commuted':'6168.00'})])
        self.assertEqual(values['commuted'],'6168');self.assertEqual(len(sources['commuted']),2);self.assertEqual(notes,[])

    def test_conflicting_categories_within_profile_are_rejected(self):
        tables=[{'rows':[['S. No.','Personal Details'],['1','PPONumber',PPO],['2','Pensioner Name','TEST'],['3','Date Of Birth','01/01/1950'],['4','Pay Commission','CDA']]},
                {'rows':[['S. No.','Pension Details'],['1','Pay Commission','IDA']]}]
        with self.assertRaisesRegex(ValueError,'Conflicting explicit'):tables_to_fields(tables,'profile',PPO)

    def test_form14_claimant_not_guardian_or_spouse(self):
        tables=[{'rows':[['1.(i) Name of the Government servant','Late. TEST ORIGINAL'],['Date of death of the Government Servant','10/01/2022']]},
                {'rows':[['Name','Date of Birth','Relationship with the deceased Government Servant','Postal Address'],['TEST CLAIMANT','15/09/2005','Son','private address']]},
                {'rows':[['Name','Date of Birth','Relationship with the minor','Relationship with the deceased'],['GUARDIAN','01/01/1960','Guardian','Wife']]}]
        f,_=tables_to_fields(tables,'form14',PPO)
        self.assertEqual((f['pensioner'],f['death'],f['family_dob'],f['relationship']),('TEST ORIGINAL','2022-01-10','2005-09-15','Son'))

    def test_migrated_repeated_dob_labels_are_section_scoped(self):
        tables=[{'rows':[['S. No.','Personal Details'],['1','PPONumber',PPO],['2','Pensioner Name','TEST ORIGINAL'],['3','Date Of Birth','04/02/1952'],['4','Date Of Death(only in case of Family Pension)','31/01/2026'],['5','Pay Commission','CDA']]},
                {'rows':[['S. No.','Family Details'],['1','Name','TEST FAMILY'],['2','Date Of Birth','01/01/1957']]},
                {'rows':[['S. No.','Bank Account Details'],['1','IFSC','WRONG000001']]},
                {'rows':[['S. No.','Pension Details'],['1','Basic Pension','16275']]},
                {'rows':[['S No.','Commutations'],['','Last Commuted Amount','Last Date of Restoration'],['1','6168','01/03/2027'],['2','6168','04/02/2019']]}]
        f,notes=tables_to_fields(tables,'profile',PPO)
        self.assertEqual((f['pensioner_dob'],f['family_dob'],f['category']),('1952-02-04','1957-01-01','CDA'))
        self.assertNotIn('ifsc',f);self.assertNotIn('commutation_restore',f);self.assertTrue(notes)

    def test_wrong_profile_ppo_rejected(self):
        with self.assertRaisesRegex(ValueError,'PPO does not match'):
            tables_to_fields([{'rows':[['S. No.','Personal Details'],['1','PPONumber','999999999999999']]}],'profile',PPO)

    def test_gc_header_mapping_includes_hidden_columns(self):
        f=gc_fields(['PensionerId','Family Id','PPO No.','Pension Type','Commutation Amount','Date Of Restoration'],[['7','',PPO,'IDA','401179','09/10/2026']],PPO)
        self.assertEqual(f['category'],'IDA');self.assertEqual(f['commutation_restore'],'2026-10-09');self.assertNotIn('commuted',f)

    def test_report_restoration_discrepancy_is_retained_for_review(self):
        f=gc_fields(['PPO No.','Date Of Restoration','Commutation Payment Date'],[[PPO,'09/10/2026','22/05/2020']],PPO)
        self.assertEqual(f['commutation_restore'],'2026-10-09');self.assertIn('Verify the authority',f['_notes'][0])

    def test_boilerplate_ida_is_not_category_evidence(self):
        fields,_=parse_text('Emoluments: Basic + IDA','original')
        self.assertNotIn('category',fields)

    def test_dated_commutation_revision_supersedes_original_zero(self):
        text=f'''PPO NUMBER: {PPO}
DATED: 11/03/2022
Sanction Order: Revision on account of commutation.
Gross Pension 10825 10825
Reduced Pension after commutation 10825 6495'''
        f,_=parse_text(text,'original')
        data,sources,notes=merge_candidates([('original.pdf',{'commuted':'0'}),('revision.pdf',f)])
        self.assertEqual(data['commuted'],'4330');self.assertEqual(len(sources['commuted']),2);self.assertTrue(notes)

    def test_same_date_conflicting_revisions_not_silently_chosen(self):
        c={'_issued_date':'2022-03-11','_supersedes':['commuted']}
        data,_,notes=merge_candidates([('a',dict(c,commuted='10')),('b',dict(c,commuted='20'))])
        self.assertNotIn('commuted',data);self.assertTrue(notes)


class DiagnosticTests(unittest.TestCase):
    def test_failed_action_preserves_history_progress_and_pack(self):
        with TemporaryDirectory() as folder:
            r=Recorder(folder);r.checkpoint(case={'ppo':PPO},payment_query_complete=False)
            with self.assertRaisesRegex(ValueError,'source missing'):
                with r.step('read_source','Correct source'):
                    raise ValueError('source missing')
            r.finish(ValueError('source missing'))
            rows=[json.loads(x) for x in (r.folder/'steps.jsonl').read_text().splitlines()]
            self.assertTrue(any(x.get('expected')=='Correct source' and x.get('actual')=='source missing' for x in rows))
            self.assertEqual(json.loads((r.folder/'progress.json').read_text())['payment_query_complete'],False)
            self.assertTrue((r.folder/'diagnostics.zip').exists())

    def test_every_run_has_distinct_folder(self):
        with TemporaryDirectory() as folder:self.assertNotEqual(Recorder(folder).folder,Recorder(folder).folder)

    def test_url_credentials_and_query_not_recorded(self):
        self.assertEqual(safe_url('https://name:password@dotpension.gov.in/report?token=secret#otp'),'https://dotpension.gov.in/report')
