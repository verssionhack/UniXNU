#!/usr/bin/env python3
"""Fetch SHA-pinned reference SM8550/Adreno inputs into an isolated r2 staging tree.

Never touches frozen r101/M1/host-gate directories or device repositories.
"""
import base64
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / 'out/liuqin-r101-gpu-host-gates-r2'
STAGE = OUT / 'stage'
TOKEN = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')


def fetch_url(url):
    import time
    headers = {'User-Agent': 'liuqin-r101-gpu-host-gates-r2'}
    if TOKEN and urllib.parse.urlsplit(url).hostname in ('api.github.com', 'raw.githubusercontent.com'):
        headers['Authorization'] = f'Bearer {TOKEN}'
    last_err = None
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except Exception as exc:
            last_err = exc
            time.sleep(0.5 * (attempt + 1))
    raise last_err


def fetch_adreno_inputs():
    pins = json.loads((ROOT / 'scripts/data/adreno-inputs.json').read_text())
    jobs = []
    linux = pins['linux']
    for name, expected in linux['files'].items():
        url = linux['repository'].replace('https://github.com/', 'https://raw.githubusercontent.com/') + '/' + linux['commit'] + '/' + name
        jobs.append((STAGE / '.cache/adreno-source' / name, url, expected, None, None))
    mesa = pins['mesa']
    for name, expected in mesa['files'].items():
        url = mesa['mirror'] + '/+/' + mesa['commit'] + '/' + name + '?format=TEXT'
        jobs.append((STAGE / '.cache/adreno-source/mesa' / name, url, expected, None, 'gitiles-base64'))
    firmware = pins['firmware']
    for name, expected in firmware['files'].items():
        blob = expected['git_blob_sha1']
        url = firmware['repository'].replace('https://github.com/', 'https://api.github.com/repos/') + '/git/blobs/' + blob
        jobs.append((STAGE / '.cache/firmware/sheng-gpu' / name, url, expected, blob, None))

    def work(item):
        path, url, expected, blob, encoding = item
        if path.exists():
            data = path.read_bytes()
        else:
            raw = fetch_url(url)
            if blob:
                data = base64.b64decode(json.loads(raw)['content'])
            elif encoding == 'gitiles-base64':
                data = base64.b64decode(raw, validate=False)
            else:
                data = raw
        actual_sha = hashlib.sha256(data).hexdigest()
        if actual_sha != expected['sha256'] or (expected.get('bytes') and len(data) != expected['bytes']):
            raise ValueError(f'Pinned input hash/size differs: {path.name}')
        if blob and hashlib.sha1(('blob ' + str(len(data)) + '\0').encode() + data).hexdigest() != blob:
            raise ValueError(f'Pinned Git blob differs: {path.name}')
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return str(path.relative_to(STAGE)), len(data), actual_sha

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        return dict((k, {'bytes': sz, 'sha256': h}) for k, sz, h in ex.map(work, jobs))


def fetch_sheng_dts():
    pins = json.loads((ROOT / 'scripts/data/adreno-inputs.json').read_text())['board']
    commit = pins['commit']
    base = f'https://raw.githubusercontent.com/ianchb/sm8550-mainline/{commit}/'
    dts_root = STAGE / '.cache/linux-dts'
    board = 'arch/arm64/boot/dts/qcom/sm8550-xiaomi-sheng.dts'
    inc_re = re.compile(r'^\s*#\s*include\s*([<"])([^>"\n]+)[>"]', re.M)

    def fetch_one(name):
        dest = dts_root / name
        if not dest.exists() and not dest.is_symlink():
            data = fetch_url(base + name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        data = os.readlink(dest).encode() if dest.is_symlink() else dest.read_bytes()
        deps = set()
        text = data.decode()
        if re.fullmatch(r'(\.\./)+[\w/.,+-]+\s*', text):
            target = posixpath.normpath(str(PurePosixPath(name).parent / text.strip()))
            if target.startswith('../'):
                raise ValueError('Source symlink escapes tree: ' + name)
            if not dest.is_symlink():
                dest.unlink()
                dest.symlink_to(text.strip())
            return name, hashlib.sha256(data).hexdigest(), {target}
        for opening, include in inc_re.findall(text):
            if opening == '<':
                deps.add('include/' + include)
            else:
                deps.add(str(PurePosixPath(name).parent / include))
        return name, hashlib.sha256(data).hexdigest(), deps

    pending = {board}
    hashes = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        while pending:
            results = list(ex.map(fetch_one, sorted(pending)))
            pending = set()
            for name, digest, deps in results:
                hashes[name] = digest
                pending |= deps
            pending -= hashes.keys()
    for name, expected in pins['sha256'].items():
        if hashes.get(name) != expected:
            raise ValueError(f'Pinned board DTS hash mismatch: {name}')
    (dts_root / 'sources.json').write_text(json.dumps({
        'repository': pins['repository'], 'commit': commit, 'sha256': hashes,
    }, indent=2) + '\n')
    return hashes


def main():
    STAGE.mkdir(parents=True, exist_ok=True)
    ev = OUT / 'evidence'
    ev.mkdir(parents=True, exist_ok=True)
    adreno = fetch_adreno_inputs()
    dts = fetch_sheng_dts()
    report = {
        'scope': 'SHA-pinned SM8550/Adreno upstream inputs fetched into isolated r2 staging tree',
        'adreno_inputs_count': len(adreno),
        'adreno_inputs_bytes': sum(v['bytes'] for v in adreno.values()),
        'dts_closure_count': len(dts),
        'adreno_inputs': adreno,
        'dts_sha256': dts,
    }
    (ev / 'fetched-reference-inputs.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'PASS: fetched and verified {len(adreno)} pinned Adreno inputs ({report["adreno_inputs_bytes"]} B) and {len(dts)} DTS files')


if __name__ == '__main__':
    main()
