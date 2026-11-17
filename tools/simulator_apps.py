"""Q2 Pod App Store downloads and card layout for the desktop simulator."""

import hashlib
import json
import os
import re
import shutil
import stat
import threading
import time
import zipfile
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from http.client import HTTPException
from pathlib import Path, PurePosixPath
from queue import Empty, SimpleQueue
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

CATALOG_URL = 'https://raw.githubusercontent.com/DiamondBond/q2-pod/main/sources.list'
CAP = 1 << 30
HEADROOM = 64 << 20
RELEASE_CACHE_SECONDS = 300
SPECIAL = {
    'q2-rockbox': ('rockbox', '.rockbox', '.rockbox/rockbox', ('.rockbox/config.cfg',)),
    'q2-rockbox-themes': ('themes', '.rockbox', '', ('.rockbox/config.cfg',)),
    'q2-librespot': ('spotify', '.spotify', '.spotify/librespot', ('.spotify/cache/*', '.spotify/.cache-size')),
}
RESERVED = {'books', 'coverflow', 'downpic', 'photos', 'q2', 'sldp', 'tidal', 'rockbox', 'themes', 'spotify'}


@dataclass(frozen=True)
class App:
    repo: str
    name: str
    ident: str
    directory: str
    binary: str
    keep: tuple[str, ...] = ()
    dropped: bool = False


@dataclass(frozen=True)
class Release:
    tag: str
    url: str
    size: int
    digest: str | None


def parse_catalog(source):
    apps: dict[str, App] = {}
    for line in source.splitlines():
        fields = line.strip().split(maxsplit=1)
        if not fields:
            continue
        entry = fields[0]
        dropped = entry.startswith('-')
        repo = entry.removeprefix('-')
        if not re.fullmatch(r'[A-Za-z0-9-]{1,39}/[A-Za-z0-9_.-]+', repo) or len(repo) >= 80:
            continue
        slug = repo.split('/')[1]
        name = fields[1] if len(fields) > 1 else slug
        if len(name.encode()) >= 32 or not name.isprintable():
            continue
        if slug in SPECIAL:
            ident, directory, binary, keep = SPECIAL[slug]
        else:
            ident = slug.removeprefix('q2-')
            if ident in RESERVED or not re.fullmatch(r'[a-z0-9-]{1,15}', ident):
                continue
            directory, binary, keep = f'.{ident}', f'.{ident}/q2-{ident}', ()
        apps.setdefault(ident, App(repo, name, ident, directory, binary, keep, dropped))
        if len(apps) == 16:
            break
    return list(apps.values())


def open_url(url):
    return urlopen(Request(url, headers={'User-Agent': 'Q2-Pod-desktop-simulator'}), timeout=15)


def fetch_catalog():
    with open_url(CATALOG_URL) as response:
        data = response.read(65537)
    if len(data) > 65536 or not (apps := parse_catalog(data.decode('utf-8'))):
        raise ValueError('Invalid App Store catalog')
    return apps


class GitHubRateLimit(RuntimeError):
    def __init__(self, retry_at):
        self.retry_at = retry_at
        super().__init__(f'GitHub API rate limit reached. Try again after {time.strftime("%H:%M", time.localtime(retry_at))}.')


def rate_limit_deadline(error):
    if error.code not in (403, 429):
        return None
    headers = error.headers or {}
    retry = str(headers.get('Retry-After', ''))
    reset = str(headers.get('X-RateLimit-Reset', ''))
    exhausted = headers.get('X-RateLimit-Remaining') == '0'
    if error.code == 403 and not (exhausted or retry or 'rate limit' in str(error.reason).casefold()):
        return None
    now = time.time()
    if retry.isascii() and retry.isdigit() and len(retry) <= 9:
        return now + max(1, int(retry))
    if exhausted and reset.isascii() and reset.isdigit() and len(reset) <= 12 and int(reset) > now:
        return float(reset)
    return now + 60


