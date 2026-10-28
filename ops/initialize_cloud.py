#!/usr/bin/env python3
"""Explicit database initialization/migration, never invoked by the web worker."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--new', action='store_true', help='refuse an existing database')
    args = parser.parse_args()
    path = args.database.resolve()
    if args.new and path.exists():
        parser.error('新库目标已存在，拒绝覆盖')
    server.DB = path
    # This explicit deploy command keeps the prior kilogram-conversion policy.
    server.init_db(demo=False,convert_billing=True)
    path.chmod(0o600)
    print('数据库结构初始化完成；未建立默认登录账号。')


if __name__ == '__main__':
    main()
