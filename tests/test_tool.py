import unittest,tempfile,sys
from pathlib import Path
from datetime import date
from decimal import Decimal
from zipfile import ZipFile
from lxml import etree as E
from openpyxl import load_workbook,Workbook
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pension_tool.engine import *
from pension_tool.extract import parse_text,merge_candidates
from pension_tool.exporter import export

def case(**changes):
    data=dict(ppo='123456789012345',pensioner='TEST PENSIONER',family='TEST FAMILY',pensioner_dob='1962-02-15',family_dob='1961-02-15',death='2026-09-02',effective='2026-09-03',category='IDA',basic='10825',enhanced='10825',enhanced_until='2029-02-14',normal='6495',normal_from='2029-02-15',commuted='4330',commutation_restore='2037-03-12',fma_before='0',fma_after='0',account='12345678901',ifsc='SBIN0000113')
    data.update(changes);return Case.from_dict(data)
def rates():return [Rate(date(2026,1,1),date(2026,3,31),D('236.7'),'IDA'),Rate(date(2026,4,1),date(2026,6,30),D('238.3'),'IDA'),Rate(date(2026,7,1),date(2026,9,30),D('241.7'),'IDA')]

class CalculationTests(unittest.TestCase):
    def test_reviewed_september_split_and_rounding(self):
        r=calculate(case(),rates(),[Payment(date(2026,9,23),'MONTHLY BILL',D(32660))],'2026-09-30')
        self.assertEqual((r['due'],r['drawn'],r['difference']),(36701,32660,4041))
        self.assertEqual(r['rows'][1]['comm'],0)
    def test_normal_family_no_commutation_and_zero_missing_payment(self):
        c=case(death='2026-01-31',effective='2026-02-01',basic='16275',commuted='6168',enhanced='16275',enhanced_until='2019-02-03',normal='9765',normal_from='2019-02-04')
        r=calculate(c,rates(),[],'2026-09-30')
        self.assertEqual((r['due'],r['drawn'],r['difference']),(264967,0,264967))
        self.assertTrue(all(x['comm']==0 for x in r['rows']))
    def test_reviewed_long_case_57_months(self):
        c=case(death='2022-01-10',effective='2022-01-11',basic='10200',commuted='4080',enhanced='10200',enhanced_until='2026-10-08',normal='6120',normal_from='2026-10-09',pensioner_dob='1959-10-09',family_dob='2005-09-15')
        schedule=[(2022,1,'184.1'),(2022,4,'185.3'),(2022,7,'190.8'),(2022,10,'195.8'),(2023,1,'201.2'),(2023,4,'202.3'),(2023,7,'205.6'),(2023,10,'215.6'),(2024,1,'215.4'),(2024,4,'216.8'),(2024,7,'217.8'),(2024,10,'224.2'),(2025,1,'228.5'),(2025,4,'226.5'),(2025,7,'227.1'),(2025,10,'233.2'),(2026,1,'236.7'),(2026,4,'238.3'),(2026,7,'241.7')]
        rr=[Rate(date(y,m,1),month_end(date(y,m+2,1)),D(v),'IDA') for y,m,v in schedule]
        dates=['2022-01-28','2022-02-25','2022-04-01','2022-04-28','2022-05-30','2022-06-29','2022-07-28','2022-08-24','2022-09-22','2022-10-27','2022-11-29'];amounts=[24409,24899,24899,25021,25021,25021,25582,25582,25582,26092,26092]
        ps=[Payment(dt(d),'MONTHLY BILL',D(v),D(490) if i==1 else D(0)) for i,(d,v) in enumerate(zip(dates,amounts))]
        r=calculate(c,rr,ps,'2026-09-30');self.assertEqual(len(r['rows']),58);self.assertEqual((r['due'],r['drawn'],r['difference']),(1830703,278200,1552503));self.assertEqual(len(r['notes']),1)
    def test_april_mapping_and_separate_arrear(self):
        ps=[Payment(date(2026,4,1),'MONTHLY BILL',D(100),D(5)),Payment(date(2026,4,28),'MONTHLY BILL',D(200)),Payment(date(2026,3,10),'SUPPLEMENTARY BILL',D(30))]
        amounts,notes=allocate(ps,date(2026,3,1),date(2026,4,30));self.assertEqual(amounts,{'2026-03':130,'2026-04':200});self.assertTrue(any('excluded' in n for n in notes));self.assertTrue(any('SUPPLEMENTARY' in n for n in notes))
    def test_single_april_bill_requires_allocation(self):
        p=Payment(date(2026,4,1),'MONTHLY BILL',D(100))
        with self.assertRaisesRegex(ValueError,'expected two'):allocate([p],date(2026,3,1),date(2026,4,30))
        p.allocated_month='2026-03';self.assertEqual(allocate([p],date(2026,3,1),date(2026,4,30))[0],{'2026-03':100})
    def test_duplicate_payment_is_not_silently_summed(self):
        p=Payment(date(2026,9,1),'MONTHLY BILL',D(10))
        with self.assertRaisesRegex(ValueError,'Duplicate'):allocate([p,p],date(2026,9,1),date(2026,9,30))
    def test_fma_full_not_partial(self):
        r=calculate(case(fma_before='1000',fma_after='1000'),rates(),[],'2026-09-30')
        self.assertEqual(sum(x['fma'] for x in r['rows']),1000);self.assertEqual(r['due'],37701)
    def test_changed_conversion_month_fma_requires_override(self):
        with self.assertRaisesRegex(ValueError,'FMA changes'):calculate(case(fma_before='1000'),rates(),[],'2026-09-30')
    def test_age_threshold_from_birthday_month_and_beneficiary(self):
        self.assertEqual(quantum(date(1946,9,28),date(2026,9,1)),D('.2'))
        r=calculate(case(pensioner_dob='1940-02-15',family_dob='1961-02-15'),rates(),[],'2026-09-30')
        self.assertEqual(r['rows'][0]['quantum'],D('216.6'));self.assertEqual(r['rows'][1]['quantum'],0)
    def test_missing_or_overlapping_dr_blocks(self):
        for rr in ([],rates()+rates()):
            with self.assertRaisesRegex(ValueError,'missing or overlapping'):calculate(case(),rr,[],'2026-09-30')
    def test_current_month_blocked(self):
        with self.assertRaisesRegex(ValueError,'current'):calculate(case(),rates(),[],month_end(date.today()))
    def test_end_of_enhanced_period_splits_month(self):
        c=case(death='2026-06-30',effective='2026-07-01',enhanced_until='2026-07-14',normal_from='2026-07-15')
        r=calculate(c,rates(),[],'2026-07-31');self.assertEqual(len(r['rows']),2);self.assertEqual(r['rows'][1]['comm'],0)