def latest_release(app):
    try:
        with open_url(f'https://api.github.com/repos/{app.repo}/releases/latest') as response:
            raw = response.read((2 << 20) + 1)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        if (retry_at := rate_limit_deadline(exc)) is not None:
            raise GitHubRateLimit(retry_at) from exc
        raise
    if len(raw) > 2 << 20:
        raise ValueError('Release metadata is too large')
    release = json.loads(raw)
    if not isinstance(release, dict) or not isinstance(release.get('assets'), list):
        raise ValueError('Invalid release metadata')
    tag = release.get('tag_name')
    if not isinstance(tag, str) or not tag.isprintable() or not 0 < len(tag) <= 128:
        raise ValueError('Invalid release tag')
    for asset in release['assets']:
        if not isinstance(asset, dict) or not isinstance(asset.get('name'), str) or not asset['name'].endswith('.zip'):
            continue
        url, size, digest = asset.get('browser_download_url'), asset.get('size'), asset.get('digest')
        if not isinstance(url, str) or not isinstance(size, int) or not 0 < size <= CAP:
            raise ValueError('Invalid release ZIP metadata')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc != 'github.com' or not parsed.path.casefold().startswith(
                f'/{app.repo}/releases/download/'.casefold()):
            raise ValueError('Unexpected release download URL')
        if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r'sha256:[a-fA-F0-9]{64}', digest)):
            raise ValueError('Invalid release ZIP digest')
        return Release(tag, url, size, digest[7:].lower() if digest else None)
    return None


def relative_path(name):
    parts = name.rstrip('/').split('/')
    if any(not part or part in ('.', '..') or part.endswith((' ', '.')) or
           re.search(r'[<>:"\\|?*\x00-\x1f]', part) or
           re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?', part, re.IGNORECASE)
           for part in parts):
        raise ValueError('Invalid path in app package')
    return PurePosixPath(*parts)


