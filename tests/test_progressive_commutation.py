import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from openpyxl import load_workbook
from pension_tool.commutations import progressive_parts, remaining, original_rates
from pension_tool.input_review import resolve_timelines
from pension_tool.engine import D, calculate
from pension_tool.exporter import export
from test_tool import case, rates


class ProgressiveCommutationTests(unittest.TestCase):
    def test_equal_progressive_totals_leave_zero_current_deduction(self):
        parts=progressive_parts([('5948','11/01/2022'),('5948','26/03/2030')])
        self.assertEqual([D(p['amount']) for p in parts],[D(5948),D(0)])
        self.assertEqual(remaining(parts,date(2026,8,14)),0)
        self.assertEqual(remaining(parts,date(2022,1,10)),5948)
        c=case(commuted='0',commutation_restore='',commutation_parts=parts,
               pay_revisions=[dict(effective='2025-09-23',basic='15315',commuted='5948')])
        result=calculate(c,rates(),[],'2026-09-30')
        self.assertTrue(all(row['comm']==0 for row in result['rows']))
        with tempfile.TemporaryDirectory() as folder:
            path=export(c,result,folder)
            wb=load_workbook(path)
            self.assertEqual(wb['Sheet3']['D15'].value,15315)
            self.assertEqual(wb['Sheet3']['D18'].value,0)
            self.assertIn('Commutation portions',wb.sheetnames)

    def test_restorations_split_the_correct_days_without_summing_progressive_totals(self):
        parts=progressive_parts([('2880','28/05/2023'),('6354','28/04/2025'),('6828','15/09/2026')])
        self.assertEqual([D(p['amount']) for p in parts],[D(2880),D(3474),D(474)])
        c=case(death='2026-09-20',effective='2026-09-21',commuted='0',commutation_restore='',commutation_parts=parts)
        result=calculate(c,rates(),[],'2026-09-30')
        self.assertEqual([row['start'].day for row in result['rows']],[1,15,21])
        self.assertEqual(result['rows'][0]['comm'],D(474)*D(14)/30)
        self.assertEqual(result['rows'][1]['comm'],0)

    def test_manual_basic_and_commutation_supersede_automatic_history(self):
        c=case(basic='16000',commuted='100',commutation_restore='2030-01-01',
               pay_revisions=[dict(effective='2025-01-01',basic='15315',commuted='5948')],
               commutation_parts=progressive_parts([('5948','2022-01-11')]),
               manual_overrides=dict(basic={'selected':'16000'},commuted={'selected':'100'}))
        self.assertEqual(original_rates(c,date(2026,9,1)),(D(16000),D(100)))
        result=calculate(c,rates(),[],'2026-09-30')
        with tempfile.TemporaryDirectory() as folder:
            wb=load_workbook(export(c,result,folder))
            self.assertEqual(wb['Sheet3']['D15'].value,16000)
            self.assertEqual(wb['Sheet3']['D18'].value,100)
            self.assertIn('Manual overrides',wb.sheetnames)

    def test_blank_or_non_finite_amount_has_field_message(self):
        for value in ('','wrong','NaN','Infinity'):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'Basic: enter a valid amount'):
                case(basic=value)

    def test_explained_profile_basic_is_not_a_conflict(self):
        parts=progressive_parts([('5948','2022-01-11'),('5948','2030-03-26')])
        candidates=[('original_1.pdf',{'basic':'14870'}),('migrated_fields.json',{'basic':'15315','_commutation_parts':parts})]
        data=dict(effective='2026-08-15',pay_revisions=[dict(effective='2025-09-23',basic='15315')])
        conflicts=resolve_timelines(data,{'basic':[('14870','original_1.pdf'),('15315','migrated_fields.json')]},['Conflicting basic: test'],candidates)
        self.assertEqual(data['basic'],'14870');self.assertEqual(data['commuted'],'0');self.assertEqual(conflicts,[])
        data=dict(effective='2026-08-15',pay_revisions=[dict(effective='2025-09-23',basic='16000')])
        self.assertTrue(resolve_timelines(data,{},['Conflicting basic: test'],candidates))
        self.assertNotIn('basic',data)

    def test_manual_fields_save_and_reload_without_becoming_automatic(self):
        import tkinter as tk
        from pension_tool.desktop import App
        root=tk.Tk();root.withdraw()
        callback_errors=[]
        root.report_callback_exception=lambda *error:callback_errors.append(error)
        try:
            app=App(root)
            app.loading_fields=True
            for key,value in case().__dict__.items():
                if key in app.vars:app.vars[key].set(str(value) if value is not None else '')
            app.bound_ppo=app.vars['ppo'].get();app.automatic_values={k:v.get() for k,v in app.vars.items()};app.loading_fields=False
            app.vars['basic'].set('16000');app.vars['commutation_restore'].set('2030-01-01')
            with tempfile.TemporaryDirectory() as folder:
                app.case_folder=lambda *args:Path(folder)
                app.save_case()
                path=Path(folder)/'reviewed_case.json'
                self.assertTrue(path.exists())
                saved=json.loads(path.read_text())
                self.assertEqual(saved['case']['manual_overrides']['basic']['automatic'],'10825')
                with patch('pension_tool.desktop.filedialog.askopenfilename',return_value=str(path)):
                    app.load_case()
                self.assertEqual(app.data()['manual_overrides']['basic']['selected'],'16000')
                self.assertEqual(app.vars['commutation_restore'].get(),'2030-01-01')
                app.vars['effective'].set('2026-')
                self.assertEqual(callback_errors,[])
        finally:root.destroy()
