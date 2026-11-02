"""Read-only SAMPANN collector. Never sends/approves a pension case."""
from pathlib import Path
from urllib.parse import urljoin,urlparse
from datetime import date
import json, re, time
from .engine import Payment,D,dt,month_end

BASE='https://dotpension.gov.in'
DOCS=BASE+'/Report/Report/PensionerDocumentReport'
PAYMENTS=BASE+'/Report/Report/PensionerPaymentReportAfterTransfer'

class Portal:
    def __init__(self,output,log=print):self.output=Path(output);self.output.mkdir(parents=True,exist_ok=True);self.log=log
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.runtime=sync_playwright().start()
        try:
            self.browser=self.runtime.chromium.connect_over_cdp('http://127.0.0.1:9222',timeout=15000)
            self.context=self.browser.contexts[0];self.page=self.context.new_page()
        except Exception:
            self.runtime.stop();raise RuntimeError('Open the tool Chrome window first, complete login and OTP, then retry.')
        return self
    def __exit__(self,*args):
        try:self.page.close()
        finally:self.runtime.stop() # disconnect; never close the user browser
    def navigate(self,url):
        self.page.goto(url,wait_until='domcontentloaded',timeout=60000)
        if '/Login' in self.page.url:raise RuntimeError('SAMPANN login has expired. Complete login and OTP in the tool Chrome window.')
    def search(self,ppo):
        self.page.locator('#PPONumber').fill(ppo)
        self.page.locator('#search').click()
        self.page.wait_for_load_state('networkidle',timeout=60000)
        if '/Login' in self.page.url:raise RuntimeError('Please log into SAMPANN again.')
    def pdf(self,url,filename):
        url=urljoin(BASE,url)
        if urlparse(url).hostname!='dotpension.gov.in':raise ValueError('Unexpected document origin; review link.')
        response=self.context.request.get(url,timeout=60000)
        data=response.body()
        if not response.ok or not data.startswith(b'%PDF'):raise ValueError(filename+': portal returned no PDF (session expired or link unavailable).')
        dest=self.output/filename;dest.write_bytes(data);return dest
    def documents(self,ppo):
        self.navigate(DOCS);self.search(ppo)
        # Section grouping is derived from displayed text rather than guessed IDs.
        sections=self.page.locator('div').evaluate_all('''els => {
          const result={};
          for(const title of ['Revision Authority Documents','EPPO Documents']){
            const candidates=els.filter(e=>e.innerText && e.innerText.trim().startsWith(title) && e.querySelector('table'));
            candidates.sort((a,b)=>a.innerText.length-b.innerText.length);
            result[title]=candidates.length ? [...candidates[0].querySelectorAll('a[href]')].map(a=>({text:a.innerText,href:a.getAttribute('href')})) : [];
          }return result;
        }''')
        revisions=[x for x in sections['Revision Authority Documents'] if '/Download' in x['href']]
        if not revisions:raise ValueError('SKIPPED: no Revision Authority Documents found for this PPO.')
        docs=[]
        for i,x in enumerate(revisions):
            self.log(f'Downloading revision authority {i+1}...');docs.append(('conversion',self.pdf(x['href'],f'revision_{i+1}.pdf')))
        originals=[x for x in sections['EPPO Documents'] if 'EPPO' in x['text'].upper() or 'COMMUTATION' in x['text'].upper()]
        for i,x in enumerate(originals):docs.append(('original',self.pdf(x['href'],f'original_{i+1}.pdf')))
        migrated=self.page.get_by_role('link',name='View Pensioner Details',exact=True)
        if migrated.count():
            href=migrated.first.get_attribute('href');url=urljoin(BASE,href)
            if urlparse(url).hostname!='dotpension.gov.in':raise ValueError('Unexpected migrated profile origin.')
            p=self.context.new_page()
            try:
                p.goto(url,wait_until='networkidle');text=p.locator('body').inner_text();(self.output/'migrated_profile.txt').write_text(text,encoding='utf-8');docs.append(('profile',self.output/'migrated_profile.txt'))
            finally:p.close()
        # Resolve a JavaScript Form14 viewer through its visible link; no guessed API.
        links=self.page.get_by_text('Form14 /',exact=False)
        if links.count():
            try:
                before=set(self.context.pages)
                links.first.click();self.page.wait_for_timeout(1500)
                viewers=[p for p in self.context.pages if p not in before]
                viewer=viewers[0] if viewers else self.page
                urls=[]
                if viewers and '/Login' not in viewer.url:urls.append(viewer.url)
                urls+=viewer.locator('iframe[src],embed[src],object[data]').evaluate_all('(es)=>es.map(e=>e.getAttribute("src")||e.getAttribute("data"))')
                for url in urls:
                    try:docs.append(('form14',self.pdf(url,'form14.pdf')));break
                    except ValueError:continue
                for p in viewers:p.close()
                if not any(k=='form14' for k,_ in docs):self.log('Form14 viewer did not expose a PDF URL. Import current Form14 if birth/death fields remain blank.')
            except Exception as e:self.log('Current Form14 requires document import: '+str(e).splitlines()[0])
        return docs,'Migrated' if migrated.count() else 'SAMPANN generated'
    def payments(self,ppo,start,end):
        self.navigate(PAYMENTS)
        # Include April to capture March pension when a March statement is requested.
        query_end=min(date.today(),month_end(date(end.year,4,1))) if end.month==3 else end
        for key,value in [('FromDate',start.strftime('%d/%m/%Y')),('ToDate',query_end.strftime('%d/%m/%Y'))]:
            box=self.page.locator('#'+key)
            box.evaluate('(el)=>el.removeAttribute("readonly")');box.fill(value);box.press('Tab')
        self.search(ppo)
        if self.page.locator('#example').count()!=1:raise ValueError('Payment report table was not found. No zero Drawn assumption has been made.')
        selects=self.page.locator('select[name="example_length"]')
        if selects.count():selects.select_option('100');self.page.wait_for_load_state('networkidle')
        headers=self.page.locator('#example thead th').all_inner_texts()
        norm=lambda v:re.sub(r'[^a-z]','',v.lower())
        indexes={norm(h):i for i,h in enumerate(headers)}
        def col(name):
            options=[i for h,i in indexes.items() if norm(name)==h]
            if len(options)!=1:raise ValueError(f'Payment header missing/ambiguous: {name}. Do not assume zero.')
            return options[0]
        fields={k:col(h) for k,h in [('paid_on','Date Of Payment'),('bill_type','Type Of Payment/Bill'),('gross','Gross Amount'),('separate_arrear','Arrear')]}
        ppo_index=col('PPO Number');records=[]
        for _ in range(1000):
            rows=self.page.locator('#example tbody tr').evaluate_all('(rs)=>rs.map(r=>[...r.querySelectorAll("td")].map(c=>c.innerText.trim()))')
            if len(rows)==1 and len(rows[0])==1:
                if not re.search('no data|no matching',rows[0][0],re.I):raise ValueError('Unexpected payment table response.')
                break
            for row in rows:
                if len(row)<len(headers):raise ValueError('Incomplete payment row; report collection stopped.')
                if re.sub(r'\s','',row[ppo_index])!=ppo:raise ValueError('Payment report returned a different PPO.')
                records.append({k:row[i] for k,i in fields.items()})
            nxt=self.page.locator('#example_next')
            if not nxt.count() or 'disabled' in (nxt.get_attribute('class') or ''):break
            before=self.page.locator('#example tbody').inner_text();nxt.click()
            self.page.wait_for_function('(before)=>document.querySelector("#example tbody").innerText!==before',arg=before,timeout=30000)
        else:raise ValueError('Payment pagination did not finish.')
        (self.output/'payments_raw.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
        return [Payment(dt(r['paid_on']),r['bill_type'],D(r['gross'].replace(',','')),D(r['separate_arrear'].replace(',','') or 0)) for r in records]
