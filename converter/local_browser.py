"""Automate Scioly downloads in a visible, locally installed Chrome/Edge profile."""
import base64
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .signin import allowed_download
from .file_conversion import convert_to_pdf

from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout

TEST_PAGE = re.compile(r'/tests/[A-Za-z0-9_-]+')


def is_scioly_test(url):
    parsed = urlparse(url)
    return (parsed.scheme == 'https' and parsed.hostname == 'scioly.org'
            and parsed.port in (None, 443) and not parsed.username
            and TEST_PAGE.fullmatch(parsed.path) is not None)


def signed_in(page):
    try:
        text = page.locator('body').inner_text(timeout=5000)
        return ('Your checked out tests' in text and 'checkouts remaining' in text.lower()) or page.locator('a[href*="mode=logout"]').count() > 0
    except Exception:
        return False


class LocalBrowser:
    def __init__(self, store, discovery, stop):
        self.store = store
        self.discovery = discovery
        self.stop = stop
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.thread = None
        self.state = {'status': 'idle', 'message': 'Select up to 10 tests to download in a local Chrome window.',
                      'done': 0, 'total': 0, 'results': []}

    def public(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    def update(self, **changes):
        with self.lock:
            self.state.update(changes)

    def start(self, ids, continue_all=False):
        if not isinstance(ids, list) or not 1 <= len(ids) <= 10:
            raise ValueError('Choose 1 to 10 tests for automatic browser download.')
        pages = []
        for job in dict.fromkeys(ids):
            detail = self.store.detail(job)
            url = detail['source'].get('sourceUrl', '')
            if not is_scioly_test(url):
                raise ValueError('One selected listing has no safe Scioly test page.')
            if not any(not self.store.availability({'assets': [a]})['localFiles']
                       for a in detail['source'].get('assets', [])):
                continue
            pages.append(job)
        if continue_all:
            seen = set(pages)
            for row in self.store.snapshot()['jobs']:
                job = row['id']
                available = row.get('availability') or {}
                if job in seen or available.get('localFiles', 0) >= available.get('listedFiles', 0):
                    continue
                try:
                    detail = self.store.detail(job)
                    source = detail['source']
                    if is_scioly_test(source.get('sourceUrl', '')) and any(
                            not self.store.availability({'assets': [asset]})['localFiles']
                            for asset in source.get('assets', [])):
                        pages.append(job)
                        seen.add(job)
                except (KeyError, OSError, ValueError):
                    continue
        if not pages:
            raise ValueError('All listed Scioly tests already have their files locally.')
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('Automatic browser download is already running.')
            self.cancel.clear()
            self.state = {'status': 'starting', 'message': f'Opening a separate local Chrome window for {len(pages)} tests…',
                          'done': 0, 'total': len(pages), 'results': []}
            self.thread = threading.Thread(target=self._run, args=(pages,), daemon=True)
            self.thread.start()
        return {'message': 'Automatic download started. Sign in to the opened browser window if Scioly asks.'}

    def request_cancel(self):
        self.cancel.set()
        return {'message': 'Stopping after the current test. Saved PDFs remain in the converter.'}

    def _stopped(self):
        return self.cancel.is_set() or self.stop.is_set()

    def _launch(self, playwright):
        profile = self.store.home / 'state' / 'scioly-automation-browser'
        profile.mkdir(parents=True, exist_ok=True)
        errors = []
        for channel in ('chrome', 'msedge'):
            try:
                return playwright.chromium.launch_persistent_context(
                    str(profile), channel=channel, headless=False, accept_downloads=True,
                    no_viewport=True,
                    args=['--no-first-run', '--no-default-browser-check'])
            except Exception as exc:
                errors.append(f'{channel}: {type(exc).__name__}: {str(exc).splitlines()[0][:180]}')
        raise ValueError('Could not open Chrome or Edge for automatic downloads. ' + '; '.join(errors))

    def _wait_for_signin(self, page):
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline and not self._stopped():
            if page.is_closed():
                raise ValueError('The automation browser was closed before sign-in finished.')
            if signed_in(page):
                return True
            time.sleep(2)
        return False

    def _reopen(self, playwright, context, target):
        """Restart the managed browser without discarding its signed-in profile."""
        try:
            context.close()
        except Exception:
            pass
        replacement = self._launch(playwright)
        try:
            page = replacement.pages[0] if replacement.pages else replacement.new_page()
            page.goto('https://scioly.org/tests', wait_until='domcontentloaded', timeout=30000)
            if not signed_in(page):
                self.update(status='waiting_signin', message='The browser reopened, but Scioly needs sign-in again.')
                if not self._wait_for_signin(page):
                    raise ValueError('Scioly sign-in expired after the browser reopened.')
            page.goto(target, wait_until='domcontentloaded', timeout=30000)
            self.update(status='downloading')
            return replacement, page
        except Exception:
            replacement.close()
            raise

    @staticmethod
    def _matching(downloads, name, used, only_file=False):
        for download in downloads:
            if download in used:
                continue
            candidate = re.sub(r' \(\d+\)(?=\.[^.]+$)', '', download.suggested_filename, flags=re.I)
            if candidate.casefold() == name.casefold():
                return download
        if only_file:
            available = [d for d in downloads if d not in used]
            if len(available) == 1:
                return available[0]
        return None

    @staticmethod
    def _click_file(page, name):
        link = page.get_by_role('link', name=name, exact=True)
        if link.count() == 1 and link.is_visible():
            link.click(timeout=8000)
            return True
        row = page.locator('li').filter(has_text=name)
        if row.count() == 1:
            button = row.get_by_role('button', name=re.compile('download', re.I))
            if button.count() == 1 and button.is_visible():
                button.click(timeout=8000)
                return True
            link = row.get_by_role('link', name=re.compile('download', re.I))
            if link.count() == 1 and link.is_visible():
                link.click(timeout=8000)
                return True
        return False

    @staticmethod
    def _checkout_count(page):
        text = page.locator('body').inner_text(timeout=5000)
        match = re.search(r"using\s+(\d+)\s+of\s+5\s+checkouts", text, re.I)
        if not match:
            match = re.search(r"5\s+checkouts\s*\(\s*(\d+)\s+in use", text, re.I)
        return int(match.group(1)) if match else None

    @staticmethod
    def _file_url(page, name):
        row = page.locator('li').filter(has_text=name)
        if row.count() == 1:
            link = row.get_by_role('link', name='Download', exact=True)
            if link.count() == 1 and link.is_visible():
                href = link.get_attribute('href')
                if href:
                    return urljoin(page.url, href)
        link = page.get_by_role('link', name=name, exact=True)
        if link.count() == 1 and link.is_visible():
            href = link.get_attribute('href')
            if href:
                return urljoin(page.url, href)
        return None

    @staticmethod
    def _file_endpoint(url, listing):
        target = urlparse(url)
        source = urlparse(listing)
        return (target.scheme == 'https' and target.hostname == 'scioly.org'
                and target.port in (None, 443) and not target.username
                and is_scioly_test(listing)
                and re.fullmatch(re.escape(source.path) + r'/files/\d+', target.path) is not None)

    @classmethod
    def _fetch_file_link(cls, page, name):
        """Fetch a named attachment through the signed-in browser session, one file at a time."""
        url = cls._file_url(page, name)
        if not url or not (allowed_download(url) or cls._file_endpoint(url, page.url)):
            return None
        response = page.context.request.get(url, timeout=30000, headers={'Referer': page.url})
        if not response.ok or not (allowed_download(response.url) or cls._file_endpoint(response.url, page.url)):
            return None
        data = response.body()
        if not data or len(data) > 50 * 1024 * 1024:
            return None
        return data

    def _import_file(self, job, name, data):
        pdf, converted = convert_to_pdf(name, data)
        payload = {'name': name if name.lower().endswith('.pdf') else name + '.pdf',
                   'sourceName': name, 'data': base64.b64encode(pdf).decode('ascii')}
        outcome = self.discovery.local_import(job, [payload])['results'][0]
        if converted:
            outcome['message'] = 'Converted to PDF. ' + outcome['message']
        return {'name': name, 'status': outcome['status'], 'message': outcome['message']}

    def _release_checkout(self, page, url, before):
        current = self._checkout_count(page)
        if before is not None and current is not None and current <= before:
            return True
        choices = [page.get_by_role(role, name=re.compile(r'skip( the)? review|skip$', re.I))
                   for role in ('button', 'link')]
        for locator in choices:
            if locator.count() and locator.first.is_visible():
                locator.first.click(timeout=8000)
                for _ in range(20):
                    page.wait_for_timeout(250)
                    current = self._checkout_count(page)
                    if before is not None and current is not None and current <= before:
                        return True
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
                current = self._checkout_count(page)
                return before is not None and current is not None and current <= before
        return False

    def _process_one(self, page, job, url_override=None):
        detail = self.store.detail(job)
        source = detail['source']
        url = url_override or source['sourceUrl']
        missing = [a for a in source.get('assets', [])
                   if not self.store.availability({'assets': [a]})['localFiles']]
        downloads = []
        used = set()
        def on_download(download):
            downloads.append(download)
        page.on('download', on_download)
        results = []
        checked_out = False
        before = None
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
            before = self._checkout_count(page)
            if before is not None and before >= 5:
                return {'job': job, 'files': [], 'released': False, 'checkoutFull': True,
                        'checkoutBefore': None, 'error': 'Scioly reports all five checkout slots in use.'}
            checkout = page.get_by_role('button', name='Checkout and download', exact=True)
            if checkout.count() and checkout.is_visible():
                checked_out = True
                checkout.click(timeout=10000)
                page.wait_for_timeout(800)
            for asset in missing:
                if self._stopped():
                    break
                name = asset['name']
                only_file = len(missing) == 1
                download = self._matching(downloads, name, used, only_file)
                if download is None:
                    try:
                        data = self._fetch_file_link(page, name)
                    except Exception:
                        data = None
                    if data is not None:
                        try:
                            results.append(self._import_file(job, name, data))
                        except Exception as exc:
                            results.append({'name': name, 'status': 'failed', 'message': str(exc)[:250]})
                        continue
                if download is None:
                    clicked = self._click_file(page, name)
                    if not clicked:
                        again = page.get_by_role('button', name='Download all again', exact=True)
                        if again.count() and again.is_visible():
                            again.click(timeout=10000)
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline and not self._stopped():
                        download = self._matching(downloads, name, used, only_file)
                        if download:
                            break
                        page.wait_for_timeout(250)
                if download is None:
                    results.append({'name': name, 'status': 'missing', 'message': 'Scioly did not provide a usable PDF for this listed file.'})
                    continue
                used.add(download)
                try:
                    saved = Path(download.path())
                    if saved.stat().st_size > 50 * 1024 * 1024:
                        raise ValueError('File exceeds 50 MB.')
                    data = saved.read_bytes()
                    results.append(self._import_file(job, name, data))
                except Exception as exc:
                    results.append({'name': name, 'status': 'failed', 'message': str(exc)[:250]})
            released = self._release_checkout(page, url, before) if checked_out else True
            return {'job': job, 'files': results, 'released': released,
                    'checkoutBefore': before if checked_out else None}
        except Exception as exc:
            released = False
            if not checked_out:
                released = True
            elif before is not None:
                try:
                    released = self._release_checkout(page, url, before)
                except Exception:
                    pass
            return {'job': job, 'files': results, 'released': released,
                    'checkoutBefore': before if checked_out else None, 'error': str(exc)[:250]}
        finally:
            page.remove_listener('download', on_download)

    def _run(self, jobs):
        context = None
        try:
            with sync_playwright() as playwright:
                context = self._launch(playwright)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto('https://scioly.org/tests', wait_until='domcontentloaded', timeout=30000)
                if not signed_in(page):
                    self.update(status='waiting_signin', message='Sign in to Scioly in the opened Chrome window. The download will continue automatically after sign-in.')
                    if not self._wait_for_signin(page):
                        raise ValueError('Sign-in did not finish within five minutes. Click download again when ready.')
                self.update(status='downloading', message=f'Signed in. Downloading {len(jobs)} tests one at a time…')
                for index, job in enumerate(jobs, 1):
                    if self._stopped():
                        self.update(status='cancelled', message='Stopped. Downloads already imported remain saved.')
                        return
                    detail = self.store.detail(job)
                    url = detail['source']['sourceUrl']
                    self.update(message=f'Downloading {index} of {len(jobs)}: {detail["source"].get("competition", "Test")}')
                    outcome = {'job': job, 'files': [], 'released': False}
                    try:
                        if page.is_closed():
                            context, page = self._reopen(playwright, context, url)
                        outcome = self._process_one(page, job)
                        if outcome.get('checkoutFull'):
                            context, page = self._reopen(playwright, context, url)
                            count = self._checkout_count(page)
                            if count is not None and count < 5:
                                outcome = self._process_one(page, job)
                        elif outcome.get('error') and page.is_closed() and not self._stopped():
                            context, page = self._reopen(playwright, context, url)
                            outcome = self._process_one(page, job)
                        before = outcome.pop('checkoutBefore', None)
                        if not outcome.get('released', True) and before is not None and not self._stopped():
                            context, page = self._reopen(playwright, context, url)
                            outcome['released'] = self._release_checkout(page, url, before)
                            if outcome['released']:
                                outcome['recovery'] = 'Browser reopened and checkout slot released.'
                    except Exception as exc:
                        outcome['released'] = False
                        outcome['error'] = str(exc)[:250]
                    with self.lock:
                        self.state['results'].append(outcome)
                        self.state['done'] = index
                    if not outcome.get('released', True):
                        self.update(status='partial', message='Scioly still reports a full or unreleased checkout after the browser reopened. Saved files remain available. Free a checkout on Scioly before resuming.')
                        return
                self.update(status='complete', message='Automatic browser download finished. Review any PDFs whose checksums differ from the listing.')
        except Exception as exc:
            self.update(status='cancelled' if self._stopped() else 'failed',
                        message='Stopped.' if self._stopped() else str(exc)[:350])
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