class ParsingTests(unittest.TestCase):
    def test_order_fields_not_issue_date(self):
        text='''PPO NUMBER: 123456789012345
DATED: 15/10/2026
Sanction Order: Conversion into Family Pension/Updation of Pensioner details
Consequent upon the conversion of pension into family pension w.e.f. 03/09/2026
Name of Family Pensioner: Mrs. TEST FAMILY
Family Pension Enhanced Rate: Rs. 10825
upto: 14/02/2029
Normal Rate: Rs.6495
With Effect From: 15/02/2029
Medical Allowance: NIL
Account no.: 12345678901
IFSC Code: SBIN0000113'''
        f,_=parse_text(text);self.assertEqual(f['effective'],'2026-09-03');self.assertEqual(f['account'],'12345678901');self.assertEqual(f['enhanced'],'10825');self.assertEqual(f['normal_from'],'2029-02-15');self.assertEqual(f['family'],'TEST FAMILY')
    def test_conflict_left_blank(self):
        data,sources,notes=merge_candidates([('a',{'basic':'10'}),('b',{'basic':'20'})]);self.assertNotIn('basic',data);self.assertTrue(notes)

class ExcelTests(unittest.TestCase):
    def test_output_layout_cache_colours_and_schema(self):
        r=calculate(case(),rates(),[Payment(date(2026,9,23),'MONTHLY BILL',D(32660))],'2026-09-30')
        with tempfile.TemporaryDirectory() as folder:
            p=export(case(),r,folder);self.assertEqual(p.name,'123456789012345_TEST_FAMILY.xlsx')
            s=load_workbook(p,data_only=True).active;self.assertEqual(s['G31'].value,4041);self.assertEqual(s['G6'].value,'12345678901');self.assertEqual(s['K26'].value,32660)
            self.assertEqual(len(s.conditional_formatting),1)
            self.assertFalse(any(c.border.top.style or c.border.bottom.style for row in s.iter_rows(min_row=29,max_row=37) for c in row))
            with ZipFile(p) as z:
                ns='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
                for f in E.fromstring(z.read('xl/styles.xml')).iter(ns+'patternFill'):
                    tags=[x.tag for x in f]
                    if ns+'fgColor' in tags and ns+'bgColor' in tags:self.assertLess(tags.index(ns+'fgColor'),tags.index(ns+'bgColor'))
    def test_recovery_label_and_negative_result(self):
        r=calculate(case(),rates(),[Payment(date(2026,9,23),'MONTHLY BILL',D(40000))],'2026-09-30')
        with tempfile.TemporaryDirectory() as folder:
            s=load_workbook(export(case(),r,folder),data_only=True).active
            self.assertEqual(s['G31'].value,-3299);self.assertEqual(s['B31'].value,'Recovery to be done')
    def test_rate_excel_percent_and_cda_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            w=Workbook();s=w.active;s.title='IDA_DR';s.append(['From Date','To Date','Rate']);s.append([date(2026,7,1),date(2026,9,30),2.417]);s['C2'].number_format='0.0%';p=Path(folder)/'rates.xlsx';w.save(p)
            rr=load_rates(p);self.assertEqual(rr[0].percent,D('241.700'))
            with self.assertRaisesRegex(ValueError,'missing or overlapping'):calculate(case(category='CDA'),rr,[],'2026-09-30')

if __name__=='__main__':unittest.main(verbosity=2)
