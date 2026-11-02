"""Offline Chromium fixtures. No user session or real SAMPANN requests are used.

RUN_BROWSER_TESTS=1 python -m unittest discover -s tests -v
Optional TEST_BROWSER_CHANNEL=chrome uses installed Chrome in a temporary profile.
"""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from pension_tool.portal import Portal, DOCS, PAYMENTS, GC

PPO='123456789012345'


def page_html(path, searched=False, migrated=False, bad_payment=False):
    nav='''<ul class="nav metismenu navMain" style="height:120px;overflow:auto">
    <li><a href="#" onclick="document.querySelector('#branches').style.display='block';return false">Reports</a>
    <ul id="branches" style="display:none"><li><a href="#" onclick="document.querySelector('#details').style.display='block';return false">Pensioner Detail Reports</a>
    <ul id="details" style="display:none"><li><a href="/Report/Report/PensionerDocumentReport">Pensioner Document Report</a></li></ul></li>
    <li><a href="#" onclick="document.querySelector('#payments').style.display='block';return false">Payment related Reports</a>
    <ul id="payments" style="display:none"><li><a href="/Report/Report/PensionerPaymentReportAfterTransfer">Pensioner Payment Report</a></li>
    <li><a href="/Report/Report/GCPaymentReportAfterTransfer">DCRG &amp; Commuatation Payment Report</a></li></ul></li></ul></li></ul>'''
    # Match the live menu's nested text spans and event-target-sensitive handler.
    nav=nav.replace('<a href="#" onclick="document.querySelector(\'#details\').style.display=\'block\';return false">Pensioner Detail Reports</a>',
        '<a href="#" style="display:block;padding:8px;width:220px" onclick="if(event.target===this &amp;&amp; !document.querySelector(\'.collapsing\'))document.querySelector(\'#details\').style.display=\'block\';return false"><span>Pensioner Detail Reports</span></a>')
    calendar='''<script>
    document.querySelectorAll('input[readonly]').forEach(f=>f.onclick=()=>{
      document.querySelector('#picker')?.remove();let p=document.createElement('div');p.id='picker';
      p.innerHTML='<select class="ui-datepicker-year">'+[2019,2020,2022,2026,2029].map(y=>'<option>'+y+'</option>').join('')+'</select>'+
      '<select class="ui-datepicker-month">'+Array.from({length:12},(_,i)=>'<option value="'+i+'">'+i+'</option>').join('')+'</select>'+
      Array.from({length:31},(_,i)=>'<a href="#" class="ui-state-default">'+(i+1)+'</a>').join(' ');
      document.body.append(p);p.querySelectorAll('a').forEach(a=>a.onclick=()=>{
        f.value=a.textContent.padStart(2,'0')+'/'+String(Number(p.querySelector('.ui-datepicker-month').value)+1).padStart(2,'0')+'/'+p.querySelector('.ui-datepicker-year').value;p.remove();return false;
      });
    });
    </script>'''
    if 'ViewPensionerOnePager' in path:
        return nav+f'''<button onclick="history.back()">Back</button>
        <table><tr><td>S. No.</td><td>Personal Details</td></tr><tr><td>1</td><td>PPONumber</td><td>{PPO}</td></tr>
        <tr><td>2</td><td>Pensioner Name</td><td>TEST ORIGINAL</td></tr><tr><td>3</td><td>Date Of Birth</td><td>04/02/1952</td></tr>
        <tr><td>4</td><td>Date Of Death(only in case of Family Pension)</td><td>31/01/2026</td></tr><tr><td>5</td><td>Pay Commission</td><td>CDA</td></tr></table>
        <table><tr><td>S. No.</td><td>Family Details</td></tr><tr><td>1</td><td>Name</td><td>TEST FAMILY</td></tr><tr><td>2</td><td>Date Of Birth</td><td>01/01/1957</td></tr></table>
        <table><tr><td>S. No.</td><td>Pension Details</td></tr><tr><td>1</td><td>Basic Pension</td><td>16275</td></tr></table>'''
    if path.endswith('PensionerDocumentReport'):
        result=''
        if searched:
            profile=f'<a href="/Report/Report/ViewPensionerOnePager?PensionerID=7">View Pensioner Details</a>' if migrated else 'No data available in table'
            result=f'''<div class="ibox-content"><span>Revision Authority Documents</span><table><tr><td>1</td><td>CCA</td><td></td><td>28/10/2026</td><td><a target="_blank" href="/File/GetFile?document=revision">View</a></td></tr></table></div>
            <div class="ibox-content"><span>EPPO Documents</span><table><tr><td><a target="_blank" href="/Report/Report/Download?document=original">EPPO File/</a></td></tr></table></div>
            <div class="ibox-content"><span>Pensioner ViewFrom Documents</span><a onclick="openForm14()">Form14 /</a></div>
            <div class="ibox-content"><span>Migrated Pensioner Details</span><table><tr><td>{profile}</td></tr></table></div>
            <div class="modal" id="myAddNominationForm1" aria-hidden="true" style="display:none"><button class="close" onclick="this.parentElement.style.display='none'">Close</button>
            <div id="divNominationForm1"><div id="tabcontent"></div></div></div>
            <script>function openForm14(){{
              if({str(migrated).lower()}){{fetch('/forbidden-form14');return;}}
              setTimeout(()=>{{document.querySelector('#tabcontent').innerHTML='<h2>Form 14</h2><table><tr><td>1.(i) Name of the Government servant</td><td>Late. TEST ORIGINAL</td></tr><tr><td>Date of death of Government Servant</td><td>10/01/2022</td></tr></table><table><tr><th>Name</th><th>Date of Birth</th><th>Relationship with the deceased Government Servant</th></tr><tr><td>TEST FAMILY</td><td>15/09/2005</td><td>Son</td></tr></table>';document.querySelector('#myAddNominationForm1').style.display='block';}},200);
            }}</script>'''
        # Live report repeats ibox-content on a wrapper and its inner data panel.
        nesting="""<script>document.querySelectorAll('.ibox-content').forEach(outer=>{
          let inner=document.createElement('div');inner.className='ibox-content';
          while(outer.firstChild)inner.append(outer.firstChild);outer.append(inner);
        });</script>"""
        return nav+f'<form><input id="PPONumber" name="PPONumber" placeholder="PPO Number" value="{PPO if searched else ""}"><button id="search">Search</button></form>'+result+nesting
    is_gc=path.endswith('GCPaymentReportAfterTransfer')
    if is_gc:
        form='''<form><select class="form-control"><option>Select</option><option>CCA - Test Circle</option></select><select class="form-control"><option>Select</option><option>All</option><option>IDA</option><option>CDA</option></select>
        <input id="FromDate" name="FromDate" placeholder="From Date" readonly><input id="ToDate" name="ToDate" placeholder="To Date" readonly><button>Search</button></form>'''
        table=f'''<input type="search" aria-label="Search"><table><thead><tr>{''.join('<th>'+x+'</th>' for x in ['PensionerId','Family Id','PPO No.','Pension Type','Commutation Amount','Date Of Restoration'])}</tr></thead><tbody><tr><td>7</td><td></td><td>{PPO}</td><td>IDA</td><td>400000</td><td>09/10/2026</td></tr></tbody></table>'''
        return nav+form+(table if searched else '')+calendar
    form=f'''<form><input id="PPONumber" name="PPONumber" placeholder="PPO Number" value="{PPO if searched else ''}"><input id="FromDate" name="FromDate" placeholder="Payment Start Date" readonly><input id="ToDate" name="ToDate" placeholder="Payment End Date" readonly><button id="search">Search</button></form>'''
    if not searched:return nav+form+calendar
    row_ppo='999999999999999' if bad_payment else PPO
    rows=[[str(i+1),row_ppo,'MONTHLY BILL',f'{i+1:02d}/09/2026','100','0'] for i in range(12)]
    table=f'''<select name="example_length"><option>10</option><option>100</option></select><table id="example"><thead><tr>{''.join('<th>'+x+'</th>' for x in ['S.No.','PPO Number','Type Of Payment/Bill','Date Of Payment','Gross Amount','Arrear'])}</tr></thead><tbody></tbody></table><div id="example_info"></div><a href="#" id="example_next">Next</a>
    <script>let rows={json.dumps(rows)};function render(){{let n=Number(document.querySelector('[name=example_length]').value);document.querySelector('#example tbody').innerHTML=rows.slice(0,n).map(r=>'<tr>'+r.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('');document.querySelector('#example_info').textContent='Showing 1 to '+Math.min(n,rows.length)+' of '+rows.length+' entries';document.querySelector('#example_next').className=n>=rows.length?'disabled':'';}}document.querySelector('[name=example_length]').onchange=render;render();</script>'''
    return nav+form+table+calendar


