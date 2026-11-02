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
            self.context=self.browser.contexts[0]
            pages=[p for p in self.context.pages if urlparse(p.url).hostname=='dotpension.gov.in']
            if len(pages)!=1:raise RuntimeError('Keep exactly one SAMPANN tab open in the tool browser, then retry.')
            self.page=pages[0];self.page.bring_to_front();self.check_session()
        except Exception as e:
            self.runtime.stop();raise RuntimeError('Browser connection/setup failed: '+str(e)) from e
        return self
    def __exit__(self,kind,error,tb):
        if error:
            try:
                (self.output/'collection_error.txt').write_text(str(error)+'\nPage: '+self.page.url,encoding='utf-8')
                self.page.screenshot(path=str(self.output/'collection_error.png'),full_page=True)
            except Exception:pass
        self.runtime.stop() # retain the user tab for inspection; disconnect only
    def check_session(self):
        if '/login' in self.page.url.lower() or self.page.locator('input[type="password"]:visible').count():
            raise RuntimeError('Session expired or login incomplete. Complete SAMPANN login and OTP, then retry. Case was not skipped.')
    def wait_ready(self,predicate,description,timeout=90):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            self.check_session()
            if self.page.evaluate(predicate):return
            self.page.wait_for_timeout(250)
        raise RuntimeError(description+' timed out. Keep the portal page open and retry. Case was not skipped.')
    def navigate(self,url):
        self.check_session();path=urlparse(url).path
        if urlparse(self.page.url).path.rstrip('/')==path.rstrip('/'):
            self.wait_ready("() => !!document.querySelector('#PPONumber') && !!document.querySelector('#search')",'Report controls')
            return
        self.log('Opening report through the portal menu...')
        # Only click a real portal link. Never goto a guessed/deep report URL.
        target=self.page.locator('a[href*="'+path+'"]')
        if not target.count():
            raise RuntimeError('Report menu link not found. Expand the SAMPANN Reports menu in the tool browser and retry. No direct URL was opened.')
        if target.count()!=1:raise RuntimeError('More than one report menu link found. Open the required report manually, then retry.')
        # Expand actual ancestor menu toggles, from outside to inside.
        toggles=target.evaluate("""el => {
          const result=[];
          for(let p=el.parentElement;p;p=p.parentElement){
            if(p.tagName==='LI'){
              const a=[...p.children].find(x=>x.tagName==='A' && x!==el);
              if(a)result.unshift(a.innerText.trim());
            }
          }return result.filter(Boolean);
        }""")
        for label in toggles:
            if target.is_visible():break
            toggle=self.page.get_by_role('link',name=label,exact=True)
            if toggle.count()==1 and toggle.is_visible():toggle.click()
        if not target.is_visible():raise RuntimeError('Report menu is collapsed. Expand it and retry.')
        target.click(timeout=30000)
        self.wait_ready("""() => document.readyState!=='loading' &&
          !!document.querySelector('#PPONumber') && !!document.querySelector('#search')""",'Report page loading')
        if urlparse(self.page.url).path.rstrip('/')!=path.rstrip('/'):
            raise RuntimeError('Portal opened a different page. Report navigation needs review.')
    def search(self,ppo):
        self.check_session();self.log('Searching PPO; waiting for a completed report response...')
        self.page.locator('#PPONumber').fill(ppo)
        # Observe an actual request carrying this PPO, not network-idle or a fixed sleep.
        completed=[]
        def finished(request):
            payload=request.url+' '+(request.post_data or '')
            if ppo in payload:
                response=request.response()
                if response and response.ok:completed.append(True)
        self.page.on('requestfinished',finished)
        try:
            self.page.locator('#search').click()
            deadline=time.monotonic()+90
            while not completed and time.monotonic()<deadline:
                self.check_session();self.page.wait_for_timeout(250)
            if not completed:raise RuntimeError('PPO search response was not confirmed. No missing-document or zero-payment assumption was made.')
            self.wait_ready("""() => document.readyState!=='loading' &&
              ![...document.querySelectorAll('.dataTables_processing,.loading-overlay,.blockUI')]
                .some(e=>e.getClientRects().length && getComputedStyle(e).visibility!=='hidden' && getComputedStyle(e).display!=='none')""",'Report rendering')
        finally:self.page.remove_listener('requestfinished',finished)
    def pdf(self,url,filename):
        url=urljoin(BASE,url)
        if urlparse(url).hostname!='dotpension.gov.in':raise ValueError('Unexpected document origin; review link.')
        response=self.context.request.get(url,timeout=60000)
        data=response.body()
        if not response.ok or not data.startswith(b'%PDF'):raise ValueError(filename+': portal returned no PDF (session expired or link unavailable).')
        dest=self.output/filename;dest.write_bytes(data);return dest
    def documents(self,ppo):
        self.navigate(DOCS);self.search(ppo)
        self.wait_ready("""() => document.body.innerText.includes('Revision Authority Documents')""",'Revision Authority section loading')
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
        if not revisions:
            raise RuntimeError('Revision Authority section loaded, but no supported download links were identified. Review the portal page; this case has NOT been skipped.')
        docs=[]
        for i,x in enumerate(revisions):
            self.log(f'Downloading revision authority {i+1}...');docs.append(('conversion',self.pdf(x['href'],f'revision_{i+1}.pdf')))
        originals=[x for x in sections['EPPO Documents'] if 'EPPO' in x['text'].upper() or 'COMMUTATION' in x['text'].upper()]
        for i,x in enumerate(originals):docs.append(('original',self.pdf(x['href'],f'original_{i+1}.pdf')))
        migrated=self.page.get_by_role('link',name='View Pensioner Details',exact=True)
        if migrated.count():
            before=set(self.context.pages);previous=self.page.url
            migrated.first.click()
            self.page.wait_for_timeout(250)
            opened=[p for p in self.context.pages if p not in before]
            p=opened[0] if opened else self.page
            try:
                p.wait_for_load_state('domcontentloaded',timeout=90000)
                if '/login' in p.url.lower():raise RuntimeError('Session expired while opening migrated details.')
                p.locator('body').wait_for(state='visible',timeout=90000)
                text=p.locator('body').inner_text()
                if not re.search(r'date of birth|basic pension|pensioner name',text,re.I):
                    raise RuntimeError('Migrated profile content could not be verified. Import the profile for review.')
                (self.output/'migrated_profile.txt').write_text(text,encoding='utf-8');docs.append(('profile',self.output/'migrated_profile.txt'))
            finally:
                if opened:p.close()
                elif self.page.url!=previous:self.page.go_back(wait_until='domcontentloaded',timeout=90000)
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
