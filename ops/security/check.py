#!/usr/bin/env python3
"""Read-only production checks. Output only aggregate codes; never raw events."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
import urllib.request


def database_alerts(database, now):
    alerts = []
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=3)) as c:
        c.execute('PRAGMA query_only=ON')
        failures = c.execute("SELECT count(*) FROM security_events WHERE at>=? AND action IN ('auth.login.failed','auth.login.rate_limited')", (now - 300,)).fetchone()[0]
        if failures >= 10:
            alerts.append('LOGIN_FAILURE_BURST')
    return alerts


def backup_alerts(directory, now):
    # A completed pair is required; an orphan/empty backup cannot satisfy freshness.
    pairs = [p for p in directory.glob('*.db') if p.is_file() and p.stat().st_size > 0
             and Path(str(p) + '.manifest.json').is_file()
             and Path(str(p) + '.manifest.json').stat().st_size > 0]
    if not pairs or now - max(p.stat().st_mtime for p in pairs) > 7200:
        return ['BACKUP_STALE']
    return []


def check(database, backups, now=None):
    now = int(time.time()) if now is None else now
    alerts = []
    for unit in ('yangfan-erp.service', 'nginx.service', 'yangfan-erp-backup.timer'):
        try:
            result = subprocess.run(['systemctl', 'is-active', '--quiet', unit], timeout=5, capture_output=True)
            if result.returncode:
                alerts.append('INACTIVE:' + unit)
        except (OSError, subprocess.TimeoutExpired):
            alerts.append('SERVICE_CHECK_FAILED:' + unit)
    try:
        if subprocess.run(['systemctl', 'is-failed', '--quiet', 'yangfan-erp-backup.service'], timeout=5, capture_output=True).returncode == 0:
            alerts.append('BACKUP_SERVICE_FAILED')
    except (OSError, subprocess.TimeoutExpired):
        alerts.append('BACKUP_STATUS_UNKNOWN')
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:8765/api/health', timeout=5) as response:
            payload = json.load(response)
            if response.status != 200 or not isinstance(payload, dict) or payload.get('status') != 'ok':
                alerts.append('HEALTH_FAILED')
    except Exception:
        alerts.append('HEALTH_FAILED')
    try:
        usage = shutil.disk_usage(database.parent)
        if usage.free < max(2 * 1024 ** 3, usage.total * .2):
            alerts.append('DISK_LOW')
    except OSError:
        alerts.append('DISK_CHECK_FAILED')
    try:
        alerts.extend(database_alerts(database, now))
    except (OSError, sqlite3.Error):
        alerts.append('SECURITY_EVENTS_UNREADABLE')
    try:
        alerts.extend(backup_alerts(backups, now))
    except OSError:
        alerts.append('BACKUPS_UNREADABLE')
    return {'ok': not alerts, 'at': now, 'alerts': alerts}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path('/var/lib/yangfan-erp/erp.db'))
    parser.add_argument('--backups', type=Path, default=Path('/var/lib/yangfan-erp/backups'))
    args = parser.parse_args()
    report = check(args.database, args.backups)
    print(json.dumps(report, separators=(',', ':')), flush=True)
    raise SystemExit(0 if report['ok'] else 1)
