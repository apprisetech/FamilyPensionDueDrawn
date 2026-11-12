"""Local, per-run evidence. Never records authentication payloads or uploads data."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import hashlib, json, os, platform, sys, time, uuid, zipfile


def safe_url(value):
    """Keep the route, never opaque file paths, query credentials or fragments."""
    try:
        p = urlsplit(str(value))
        return urlunsplit((p.scheme, p.netloc.split('@')[-1], p.path, '', ''))
    except ValueError:
        return '[invalid URL]'


class Recorder:
    def __init__(self, folder, operation='collection'):
        self.folder = Path(folder) / 'runs' / (datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
        self.folder.mkdir(parents=True, exist_ok=False)
        self.sequence = 0
        self.failed = False
        self.ended = False
        digest = hashlib.sha256()
        for source in sorted(Path(__file__).parent.glob('*.py')):
            digest.update(source.name.encode());digest.update(source.read_bytes())
        self.event('run_started', operation=operation, python=sys.version.split()[0], platform=platform.system(), source_sha256=digest.hexdigest())

    def event(self, status, **values):
        self.sequence += 1
        row = dict(sequence=self.sequence, utc=datetime.now(timezone.utc).isoformat(), status=status, **values)
        with (self.folder / 'steps.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(row, default=str, ensure_ascii=False) + '\n')
            f.flush()
        return row

    def checkpoint(self, **values):
        dest = self.folder / 'progress.json'
        previous = json.loads(dest.read_text(encoding='utf-8')) if dest.exists() else {}
        previous.update(values)
        temp = dest.with_suffix('.tmp')
        temp.write_text(json.dumps(previous, default=str, indent=2, ensure_ascii=False), encoding='utf-8')
        os.replace(temp, dest)

    @contextmanager
    def step(self, action, expected, page=None, **details):
        started = time.monotonic()
        self.event('started', action=action, expected=expected, **details)
        try:
            yield
        except Exception as error:
            self.event('failed', action=action, expected=expected, actual=str(error), elapsed_seconds=round(time.monotonic()-started, 3))
            if not self.failed:
                self.capture(page, action)
            self.failed = True
            raise
        else:
            self.event('succeeded', action=action, expected=expected, actual='verified', elapsed_seconds=round(time.monotonic()-started, 3))

    def capture(self, page, label='failure'):
        """Rendered DOM only; remove scripts, hidden/credential values and URL queries."""
        prefix = f'{self.sequence:04d}'
        if page is None:
            self.event('evidence_unavailable', reason='Browser connection not established', action=label)
            return
        try:
            self.event('page_state', action=label, page=safe_url(page.url))
            auth = '/login' in page.url.lower() or page.locator(
                'input[type="password"]:visible,input[autocomplete="one-time-code"]:visible,'
                'input[name*="otp" i]:visible,input[id*="otp" i]:visible').count() > 0
            if auth:
                self.event('evidence_omitted', reason='Authentication screen; no screenshot or field contents retained')
                return
            page.screenshot(path=str(self.folder / (prefix + '.png')), full_page=True, timeout=10000)
            state = page.locator('body').evaluate("""body => {
                const root=body.cloneNode(true);
                root.querySelectorAll('script,style,iframe,object,embed,input[type=password],input[type=hidden]').forEach(e=>e.remove());
                root.querySelectorAll('*').forEach(e=>[...e.attributes].forEach(a=>{
                    if(/^on/i.test(a.name)||/token|nonce|secret|password|cookie/i.test(a.name))e.removeAttribute(a.name);
                    else if(['href','src','action'].includes(a.name))e.setAttribute(a.name,a.value.split('?')[0].split('#')[0]);
                    else if(a.name.startsWith('data-'))e.removeAttribute(a.name);
                }));
                root.querySelectorAll('input').forEach(e=>{
                    if(/otp|pass|token|secret|auth|verification/i.test(e.name+' '+e.id+' '+e.getAttribute('placeholder')))e.remove();
                    else e.setAttribute('value',e.value);
                });
                return {html:root.outerHTML,text:root.innerText||root.textContent};
            }""")
            (self.folder / (prefix + '.html')).write_text(state['html'], encoding='utf-8')
            (self.folder / (prefix + '.txt')).write_text(state['text'], encoding='utf-8')
        except Exception as error:
            self.event('evidence_unavailable', action=label, reason=type(error).__name__)

    def finish(self, error=None, page=None):
        if self.ended:return
        if error:
            self.event('run_failed', actual=str(error))
            if not self.failed:
                self.capture(page)
            self.failed = True
        else:
            self.event('run_finished', actual='completed')
        self.checkpoint(status='failed' if self.failed else 'completed')
        if self.failed:
            (self.folder / 'READ_ME.txt').write_text(
                'LOCAL PRIVATE DIAGNOSTICS\nsteps.jsonl records action, expected/actual result and timing.\n'
                'progress.json retains partial progress. Numbered PNG/HTML/TXT files show report failures when available.\n'
                'Login screens, request payloads, cookies and browser storage are not recorded.\n'
                'This pack may contain pension and bank information. It is never uploaded automatically.\n', encoding='utf-8')
            with zipfile.ZipFile(self.folder / 'diagnostics.zip', 'w', zipfile.ZIP_DEFLATED) as z:
                for file in self.folder.iterdir():
                    if file.is_file() and file.suffix != '.zip':
                        z.write(file, file.name)
        self.ended = True
