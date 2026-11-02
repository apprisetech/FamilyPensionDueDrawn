"""Click-driven, read-only SAMPANN collection with private per-run evidence."""
from datetime import date
from pathlib import Path
from urllib.parse import urlparse, urljoin
import json, re, time
from .diagnostics import Recorder, safe_url
from .engine import Payment, D, dt, month_end
from .sources import gc_fields, norm, tables_to_fields

BASE = 'https://dotpension.gov.in'
# These identify/verify UI destinations; they are NEVER opened with goto/request.get.
DOCS = BASE + '/Report/Report/PensionerDocumentReport'
PAYMENTS = BASE + '/Report/Report/PensionerPaymentReportAfterTransfer'
GC = BASE + '/Report/Report/GCPaymentReportAfterTransfer'

TABLES = """es => es.map(t=>({rows:[...t.rows].map(r=>[...r.cells].map(c=>c.innerText.trim()))}))"""
SETTLED = """() => document.readyState!=='loading' &&
    ![...document.querySelectorAll('.dataTables_processing,.loading-overlay,.blockUI')]
     .some(e=>e.getClientRects().length && getComputedStyle(e).visibility!=='hidden' && getComputedStyle(e).display!=='none')"""


class Portal:
    def __init__(self, output, log=print, recorder=None):
        self.record = recorder or Recorder(output)
        self.output = self.record.folder / 'sources'
        self.output.mkdir(parents=True, exist_ok=True)
        self.log = log
        self.timeout = 90
        self.page = None
        self.runtime = None
        self.ppo = None
        self.last_query = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        try:
            with self.record.step('connect_browser', 'One logged-in SAMPANN report/dashboard tab'):
                self.runtime = sync_playwright().start()
                self.browser = self.runtime.chromium.connect_over_cdp('http://127.0.0.1:9222', timeout=15000)
                self.context = self.browser.contexts[0]
                pages = [p for p in self.context.pages if urlparse(p.url).hostname == 'dotpension.gov.in'
                         and not re.search(r'/(?:File/GetFile|Report/Report/Download)', urlparse(p.url).path, re.I)]
                if len(pages) != 1:
                    raise RuntimeError('Keep one SAMPANN dashboard/report tab in the tool browser. Previously opened PDFs may remain open.')
                self.page = pages[0]
                self.page.bring_to_front()
                self.check_session()
        except Exception as error:
            if self.runtime: self.runtime.stop()
            self.record.finish(error)
            if 'ECONNREFUSED' in str(error):
                message="The open Chrome window is not connected to this tool. Click '1. Open Chrome / Login', complete login in that window, then collect again."
            else:message=f'Browser connection/setup failed: {error}'
            raise RuntimeError(message) from error
        return self

    def __exit__(self, kind, error, tb):
        # The caller's recorder also covers parsing and export. Do not seal it early.
        if error and not self.record.failed:
            self.record.capture(self.page, 'collection_stopped')
            self.record.failed = True
        if self.runtime: self.runtime.stop()  # disconnect, do not close the user's browser

    def check_session(self):
        if self.page is None: raise RuntimeError('Browser is not connected.')
        url = urlparse(self.page.url)
        public_home = url.path.rstrip('/') in ('', '/Home', '/Home/Index')
        if (url.hostname != 'dotpension.gov.in' or '/login' in url.path.lower()
            or self.page.locator('input[type="password"]:visible').count()
            or (public_home and not self.page.locator('ul.nav.metismenu.navMain').count())):
            raise RuntimeError('Session expired or login incomplete. Complete SAMPANN login/OTP, then retry. This is not missing data.')

    def until(self, predicate, description, page=None, timeout=None):
        page = page or self.page
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while time.monotonic() < deadline:
            self.check_session()
            if predicate(): return
            page.wait_for_timeout(250)
        raise RuntimeError(description + ' timed out. Current results are incomplete; case was not skipped.')

    def wait_ready(self, predicate, description, timeout=None):
        with self.record.step('wait', description, self.page):
            self.until(lambda: self.page.evaluate(predicate), description, timeout=timeout)

    def click(self, item, label):
        with self.record.step('click', label, self.page):
            if item.count() != 1:
                raise RuntimeError(label + ': a unique control was not found.')
            # Native locator scrolling/clicking; no forced/JavaScript clicks or CSS repair.
            try:
                item.scroll_into_view_if_needed(timeout=10000)
            except Exception:
                self.record.event('recovery', action='reobserve_and_scroll', expected=label)
                self.check_session()
                item.scroll_into_view_if_needed(timeout=10000)  # safe scroll retry, never repeat an unknown click
            options = dict(timeout=15000)
            if item.evaluate('(el)=>el.tagName') == 'A':
                box = item.bounding_box()
                if box:
                    # Some portal handlers inspect event.target rather than the
                    # anchor. Native clicks on its padding avoid nested text/icon
                    # spans without invoking JavaScript click or forcing input.
                    options['position'] = dict(x=min(3,box['width']/2),y=box['height']/2)
            item.click(**options)

    def menu_item(self, label):
        return self.page.locator('ul.nav.metismenu.navMain a').filter(
            has_text=re.compile(r'^[\W_]*' + re.escape(label) + r'[\W_]*$'))

    def wait_menu(self, item, description):
        with self.record.step('wait_menu', description, self.page):
            self.until(lambda: item.count() == 1 and item.is_visible()
                       and not self.page.locator('ul.navMain .collapsing').count(), description)

    def open_menu_branch(self, parent, child, label):
        self.wait_menu(parent, label)
        if child.count() == 1 and child.is_visible():
            self.record.event('already_ready', action=label, actual='Expanded branch retained')
            return
        self.click(parent, 'Expand ' + label)
        self.wait_menu(child, 'Submenu after ' + label)

    def navigate(self, destination):
        routes = {DOCS: ('Pensioner Detail Reports', 'Pensioner Document Report'),
                  PAYMENTS: ('Payment related Reports', 'Pensioner Payment Report'),
                  GC: ('Payment related Reports', 'DCRG & Commuatation Payment Report')}
        if destination not in routes: raise ValueError('Unknown report; no direct address will be opened.')
        self.check_session()
        path = urlparse(destination).path
        with self.record.step('navigate_menu', 'Open report ' + path, self.page):
            if urlparse(self.page.url).path.rstrip('/') != path.rstrip('/'):
                self.wait_ready("() => !!document.querySelector('ul.nav.metismenu.navMain')", 'SAMPANN sidebar')
                # Collapsed/minimized sidebars must be opened with the visible toggle.
                if self.page.locator('body.mini-navbar').count():
                    self.click(self.page.locator('a.navbar-minimalize'), 'Expand sidebar')
                branch, label = routes[destination]
                reports = self.menu_item('Reports')
                parent = self.menu_item(branch)
                # Resolve by the real UI href; a stored address is only an identity check.
                target = self.page.locator('ul.nav.metismenu.navMain a').filter(
                    has_text=re.compile(re.escape(label))) if destination != GC else self.page.locator(
                        'ul.nav.metismenu.navMain a[href="/Report/Report/GCPaymentReportAfterTransfer"]')
                # Exact href separates the Payment and Archive copies of the same label.
                target = target.and_(self.page.locator('a[href="' + path + '"]'))
                self.open_menu_branch(reports, parent, 'Reports')
                self.open_menu_branch(parent, target, branch)
                self.click(target, label)
            self.until(lambda: urlparse(self.page.url).path.rstrip('/') == path.rstrip('/'), 'Correct report destination')
            controls = ('#PPONumber' if destination != GC else '#FromDate')
            self.until(lambda: self.page.locator(controls).count() == 1 and self.page.get_by_role('button', name='Search', exact=True).is_visible(), 'Report controls')

    def search(self, ppo):
        if not re.fullmatch(r'\d{15}', ppo): raise ValueError('Enter a 15-digit PPO.')
        with self.record.step('search_ppo', 'Successful current PPO response and replaced report content', self.page, ppo=ppo):
            self.check_session()
            self.page.locator('#PPONumber').fill(ppo)
            self.ppo = ppo
            completed = []
            def finished(request):
                # Inspect only for matching this query; never retain payloads/headers/cookies.
                payload = request.url + ' ' + (request.post_data or '')
                if ppo in payload:
                    response = request.response()
                    if response and response.ok: completed.append(True)
            self.page.on('requestfinished', finished)
            try:
                self.click(self.page.get_by_role('button', name='Search', exact=True), 'Search requested PPO')
                self.until(lambda: bool(completed), 'Current PPO search response')
                self.wait_ready(SETTLED, 'Report rendering')
                if self.page.locator('#PPONumber').input_value() != ppo:
                    raise RuntimeError('Report PPO input changed during collection.')
            finally:
                self.page.remove_listener('requestfinished', finished)

    def section(self, title):
        with self.record.step('read_section', title, self.page):
            item = self.page.locator('div.ibox-content').filter(
                has_text=re.compile(r'^\s*' + re.escape(title))).filter(
                has_not=self.page.locator('div.ibox-content'))
            self.until(lambda: item.count() == 1 and item.is_visible(), title)
            return item

    def document_link(self, link, filename):
        """Save only a download/PDF response produced by the actual visible link click."""
        with self.record.step('open_document', 'Clicked document produces a verified PDF', self.page, filename=filename):
            href = link.get_attribute('href') or ''
            target = urljoin(self.page.url, href) if href and not href.startswith(('#', 'javascript:')) else None
            if href and not href.startswith(('#', 'javascript:')):
                if urlparse(target).hostname != 'dotpension.gov.in':
                    raise ValueError('Unexpected document origin; review the control.')
            before = set(self.context.pages)
            previous = self.page.url
            downloads, responses, attached = [], [], []
            owned = set()
            viewer_downloads = set()
            def follows_target(request):
                while request:
                    if target and request.url == target: return True
                    request = request.redirected_from
                return False
            def belongs(page):
                return page in owned or (page not in before and target and page.url == target)
            def on_download(download):
                if download.page is self.page or belongs(download.page): downloads.append(download)
            def on_response(response):
                if urlparse(response.url).hostname == 'dotpension.gov.in' and 'application/pdf' in response.headers.get('content-type', '').lower() and follows_target(response.request):
                    self.record.event('document_response',page=safe_url(response.url),content_type='application/pdf')
                    responses.append(response)
                    try:
                        page = response.request.frame.page
                        if page not in before: owned.add(page)
                    except Exception: pass
            def on_page(page):
                page.on('download', on_download)
                attached.append(page)
                if page.opener() is self.page: owned.add(page)
            self.page.on('download', on_download)
            self.context.on('response', on_response)
            self.context.on('page', on_page)
            success = False
            try:
                self.click(link, 'Open document link')
                dest = self.output / filename
                seen = set()
                deadline = time.monotonic() + self.timeout
                while time.monotonic() < deadline:
                    self.check_session()
                    if downloads:
                        download = downloads.pop(0)
                        download.save_as(str(dest))
                        if not dest.read_bytes().startswith(b'%PDF-'):
                            raise ValueError('Clicked download returned a non-PDF file.')
                        success = True
                        break
                    for response in responses:
                        if id(response) in seen: continue
                        seen.add(id(response))
                        try:
                            data = response.body()
                            self.record.event('pdf_response_body',byte_count=len(data))
                            if data.startswith(b'%PDF-'):
                                dest.write_bytes(data)
                                success = True
                                break
                        except Exception as error:
                            self.record.event('pdf_response_unavailable', reason=type(error).__name__)
                    if success: break
                    # Chrome sometimes exposes its HTML PDF placeholder as the
                    # response body. Use the visible built-in viewer Download
                    # control, never refetch its URL or invoke a hidden PDF API.
                    viewers = [p for p in self.context.pages if belongs(p)]
                    if self.page.url != previous: viewers.append(self.page)
                    for viewer in viewers:
                        if viewer in viewer_downloads: continue
                        for frame in viewer.frames:
                            if not frame.url.startswith('chrome-extension://'): continue
                            button = frame.get_by_role('button', name='Download', exact=True)
                            if button.count() == 1 and button.is_visible():
                                self.click(button, 'Download opened PDF in viewer')
                                viewer_downloads.add(viewer)
                                break
                    self.page.wait_for_timeout(250)
                if not success:
                    raise RuntimeError('Clicked document did not produce a downloadable PDF. Viewer tabs retained for review.')
                self.record.checkpoint(last_document=str(dest), document_identity='pending PPO/content validation')
                return dest
            finally:
                self.page.remove_listener('download', on_download)
                self.context.remove_listener('response', on_response)
                self.context.remove_listener('page', on_page)
                for page in attached:
                    if not page.is_closed(): page.remove_listener('download', on_download)
                if success:
                    for page in list(self.context.pages):
                        if belongs(page): page.close()
                    if self.page.url != previous:
                        self.page.go_back(wait_until='domcontentloaded', timeout=90000)

    def form14(self, ppo):
        with self.record.step('read_form14', 'Current Normal claimant and death fields in visible HTML modal', self.page):
            self.click(self.page.get_by_text('Form14 /', exact=True), 'Open current Form 14')
            modal = self.page.locator('#myAddNominationForm1')
            # Live SAMPANN incorrectly sets aria-hidden=true on this visible dialog.
            self.until(lambda: modal.is_visible() and modal.locator('#tabcontent h2').count() == 1
                       and modal.locator('#tabcontent h2').inner_text().strip() == 'Form 14', 'Form 14 content')
            tables = modal.locator('#tabcontent table').evaluate_all(TABLES)
            fields, notes = tables_to_fields(tables, 'form14', ppo)
            # Save the required extracted fields, not Aadhaar/mobile/guardian boilerplate.
            path = self.output / 'form14_fields.json'
            path.write_text(json.dumps(dict(fields=fields, notes=notes), indent=2), encoding='utf-8')
            self.click(modal.locator('button.close'), 'Close verified Form 14')
            self.until(lambda: not modal.is_visible(), 'Form 14 closed')
            return path

    def migrated_profile(self, ppo, link):
        with self.record.step('read_migrated_profile', 'Matching one-pager sections and explicit category', self.page):
            before = set(self.context.pages)
            self.click(link, 'View Migrated Pensioner Details')
            def profile_page():
                candidates = [p for p in self.context.pages if p not in before] + [self.page]
                return next((p for p in candidates if '/ViewPensionerOnePager' in p.url), None)
            self.until(lambda: profile_page() is not None, 'Migrated profile navigation')
            profile = profile_page()
            self.until(lambda: profile.get_by_text(ppo, exact=True).count() > 0, 'Matching profile PPO', page=profile)
            tables = profile.locator('table').evaluate_all(TABLES)
            fields, notes = tables_to_fields(tables, 'profile', ppo)
            path = self.output / 'migrated_fields.json'
            path.write_text(json.dumps(dict(fields=fields, notes=notes), indent=2), encoding='utf-8')
            # No Form14 attempt for this branch. Next report navigation uses the sidebar here.
            if profile is not self.page:
                self.page = profile
            return path

    def documents(self, ppo):
        self.navigate(DOCS)
        self.search(ppo)
        revision = self.section('Revision Authority Documents')
        links = revision.locator('tr td:nth-child(5) a')
        if not links.count():
            raise RuntimeError('No Revision Authority document links after the verified query. Keep case for source review.')
        docs = []
        for i in range(links.count()):
            docs.append(('revision', self.document_link(links.nth(i), f'revision_{i+1}.pdf')))
            self.record.checkpoint(documents=[(k, str(p)) for k, p in docs])
        original = self.section('EPPO Documents')
        originals = original.locator('tr td a')
        for i in range(originals.count()):
            link = originals.nth(i)
            if re.search(r'EPPO|commutation', link.inner_text(), re.I):
                docs.append(('original', self.document_link(link, f'original_{i+1}.pdf')))
                self.record.checkpoint(documents=[(k, str(p)) for k, p in docs])
        migrated = self.section('Migrated Pensioner Details').get_by_role('link', name='View Pensioner Details', exact=True)
        if migrated.count() == 1:
            branch = 'Migrated SAMPANN'
            docs.append(('structured', self.migrated_profile(ppo, migrated)))
        elif migrated.count() > 1:
            raise RuntimeError('Ambiguous migrated profile links.')
        else:
            branch = 'Normal SAMPANN'
            docs.append(('structured', self.form14(ppo)))
        self.record.checkpoint(source_branch=branch, documents=[(k, str(p)) for k, p in docs])
        return docs, branch

    def calendar(self, placeholder, value):
        with self.record.step('select_date', f'{placeholder} = {value:%d/%m/%Y}', self.page):
            field = self.page.get_by_placeholder(placeholder, exact=True)
            self.click(field, 'Open ' + placeholder + ' calendar')
            years = self.page.locator('select.ui-datepicker-year')
            months = self.page.locator('select.ui-datepicker-month')
            self.until(lambda: years.is_visible() and months.is_visible(), 'Date-picker selectors')
            years.select_option(str(value.year))
            months.select_option(str(value.month - 1))
            day = self.page.locator('a.ui-state-default').filter(has_text=re.compile('^' + str(value.day) + '$'))
            self.click(day, 'Choose calendar day')
            if field.input_value() != value.strftime('%d/%m/%Y'):
                raise RuntimeError('Selected date was not retained by the portal.')

    def grid_rows(self, table):
        return table.locator('tbody tr').evaluate_all('(rs)=>rs.map(r=>[...r.cells].map(c=>c.innerText.trim()))')

    def payments(self, ppo, start, end):
        self.last_query = None
        with self.record.step('collect_payments', 'Complete current PPO query; all pages verified before zero is allowed', self.page):
            self.navigate(PAYMENTS)
            query_end = min(date.today(), month_end(date(end.year, 4, 1))) if end.month == 3 else end
            self.calendar('Payment Start Date', start)
            self.calendar('Payment End Date', query_end)
            self.search(ppo)
            self.until(lambda: self.page.locator('#example tbody').count() == 1, 'Payment table')
            table = self.page.locator('#example')
            selects = self.page.locator('select[name="example_length"]')
            if selects.count():
                with self.record.step('page_size', 'Show 100 payment entries', self.page):
                    selects.select_option('100')
                    self.wait_ready(SETTLED, 'Payment page-size update')
            headers = table.locator('thead th').all_inner_texts()
            keys = [norm(h) for h in headers]
            required = ['dateofpayment','typeofpaymentbill','grossamount','arrear','pponumber']
            if any(keys.count(k) != 1 for k in required):
                raise ValueError('Payment columns missing/ambiguous. No zero Drawn assumption made.')
            columns = {k: keys.index(v) for k, v in [('paid_on','dateofpayment'), ('bill_type','typeofpaymentbill'),
                       ('gross','grossamount'), ('separate_arrear','arrear')]}
            records, fingerprints = [], set()
            for index in range(1000):
                with self.record.step('payment_page', 'Read and verify complete page', self.page, page_number=index+1):
                    rows = self.grid_rows(table)
                    fingerprint = json.dumps(rows)
                    if fingerprint in fingerprints:
                        raise ValueError('Payment pagination repeated a page. Query is incomplete.')
                    fingerprints.add(fingerprint)
                    if len(rows) == 1 and len(rows[0]) == 1 and re.search(r'no data|no matching', rows[0][0], re.I):
                        if records: raise ValueError('Unexpected empty page after payments. Query is incomplete.')
                        break
                    if not rows: raise ValueError('Payment rows are not ready; blank is not zero.')
                    for row in rows:
                        if len(row) != len(headers) or re.sub(r'\s', '', row[keys.index('pponumber')]) != ppo:
                            raise ValueError('Incomplete row or different PPO in payment results.')
                        records.append({key: row[i] for key, i in columns.items()})
                    self.record.checkpoint(payment_rows=records, payment_query_complete=False)
                nxt = self.page.locator('#example_next')
                if not nxt.count():
                    raise ValueError('Payment pagination controls missing; completeness cannot be verified.')
                if 'disabled' in (nxt.get_attribute('class') or ''): break
                self.click(nxt, 'Next payment page')
                self.until(lambda: json.dumps(self.grid_rows(table)) != fingerprint, 'New payment page')
            else:
                raise ValueError('Payment pagination did not finish.')
            info = self.page.locator('#example_info').inner_text()
            match = re.search(r'of\s+([\d,]+)\s+entries', info)
            if not match or int(match.group(1).replace(',', '')) != len(records) or 'filtered from' in info.lower():
                raise ValueError('Payment total/count or filter coverage could not be reconciled.')
            values = [Payment(dt(r['paid_on']), r['bill_type'], D(r['gross'].replace(',', '')),
                              D(r['separate_arrear'].replace(',', '') or 0)) for r in records]
            if any(not start<=p.paid_on<=query_end for p in values):
                raise ValueError('Payment dates fall outside the requested query; results may be stale.')
            # Reject duplicate rows here as well as in calculation, before setting query complete.
            signatures = [(p.paid_on, p.bill_type, p.gross, p.separate_arrear) for p in values]
            if len(set(signatures)) != len(signatures): raise ValueError('Duplicate payment rows require review.')
            self.last_query = dict(ppo=ppo, start=str(start), requested_end=str(end), actual_end=str(query_end), count=len(records), complete=True)
            (self.output / 'payments_raw.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
            self.record.checkpoint(payment_rows=records, payment_query=self.last_query, payment_query_complete=True)
            return values

    def commutation(self, ppo, since):
        with self.record.step('read_commutation', 'Matching explicit Pension Type and restoration row', self.page):
            self.navigate(GC)
            selects = self.page.locator('select.form-control')
            office = selects.nth(0)
            options = office.locator('option').all_text_contents()
            choices = [text.strip() for text in options if text.strip().lower() != 'select']
            if len(choices) != 1: raise ValueError('Select the correct CCA office; office is ambiguous.')
            office.select_option(label=choices[0])
            selects.nth(1).select_option(label='All')
            self.calendar('From Date', since)
            self.calendar('To Date', date.today())
            self.click(self.page.get_by_role('button', name='Search', exact=True), 'Search DCRG and commutation details')
            self.until(lambda: self.page.get_by_role('searchbox').count() == 1, 'Commutation table filter')
            search = self.page.get_by_role('searchbox')
            search.fill(ppo)
            # Match by a real row, not only the filter's newly typed value.
            self.until(lambda: self.page.locator('tbody tr').filter(has_text=ppo).count() == 1, 'Matching commutation PPO')
            grids = self.page.locator('table').filter(has=self.page.locator('tbody tr').filter(has_text=ppo))
            if grids.count() != 1: raise ValueError('Unique commutation data table not found.')
            table = grids.first
            headers = table.locator('thead th').all_inner_texts()
            rows = self.grid_rows(table)
            fields = gc_fields(headers, rows, ppo)
            path = self.output / 'commutation_fields.json'
            path.write_text(json.dumps(dict(fields=fields, notes=fields.pop('_notes',[]), query_start=str(since)), indent=2), encoding='utf-8')
            return path
