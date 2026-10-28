#!/usr/bin/env python3
"""Inspect upgrade plans read-only, or explicitly back up and upgrade a database."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import migrations
from ops import erp_ops


def inspect_database(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as c:
        c.execute('PRAGMA query_only=ON')
        return migrations.status(c)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'plan', 'apply'))
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--backup-directory', type=Path)
    parser.add_argument('--kilograms', action='store_true', help='明确执行旧包价转公斤价；普通升级不执行')
    args = parser.parse_args()
    path = args.database.expanduser().resolve()
    if args.kilograms and args.action != 'apply': parser.error('--kilograms 只能用于 apply')
    if args.action != 'apply':
        result = inspect_database(path)
    else:
        # A separate process must own deployment maintenance; this tool does not
        # stop a running web worker or guess whether live business has paused.
        backup = erp_ops.backup_database(path, args.backup_directory or path.parent / 'backups') if path.exists() else None
        import server
        server.DB = path
        # init_db owns one complete transaction for automatic upgrade steps.
        server.init_db(demo=False,convert_billing=args.kilograms)
        result = {**inspect_database(path), 'backup': backup}
    print(json.dumps({'ok': True, **result}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (migrations.MigrationError, sqlite3.Error, ValueError, OSError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        sys.exit(1)