@unittest.skipUnless(os.environ.get('RUN_BROWSER_TESTS')=='1','Offline Chromium fixture tests are opt-in')
class BrowserFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.runtime=sync_playwright().start()
        args=dict(headless=True,args=['--host-resolver-rules=MAP dotpension.gov.in 127.0.0.1','--no-proxy-server'])
        if os.environ.get('TEST_BROWSER_CHANNEL'):args['channel']=os.environ['TEST_BROWSER_CHANNEL']
        cls.browser=cls.runtime.chromium.launch(**args)
        import fitz
        def pdf(text):
            doc=fitz.open();p=doc.new_page();p.insert_text((72,72),text);data=doc.tobytes();doc.close();return data
        cls.pdf=pdf(f'''PPO NUMBER: {PPO}
DATED: 28/10/2026
Conversion to family pension
Consequent on death w.e.f. 11/01/2022
Name of family pensioner: TEST FAMILY
Enhanced rate: 10200
up to: 08/10/2026
Normal rate: 6120
with effect from: 09/10/2026
Account number: 12345678901
IFSC: SBIN0000113
Medical allowance: NIL''')
        cls.original_pdf=pdf(f'''PPO NUMBER: {PPO}
DATED: 01/01/2020
Pensioner Name: TEST ORIGINAL
Date of birth: 09/10/1959
Basic pension: 10200
Monthly commutation: 4080
Medical allowance: NIL''')

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.runtime.stop()

    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.context=self.browser.new_context(accept_downloads=True);self.addCleanup(self.context.close)
        self.migrated=False;self.bad_payment=False;self.forbidden=0;self.visited=[];self.payment_mode='normal'
        fixture=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                url=urlparse(self.path);fixture.visited.append(url.path)
                if url.path=='/forbidden-form14':fixture.forbidden+=1
                pdf=url.path in ('/File/GetFile','/Report/Report/Download')
                html=page_html(url.path,bool(parse_qs(url.query)),fixture.migrated,fixture.bad_payment)
                if fixture.payment_mode=='count_mismatch':html=html.replace("+' entries'","+' entries (filtered from 99 total entries)'")
                if fixture.payment_mode=='empty':
                    html=html.replace('let rows='+json.dumps([[str(i+1),PPO,'MONTHLY BILL',f'{i+1:02d}/09/2026','100','0'] for i in range(12)]),'let rows=[]')
                    html=html.replace(".join('');document.querySelector('#example_info')", ".join('') || '<tr><td>No data available in table</td></tr>';document.querySelector('#example_info')")
                body=(fixture.original_pdf if 'original' in url.query else fixture.pdf) if pdf else html.encode()
                self.send_response(200)
                self.send_header('Content-Type','application/pdf' if pdf else 'text/html; charset=utf-8')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        # A real loopback server is needed: Chrome's built-in PDF viewer downloads
        # outside Playwright route fulfillment. The resolver prevents real portal access.
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        def guard(route):
            url=urlparse(route.request.url)
            if url.scheme not in ('http','https') or (url.hostname=='dotpension.gov.in' and url.port==self.server.server_port):route.continue_()
            else:route.abort()
        self.context.route('**/*',guard)
        self.page=self.context.new_page();self.page.goto(f'http://dotpension.gov.in:{self.server.server_port}'+urlparse(DOCS).path) # offline fixture setup only
        self.portal=Portal(self.temp.name);self.portal.context=self.context;self.portal.page=self.page;self.portal.timeout=3

    def test_native_menu_navigation_and_readonly_datepicker_payment_completeness(self):
        from datetime import date
        values=self.portal.payments(PPO,date(2026,9,1),date(2026,9,30))
        self.assertEqual(len(values),12);self.assertTrue(self.portal.last_query['complete'])
        self.assertTrue(self.page.locator('#FromDate').get_attribute('readonly') is not None)

    def test_normal_html_modal_and_inline_getfile_save(self):
        docs,branch=self.portal.documents(PPO)
        self.assertEqual(branch,'Normal SAMPANN')
        fields=json.loads(next(p for k,p in docs if k=='structured').read_text())['fields']
        self.assertEqual(fields['family_dob'],'2005-09-15');self.assertEqual(fields['death'],'2022-01-10')
        self.assertTrue(all(p.read_bytes().startswith(b'%PDF-') for k,p in docs if p.suffix=='.pdf'))
        # Headless-shell can leave an unidentified about:blank download tab.
        # Never close an unowned tab just to make the context count equal one.
        self.assertTrue(all(p is self.page or p.url=='about:blank' for p in self.context.pages))

    def test_document_cleanup_preserves_unrelated_tabs(self):
        unrelated=self.context.new_page();unrelated.set_content('<p>User work</p>')
        self.portal.documents(PPO)
        self.assertFalse(unrelated.is_closed());self.assertIn('User work',unrelated.content())

    def test_migrated_onepager_skips_generic_form14_and_keeps_dob_sections(self):
        self.migrated=True
        docs,branch=self.portal.documents(PPO)
        self.assertEqual(branch,'Migrated SAMPANN');self.assertEqual(self.forbidden,0)
        fields=json.loads(next(p for k,p in docs if k=='structured').read_text())['fields']
        self.assertEqual(fields['category'],'CDA');self.assertEqual(fields['pensioner_dob'],'1952-02-04');self.assertEqual(fields['family_dob'],'1957-01-01')

    def test_wrong_payment_ppo_saves_failure_evidence_and_never_completes(self):
        from datetime import date
        self.bad_payment=True
        with self.assertRaisesRegex(ValueError,'different PPO'):
            self.portal.payments(PPO,date(2026,9,1),date(2026,9,30))
        self.portal.record.finish(ValueError('different PPO'),self.page)
        self.assertIsNone(self.portal.last_query)
        self.assertTrue((self.portal.record.folder/'diagnostics.zip').exists())
        self.assertTrue(list(self.portal.record.folder.glob('*.png')))

    def test_filtered_subset_is_incomplete_even_when_row_count_matches(self):
        from datetime import date
        self.payment_mode='count_mismatch'
        with self.assertRaisesRegex(ValueError,'coverage'):
            self.portal.payments(PPO,date(2026,9,1),date(2026,9,30))
        self.assertIsNone(self.portal.last_query)

    def test_explicit_zero_report_can_complete(self):
        from datetime import date
        self.payment_mode='empty'
        self.assertEqual(self.portal.payments(PPO,date(2026,9,1),date(2026,9,30)),[])
        self.assertTrue(self.portal.last_query['complete'])

    def test_collected_sources_through_calculation_and_standard_excel(self):
        from datetime import date
        from pension_tool.extract import read_pdf,parse_text,merge_candidates
        from pension_tool.engine import Case,Rate,D,calculate
        from pension_tool.exporter import export
        from openpyxl import load_workbook
        docs,_=self.portal.documents(PPO);candidates=[]
        for kind,path in docs:
            fields=json.loads(path.read_text())['fields'] if kind=='structured' else parse_text(read_pdf(path)[0],'conversion' if kind=='revision' else 'original')[0]
            candidates.append((path.name,fields))
        gc=self.portal.commutation(PPO,date(2020,1,1));candidates.append((gc.name,json.loads(gc.read_text())['fields']))
        fields,_,conflicts=merge_candidates(candidates);self.assertEqual(conflicts,[])
        case=Case.from_dict(fields)
        payments=self.portal.payments(PPO,date(2022,1,1),date(2026,9,30))
        result=calculate(case,[Rate(date(2020,1,1),date(2027,12,31),D(0),'IDA')],payments,'2026-09-30')
        path=export(case,result,Path(self.temp.name)/'excel')
        book=load_workbook(path,data_only=True)
        self.assertEqual(book.sheetnames,['Sheet3']);self.assertEqual(result['drawn'],1200)
        self.assertEqual(book.active.max_column,12);book.close()

    def test_gc_hidden_columns_and_explicit_category(self):
        from datetime import date
        path=self.portal.commutation(PPO,date(2019,1,1))
        fields=json.loads(path.read_text())['fields']
        self.assertEqual(fields['category'],'IDA');self.assertEqual(fields['commutation_restore'],'2026-10-09')

    def test_evidence_omits_authentication_screens(self):
        self.page.set_content('<input type="password" value="do-not-save">')
        self.portal.record.capture(self.page)
        self.assertFalse(list(self.portal.record.folder.glob('*.png')))
        self.assertFalse(list(self.portal.record.folder.glob('*.html')))

    def test_evidence_omits_otp_screen_without_password(self):
        self.page.set_content('<input autocomplete="one-time-code" value="do-not-save">')
        self.portal.record.capture(self.page)
        self.assertFalse(list(self.portal.record.folder.glob('*.png')))

    def test_sanitized_dom_does_not_persist_hidden_tokens_or_scripts(self):
        self.page.set_content('<input type="hidden" value="private-token"><script>const secret="private-script"</script><a href="/report?token=secret-query" onclick="secret()">Source</a>')
        self.portal.record.capture(self.page)
        text=''.join(p.read_text(encoding='utf-8') for p in self.portal.record.folder.glob('*.html'))
        for secret in ('private-token','private-script','secret-query','onclick'):self.assertNotIn(secret,text)
