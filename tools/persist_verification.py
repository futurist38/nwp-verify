"""Merge generated verification changes onto current main without rebase/stash.

Use a separate Git index and a fast-forward push. A rejected push rebuilds from
the new remote head, with a keyed three-way merge of CSV/JSON records. The job's
checkout and generated output are never reset. Only verification/ is writable.
"""
import argparse
import csv
import datetime as dt
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

KEYS = {
    'obs': ('TM', 'STN'), 'forecast': ('model', 'run_utc', 'city', 'step_h'),
    'city_forecast': ('model', 'run_utc', 'city', 'step_h'),
    'scores': ('valid_kst', 'city', 'model', 'run_utc', 'var'),
    'nowcast': ('issue_utc', 'lead_min', 'method'),
}
MISSING = object()


def git(*args, data=None, env=None, check=True):
    return subprocess.run(['git', *args], input=data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=check, env=env)


def blob(ref, path):
    r = git('show', f'{ref}:{path}', check=False)
    return r.stdout if r.returncode == 0 else None


def populated(value):
    return value is not MISSING and value is not None and value != ''


def merge_value(base, local, remote):
    # Missing local values never delete shared history. An unchanged local value
    # cannot overwrite a concurrently updated remote value.
    if local is MISSING or local == base:
        return remote
    if remote is MISSING or remote == base or local == remote:
        return local
    if isinstance(local, dict) and isinstance(remote, dict):
        base = base if isinstance(base, dict) else {}
        result = {}
        for key in sorted(local.keys() | remote.keys()):
            value = merge_value(base.get(key, MISSING), local.get(key, MISSING), remote.get(key, MISSING))
            if value is not MISSING:
                result[key] = value
        return result
    return remote if populated(remote) else local


def canonical(value, column):
    if column in {'TM', 'run_utc', 'valid_kst', 'issue_utc'}:
        try:
            return dt.datetime.fromisoformat(value).isoformat()
        except ValueError:
            pass
    return value


def merge_csv(path, base, local, remote):
    key_columns = KEYS[Path(path).parts[1]]
    def read(data):
        reader = csv.DictReader(io.StringIO((data or b'').decode('utf-8-sig')))
        columns = reader.fieldnames or []
        if columns and not set(key_columns) <= set(columns):
            raise ValueError(f'{path}: missing record key columns')
        rows = {tuple(canonical(row[k], k) for k in key_columns): row for row in reader}
        return columns, rows
    bc, br = read(base); lc, lr = read(local); rc, rr = read(remote)
    columns = list(dict.fromkeys(rc + lc + bc))
    rows = dict(rr)
    for key, row in lr.items():
        old, current = br.get(key, MISSING), rr.get(key, MISSING)
        if row == old:
            continue
        if current is MISSING or current == old or row == current:
            rows[key] = row
        else:
            # Preserve a coherent score/observation row; never mix fcst/obs/err
            # cells from different computations. On equal completeness remote
            # wins because it was published after this runner's checkout.
            count = lambda r: sum(populated(v) for v in r.values())
            rows[key] = row if count(row) > count(current) else current
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows[key] for key in sorted(rows))
    return out.getvalue().encode('utf-8-sig')


def merge_file(path, base, local, remote):
    if remote is None or remote == base or local == remote:
        return local
    if local == base:
        return remote
    if path.endswith('.csv') and Path(path).parts[1] in KEYS:
        return merge_csv(path, base, local, remote)
    if path.endswith('.json'):
        read = lambda data: json.loads(data.decode('utf-8-sig')) if data else {}
        result = merge_value(read(base), read(local), read(remote))
        return json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    print(f'[persist] concurrent non-record file: keeping remote {path}')
    return remote


def persist(paths, message, attempts=6):
    for path in paths:
        p = Path(path)
        if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0] != 'verification':
            raise ValueError('Only relative verification/ paths are allowed')
    head = git('rev-parse', 'HEAD').stdout.decode().strip()
    changed = git('diff', '--name-only', '-z', 'HEAD', '--', *paths).stdout
    untracked = git('ls-files', '--others', '--exclude-standard', '-z', '--', *paths).stdout
    names = sorted(set((changed + untracked).decode().strip('\0').split('\0')) - {''})
    snapshot = {name: (blob(head, name), Path(name).read_bytes()) for name in names if Path(name).is_file()}
    snapshot = {p: pair for p, pair in snapshot.items() if pair[0] != pair[1]}
    if not snapshot:
        print('[persist] no generated changes'); return
    with tempfile.TemporaryDirectory(prefix='verification-index-') as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / 'index'))
        for attempt in range(1, attempts + 1):
            git('fetch', '-q', 'origin', 'main')
            parent = git('rev-parse', 'FETCH_HEAD').stdout.decode().strip()
            git('read-tree', parent, env=env)
            count = 0
            for path, (base, local) in snapshot.items():
                remote = blob(parent, path)
                result = merge_file(path, base, local, remote)
                if result == remote:
                    continue
                sha = git('hash-object', '-w', '--stdin', data=result).stdout.decode().strip()
                git('update-index', '--add', '--cacheinfo', '100644', sha, path, env=env)
                count += 1
            if not count:
                print('[persist] changes already present on main'); return
            tree = git('write-tree', env=env).stdout.decode().strip()
            commit = git('commit-tree', tree, '-p', parent, '-m', message).stdout.decode().strip()
            result = git('push', '-q', 'origin', f'{commit}:refs/heads/main', check=False)
            if result.returncode == 0:
                print(f'[persist] saved {count} files on main ({commit[:8]}, attempt {attempt})'); return
            # A stale push does not leave a rebase in progress. Fetch and merge
            # this original snapshot afresh; never drop concurrent rows.
            print(f'::warning::verification push rejected; retry {attempt}/{attempts}')
            if attempt < attempts:
                time.sleep(min(5 * attempt, 20))
    raise RuntimeError('verification persistence failed after all retries')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--message', required=True)
    parser.add_argument('paths', nargs='+')
    args = parser.parse_args()
    persist(args.paths, args.message)