def card_path(card, path):
    current = card
    for part in PurePosixPath(path).parts:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return card.joinpath(*PurePosixPath(path).parts)
        if stat.S_ISLNK(info.st_mode) or (getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError(f'Linked path on SD card: {path}')
    return current


def read_card_record(card, ident, suffix):
    path = card_path(card, f'.q2/apps/{ident}.{suffix}')
    if not path.is_file():
        return ''
    with path.open(encoding='utf-8') as source:
        data = source.read((1 << 20) + 1)
    if len(data) > 1 << 20:
        raise ValueError('App Store record is too large')
    return data


def installed_tag(card, app):
    if card is None:
        return ''
    tag = read_card_record(card, app.ident, 'tag').strip()
    if tag:
        return tag
    return 'Manual install' if app.binary and card_path(card, app.binary).is_file() else ''


def check_cancel(cancel):
    if cancel.is_set():
        raise InterruptedError('Cancelled')


def install(card, app, release, cancel, progress):
    check_cancel(cancel)
    staging = card_path(card, '.q2/staging')
    staging.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(card).free < release.size + HEADROOM:
        raise OSError('Not enough space on the SD card')
    with TemporaryDirectory(prefix=f'{app.ident}-', dir=staging) as folder:
        work = Path(folder)
        part = work / 'download.zip'
        progress('Downloading 0%')
        checksum = hashlib.sha256()
        size, percent = 0, 0
        with open_url(release.url) as response, part.open('wb') as out:
            while True:
                check_cancel(cancel)
                block = response.read(64 << 10)
                if not block:
                    break
                size += len(block)
                if size > release.size:
                    raise ValueError('Release ZIP is larger than expected')
                checksum.update(block)
                out.write(block)
                next_percent = size * 100 // release.size
                if next_percent > percent:
                    percent = next_percent
                    progress(f'Downloading {percent}%')
        if size != release.size or (release.digest and checksum.hexdigest() != release.digest):
            raise ValueError('Release ZIP failed verification')

        progress('Unpacking…')
        payload = work / 'payload'
        files: list[PurePosixPath] = []
        with zipfile.ZipFile(part) as archive:
            listing = []
            names: set[str] = set()
            for member in archive.infolist():
                rel = relative_path(member.filename)
                if rel.parts[0] != app.directory:
                    continue
                mode = stat.S_IFMT(member.external_attr >> 16)
                if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ValueError('Unsupported file type in app ZIP')
                if member.is_dir() or rel.name.startswith('._') or any(
                        fnmatchcase(str(rel), pattern) for pattern in app.keep):
                    continue
                if str(rel).casefold() in names or len(rel.parts) < 2:
                    raise ValueError('Conflicting paths in app ZIP')
                names.add(str(rel).casefold())
                listing.append((member, rel))
            total = sum(member.file_size for member, _ in listing)
            if not listing or total > CAP or len(listing) > 40000:
                raise ValueError('Invalid app ZIP contents')
            if shutil.disk_usage(card).free < total + HEADROOM:
                raise OSError('Not enough space on the SD card')
            for member, rel in listing:
                check_cancel(cancel)
                target = payload.joinpath(*rel.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open('xb') as out:
                    while block := source.read(64 << 10):
                        check_cancel(cancel)
                        out.write(block)
                files.append(rel)
        if app.binary and PurePosixPath(app.binary) not in files:
            raise ValueError('App binary is missing from the release ZIP')

        files.sort(key=lambda rel: str(rel) == app.binary)
        metadata = (PurePosixPath(f'.q2/apps/{app.ident}.files'), PurePosixPath(f'.q2/apps/{app.ident}.tag'))
        for rel, text in zip(metadata, ('\n'.join(map(str, files)) + '\n', release.tag)):
            target = payload.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8')
        check_cancel(cancel)
        progress('Installing…')
        place_files(card, payload, work / 'backup', [*files, *metadata])


def place_files(card, payload, backup, files):
    targets = [(rel, card_path(card, rel)) for rel in files]
    moved = []
    try:
        for rel, target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            saved = None
            if target.exists():
                if not target.is_file():
                    raise ValueError(f'App file conflicts with an SD folder: {rel}')
                saved = backup.joinpath(*rel.parts)
                saved.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, saved)
            moved.append((target, saved))
            os.replace(payload.joinpath(*rel.parts), target)
    except (OSError, ValueError):
        for target, saved in reversed(moved):
            target.unlink(missing_ok=True)
            if saved:
                os.replace(saved, target)
        raise


def remove(card, app, apps):
    files = read_card_record(card, app.ident, 'files').splitlines()
    # Rockbox Themes shares its directory and some files with Rockbox. Spotify keeps its cache.
    if app.ident in ('rockbox', 'themes', 'spotify'):
        shared = {path for other in apps if other.ident != app.ident and other.directory == app.directory
                  for path in read_card_record(card, other.ident, 'files').splitlines()}
        if app.binary:
            files = [app.binary, *[file for file in files if file != app.binary]]
        targets = []
        for file in files:
            rel = relative_path(file)
            if rel.parts[0] == app.directory and str(rel) not in shared:
                targets.append(card_path(card, rel))
        for target in targets:
            target.unlink(missing_ok=True)
    else:
        directory = card_path(card, app.directory)
        if directory.is_dir():
            shutil.rmtree(directory)
    for suffix in ('tag', 'files'):
        card_path(card, f'.q2/apps/{app.ident}.{suffix}').unlink(missing_ok=True)


class AppStore:
    def __init__(self, source):
        self.apps = parse_catalog(source)
        self.releases: dict[str, Release] = {}
        self.armed = ''
        self.job = ''
        self.item = ''
        self.stage = ''
        self.message = ''
        self.checked = 0.0
        self.retry_at = 0.0
        self.release_cache: dict[str, tuple[float, Release | None]] = {}
        self.cancel = threading.Event()
        self.events: SimpleQueue = SimpleQueue()

    def poll(self):
        finished = False
        while True:
            try:
                event, value = self.events.get_nowait()
            except Empty:
                return finished
            if event == 'stage':
                if not self.cancel.is_set() or value == 'Installing…':
                    self.stage = value
            elif event == 'catalog':
                self.apps, self.releases, self.checked = value
            elif event == 'release':
                ident, release = value
                self.releases[ident] = release
            else:
                self.job, self.item, self.stage, self.message = '', '', '', value
                finished = True

    def get_release(self, app):
        if (cached := self.release_cache.get(app.repo)) and time.monotonic() < cached[0]:
            return cached[1]
        if time.time() < self.retry_at:
            raise GitHubRateLimit(self.retry_at)
        try:
            result = latest_release(app)
        except GitHubRateLimit as exc:
            self.retry_at = exc.retry_at
            raise
        self.release_cache[app.repo] = time.monotonic() + RELEASE_CACHE_SECONDS, result
        return result

    def has_rockbox(self, card):
        try:
            return card is not None and card_path(card, SPECIAL['q2-rockbox'][2]).is_file()
        except (OSError, ValueError):
            return False

    def visible(self, card):
        has_rockbox = self.has_rockbox(card)
        return [app for app in self.apps if (app.ident != 'themes' or has_rockbox)
                and (not app.dropped or self.status(card, app) == 'Installed' or self.item == app.ident)]

    def row_status(self, card, app):
        if self.armed == app.ident:
            if self.status(card, app) == 'Install':
                return 'Starts at power-on. Press again to install'
            return 'Press again to remove'
        return self.status(card, app)

    def status(self, card, app):
        if self.item == app.ident:
            return self.stage
        try:
            tag = installed_tag(card, app)
        except (OSError, ValueError):
            return 'SD card error'
        latest = self.releases.get(app.ident)
        if tag and not app.dropped and (tag == 'Manual install' or (latest and tag != latest.tag)):
            return 'Update'
        return 'Installed' if tag else 'Install'

    def select(self, card, item, online=True, background=False):
        self.message = ''
        if self.job:
            if self.job == 'check' and item != 'check' and not background:
                self.cancel.set()
                self.message = 'Stopped checking for updates'
            elif self.job == 'install' and self.item == item and self.stage != 'Installing…':
                self.cancel.set()
                self.stage = 'Cancelling…'
            elif item != self.item and not background:
                self.message = 'Wait for the one in progress'
            return
        app = next((app for app in self.visible(card) if app.ident == item), None)
        if item != 'check' and app is None:
            return
        if app and card is None:
            self.message = 'No SD card'
            return
        status = self.status(card, app) if app else ''
        if status == 'SD card error':
            self.message = 'Could not read App Store files on the SD card'
            return
        job = 'check' if item == 'check' else 'remove' if status == 'Installed' else 'install'
        if job != 'remove' and not online:
            self.message = 'Connect to Wi-Fi'
            return
        if job == 'check' and self.checked and time.monotonic() - self.checked < 60:
            self.message = 'Checked for updates'
            return
        armed, self.armed = self.armed, ''
        if app and (job == 'remove' or app.ident == 'rockbox' and status == 'Install') and armed != item:
            self.armed = item
            self.message = 'Press again to remove' if job == 'remove' else 'Starts at power-on. Press again to install'
            return
        self.job, self.item, self.stage = job, item, ('Removing…' if job == 'remove' else 'Checking…')
        self.cancel = threading.Event()
        events, cancel, previous = self.events, self.cancel, self.apps[:]

        def work():
            try:
                if job == 'check':
                    apps = fetch_catalog()
                    seen = {current.ident for current in apps}
                    apps.extend(replace(old, dropped=True) for old in previous
                                if old.ident not in seen and installed_tag(card, old))
                    apps = apps[:16]
                    releases = {}
                    for current in apps:
                        check_cancel(cancel)
                        # An uninstalled app has no installed version to check.
                        if not current.dropped and installed_tag(card, current) and (found := self.get_release(current)):
                            releases[current.ident] = found
                    check_cancel(cancel)
                    events.put(('catalog', (apps, releases, time.monotonic())))
                    message = '' if background else 'Checked for updates'
                elif job == 'remove' and app and card:
                    if app.ident == 'rockbox':
                        if themes := next((old for old in previous if old.ident == 'themes'), None):
                            remove(card, themes, previous)
                    remove(card, app, previous)
                    message = f'{app.name} removed'
                elif app and card:
                    check_cancel(cancel)
                    if app.repo not in {current.repo for current in fetch_catalog() if not current.dropped}:
                        raise ValueError('App is no longer listed')
                    check_cancel(cancel)
                    release = self.get_release(app)
                    if release is None:
                        raise ValueError('No installable release')

                    def update_stage(stage):
                        events.put(('stage', stage))
                    install(card, app, release, cancel, update_stage)
                    events.put(('release', (app.ident, release)))
                    message = f'{app.name} installed'
                else:
                    message = 'No SD card'
            except (OSError, ValueError, RuntimeError, HTTPException, zipfile.BadZipFile) as exc:
                message = str(exc)
            events.put(('done', message))

        threading.Thread(target=work, daemon=True).start()
