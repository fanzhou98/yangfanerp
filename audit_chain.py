"""Append-only audit hash chain: every record binds the one before it.

The chain is tamper-evident, not tamper-proof: anyone with direct database access
can rewrite a row, but doing so without rebuilding every later hash breaks the
chain and `verify` reports the first broken row.
"""
import hashlib
import json

FIELDS = ('at', 'role', 'action', 'entity', 'before_json', 'after_json',
          'actor_id', 'actor_name', 'request_id')
GENESIS = ''


def canonical(row):
    return json.dumps([row.get(field) or '' for field in FIELDS],
                      ensure_ascii=False, separators=(',', ':'))


def digest(row, previous):
    return hashlib.sha256((previous + '|' + canonical(row)).encode()).hexdigest()


def head(c):
    row = c.execute('SELECT hash FROM audit ORDER BY id DESC LIMIT 1').fetchone()
    return row[0] if row and row[0] else GENESIS


def _chained(c):
    return 'hash' in {r[1] for r in c.execute('PRAGMA table_info(audit)')}


def append(c, values):
    """Insert one audit row and return the chain hash it produced.

    Migrations before 092 run against an audit table without the chain columns;
    those rows are chained later by the 092 backfill.
    """
    if not _chained(c):
        c.execute('INSERT INTO audit(' + ','.join(FIELDS) + ') '
                  'VALUES(' + ','.join('?' * len(FIELDS)) + ')', tuple(values))
        return GENESIS
    previous = head(c)
    value = digest(dict(zip(FIELDS, values)), previous)
    c.execute('INSERT INTO audit(' + ','.join(FIELDS) + ',prev_hash,hash) '
              'VALUES(' + ','.join('?' * (len(FIELDS) + 2)) + ')',
              tuple(values) + (previous, value))
    return value


def verify(c):
    """Walk the whole chain; return the first broken row and the total count."""
    previous = GENESIS
    total = 0
    for record in c.execute('SELECT id,' + ','.join(FIELDS) + ',prev_hash,hash '
                            'FROM audit ORDER BY id'):
        total += 1
        row = dict(zip(FIELDS, record[1:1 + len(FIELDS)]))
        stored_prev, stored_hash = record[1 + len(FIELDS)], record[2 + len(FIELDS)]
        if stored_prev != previous or stored_hash != digest(row, previous):
            return {'ok': False, 'total': total, 'broken_id': record[0],
                    'broken_at': row['at'] or '', 'broken_action': row['action'] or '',
                    'basis': '逐行重算 SHA-256：任一行被改动，或中间某行被删除，其后的 previous hash 就对不上'}
        previous = stored_hash
    return {'ok': True, 'total': total, 'broken_id': None, 'broken_at': '',
            'broken_action': '',
            'basis': '逐行重算 SHA-256：任一行被改动，或中间某行被删除，其后的 previous hash 就对不上'}
