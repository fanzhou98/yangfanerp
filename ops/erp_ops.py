#!/usr/bin/env python3
"""Read-only checks, consistent backups and isolated restore drills (stdlib only).

Never imports server.py, starts migrations, deletes old backups or overwrites a DB.
Reports contain aggregate checks, not customer data, credentials or SQL values.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone, timedelta
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audit_chain
import tempfile
import time
from urllib.parse import urlsplit
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TABLES = {"customers", "products", "orders", "receipts", "audit", "meta"}
PAYLOAD_TABLES = {"fund_accounts", "fund_assignments", "fund_transfers", "purchase_payees", "purchase_charges", "supplier_categories", "suppliers", "purchase_orders", "purchase_receipts", "purchase_payments", "orders", "receipts", "trial_archives", "archived_orders", "dispatch_plans", "warehouse_plans", "sales_returns",
                  "driver_return_submissions", "driver_weight_submissions", "driver_return_requests", "asset_records", "asset_submissions", "payroll_records", "factory_daily", "factory_runs", "factory_groups", "factory_employees", "factory_attendance", "factory_schedules", "factory_scrap", "factory_settings", "processing_batches", "stock_closings", "byproduct_statements", "statement_documents", "material_entries", "indirect_expenses", "expense_reviews", "expense_payments", "byproduct_sales", "resource_periods"}


class OpsError(Exception):
    """A safe operational error message, suitable for stdout."""


def existing_file(path: Path) -> Path:
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise OpsError("输入必须是存在的普通数据库文件，不能是符号链接")
    return path.resolve()


def readonly(path: Path):
    """mode=ro preserves WAL visibility while preventing accidental writes/creation."""
    c = sqlite3.connect(existing_file(path).as_uri() + "?mode=ro", uri=True, timeout=5)
    c.execute("PRAGMA query_only=ON")
    c.execute("PRAGMA busy_timeout=5000")
    return c


def quote_identifier(name):
    return '"' + name.replace('"', '""') + '"'


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def check_database(path: Path, full=False):
    path = existing_file(path)
    with closing(readonly(path)) as c:
        c.execute("BEGIN")
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if not REQUIRED_TABLES <= tables:
            raise OpsError("数据库缺少 ERP 必需表，未进行备份或恢复")
        pragma = "integrity_check" if full else "quick_check"
        integrity = [r[0] for r in c.execute("PRAGMA " + pragma)] == ["ok"]
        foreign_keys_ok = c.execute("PRAGMA foreign_key_check").fetchone() is None
        counts = {name: c.execute("SELECT count(*) FROM " + quote_identifier(name)).fetchone()[0]
                  for name in sorted(tables)}
        invalid_payloads = 0
        for name in sorted(PAYLOAD_TABLES & tables):
            columns = {row[1] for row in c.execute("PRAGMA table_info(" + quote_identifier(name) + ")")}
            if "payload" not in columns:
                continue
            for (raw,) in c.execute("SELECT payload FROM " + quote_identifier(name)):
                try:
                    valid = isinstance(json.loads(raw), dict)
                except (ValueError, TypeError):
                    valid = False
                invalid_payloads += not valid
        statement_hash_mismatches = 0
        for table in ('statement_documents','byproduct_statements'):
            if table not in tables:continue
            for raw, expected in c.execute('SELECT payload,content_hash FROM '+table):
                if not isinstance(raw, str) or hashlib.sha256(raw.encode("utf-8")).hexdigest() != expected:
                    statement_hash_mismatches += 1
        journal_mode = c.execute("PRAGMA journal_mode").fetchone()[0]
        schema_version = c.execute("PRAGMA user_version").fetchone()[0]
    return {"ok": integrity and foreign_keys_ok and not invalid_payloads and not statement_hash_mismatches,
            "check": pragma, "integrity_ok": integrity, "foreign_keys_ok": foreign_keys_ok,
            "invalid_payload_rows": invalid_payloads, "statement_hash_mismatches": statement_hash_mismatches,
            "table_counts": counts, "user_version": schema_version, "journal_mode": journal_mode,
            "database_bytes": path.stat().st_size, "database_mode": oct(path.stat().st_mode & 0o777),
            "disk_free_bytes": shutil.disk_usage(path.parent).free}


def logical_hash(path: Path):
    """Hash sorted typed rows and schema without exporting any raw value."""
    digest = hashlib.sha256()
    with closing(readonly(path)) as c:
        c.execute("BEGIN")
        objects = c.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        digest.update(json.dumps(objects, ensure_ascii=False, separators=(",", ":")).encode())
        tables = sorted(row[1] for row in objects if row[0] == "table")
        for name in tables:
            columns = [row[1] for row in c.execute("PRAGMA table_info(" + quote_identifier(name) + ")")]
            selected = ",".join(quote_identifier(col) for col in columns)
            digest.update(name.encode())
            for row in c.execute("SELECT " + selected + " FROM " + quote_identifier(name) + " ORDER BY " + selected):
                typed = [[type(value).__name__, value.hex() if isinstance(value, bytes) else value] for value in row]
                digest.update(json.dumps(typed, ensure_ascii=False, separators=(",", ":")).encode())
                digest.update(b"\n")
    return digest.hexdigest()


def private_directory(directory: Path):
    directory = Path(directory).expanduser()
    if directory.is_symlink():
        raise OpsError("输出目录不能是符号链接")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.stat().st_mode & 0o777 != 0o700:
        os.chmod(directory, 0o700)
    return directory.resolve()


def publish_new(temporary: Path, target: Path):
    """An atomic no-replace publication; unlike replace(), cannot overwrite a file."""
    os.link(temporary, target)
    temporary.unlink()


def write_private_json(path: Path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def read_small_json(path: Path):
    path = existing_file(path)
    if path.stat().st_size > 1024 * 1024:
        raise OpsError("校验清单过大，请人工核对来源")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise OpsError("校验清单格式无效") from None


def new_candidate_path(target: Path):
    target = Path(target).expanduser().absolute()
    if target.resolve() == (ROOT / "data" / "erp.db").resolve():
        raise OpsError("禁止直接恢复到运行数据库；请使用新的恢复候选文件并按维护手册切换")
    if any(Path(str(target) + suffix).exists() or Path(str(target) + suffix).is_symlink()
           for suffix in ("", "-journal", "-wal", "-shm", ".recovery.json", ".finalized-recovery.json")):
        raise OpsError("目标或其 SQLite 旁路 / 恢复记录文件已存在，拒绝覆盖")
    private_directory(target.parent)
    return target


def copy_database(source: Path, target: Path, timeout=60):
    """SQLite Online Backup API, private temporary file, bounded busy retry."""
    if target.exists() or target.is_symlink():
        raise OpsError("目标已存在，工具拒绝覆盖")
    temporary = None
    deadline = time.monotonic() + timeout

    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise OpsError("备份超时，已取消；原数据库保持不变")

    try:
        fd, name = tempfile.mkstemp(prefix=".erp-copy-", suffix=".partial", dir=target.parent)
        os.close(fd)
        temporary = Path(name)
        with closing(readonly(source)) as src, closing(sqlite3.connect(temporary)) as dst:
            src.backup(dst, pages=128, progress=progress, sleep=0.1)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        report = check_database(temporary, full=True)
        if not report["ok"]:
            raise OpsError("副本校验未通过，未发布备份或恢复文件")
        publish_new(temporary, target)
        return report
    except FileExistsError:
        raise OpsError("目标已存在，工具拒绝覆盖") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
            for suffix in ("-journal", "-wal", "-shm"):
                Path(str(temporary) + suffix).unlink(missing_ok=True)


def backup_database(database: Path, directory: Path):
    source = existing_file(database)
    directory = private_directory(directory)
    filename = "erp-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + secrets.token_hex(6) + ".db"
    target = directory / filename
    report = copy_database(source, target)
    manifest = {"format": "erp-sqlite-backup-v1", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "sha256": file_hash(target), "logical_sha256": logical_hash(target), "checks": report}
    manifest_path = Path(str(target) + ".manifest.json")
    write_private_json(manifest_path, manifest)
    return {"ok": True, "backup": str(target), "manifest": str(manifest_path), "sha256": manifest["sha256"], "checks": report}


def _backup_time(path: Path):
    name = path.name
    if not name.startswith("erp-") or not name.endswith(".db"):
        return None
    stamp = name.split("-")[1]
    try:
        return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def prune_backups(directory: Path, now=None, keep_hourly_days=7, keep_daily_days=60,
                  keep_monthly_months=24, min_keep=30, dry_run=False):
    """Tiered retention: all <7d, one per day 7-60d, one per month >60d, keep newest min_keep."""
    directory = existing_directory(directory) if "existing_directory" in globals() else Path(directory)
    if not directory.is_dir():
        raise ValueError("备份目录不存在")
    now = now or datetime.now(timezone.utc)
    db_files = []
    for path in directory.glob("erp-*.db"):
        at = _backup_time(path)
        if at is not None:
            db_files.append((at, path))
    db_files.sort(reverse=True)
    keep = {p for _, p in db_files[:max(1, min_keep)]}
    seen_days, seen_months = set(), set()
    for at, path in db_files:
        age = (now - at).total_seconds() / 86400
        if age < keep_hourly_days:
            keep.add(path)
        elif age < keep_daily_days:
            day = at.date()
            if day not in seen_days:
                seen_days.add(day); keep.add(path)
        else:
            month = (at.year, at.month)
            if month not in seen_months:
                seen_months.add(month); keep.add(path)
    removed = []
    for _, path in db_files:
        if path in keep:
            continue
        removed.append(path.name)
        if not dry_run:
            path.unlink(missing_ok=True)
            Path(str(path) + ".manifest.json").unlink(missing_ok=True)
    return {"ok": True, "kept": len(keep), "removed": len(removed), "removed_files": sorted(removed), "dry_run": bool(dry_run)}


def verified_manifest(backup: Path):
    backup = existing_file(backup)
    manifest = read_small_json(Path(str(backup) + ".manifest.json"))
    if not isinstance(manifest, dict) or manifest.get("format") != "erp-sqlite-backup-v1":
        raise OpsError("不是本工具生成的备份清单")
    if manifest.get("sha256") != file_hash(backup):
        raise OpsError("备份文件校验不一致，拒绝恢复")
    if manifest.get("logical_sha256") != logical_hash(backup):
        raise OpsError("备份内容校验不一致，拒绝恢复")
    return manifest


def restore_new(backup: Path, target: Path):
    backup = existing_file(backup)
    target = new_candidate_path(target)
    manifest = verified_manifest(backup)
    report = copy_database(backup, target)
    if logical_hash(target) != manifest["logical_sha256"]:
        target.unlink()
        raise OpsError("恢复内容不一致，已删除本次新建的候选文件")
    provenance = {"format": "erp-recovery-candidate-v1", "backup_sha256": manifest["sha256"],
                  "sha256": file_hash(target), "logical_sha256": manifest["logical_sha256"]}
    marker = Path(str(target) + ".recovery.json")
    write_private_json(marker, provenance)
    return {"ok": True, "candidate": str(target), "recovery_record": str(marker),
            "logical_sha256": manifest["logical_sha256"], "requires_finalize": True, "checks": report}


def finalize_recovery(database: Path, target: Path):
    """Only modify a NEW copy of a verified restore candidate; never the input."""
    source = existing_file(database)
    if source == (ROOT / "data" / "erp.db").resolve():
        raise OpsError("不能整理运行数据库；只接受本工具新建的恢复候选文件")
    provenance = read_small_json(Path(str(source) + ".recovery.json"))
    if (not isinstance(provenance, dict) or provenance.get("format") != "erp-recovery-candidate-v1"
            or not isinstance(provenance.get("backup_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", provenance["backup_sha256"])
            or provenance.get("sha256") != file_hash(source)
            or provenance.get("logical_sha256") != logical_hash(source)):
        raise OpsError("恢复候选来源或内容校验不一致，拒绝整理")
    target = new_candidate_path(target)
    with tempfile.TemporaryDirectory(prefix=".erp-finalize-", dir=target.parent) as work:
        candidate = Path(work) / "candidate.db"
        copy_database(source, candidate)
        if logical_hash(candidate) != provenance["logical_sha256"]:
            raise OpsError("恢复候选在复制期间发生变化，未发布最终候选")
        with closing(sqlite3.connect(candidate)) as c:
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("BEGIN IMMEDIATE")
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            sessions = c.execute("SELECT count(*) FROM auth_sessions").fetchone()[0] if "auth_sessions" in tables else 0
            if "auth_sessions" in tables:
                c.execute("DELETE FROM auth_sessions")
            if "auth_login_limits" in tables:
                c.execute("DELETE FROM auth_login_limits")
            c.execute("INSERT INTO meta(key,value) VALUES('business_data_epoch',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (secrets.token_hex(12),))
            details = {"sessions_invalidated": sessions, "business_epoch_rotated": True, "account_review_required": True}
            timestamp = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
            record = {"at": timestamp, "role": "系统", "action": "离线恢复候选安全整理（旧会话失效与新数据轮次）",
                      "entity": "recovery", "before_json": "null", "after_json": json.dumps(details, ensure_ascii=False, separators=(",", ":")),
                      "actor_id": "", "actor_name": "离线维护命令（未登录）", "request_id": "RECOVERY-" + secrets.token_hex(12)}
            audit_chain.append(c, [record.get(name, "") for name in audit_chain.FIELDS])
            if "security_events" in tables:
                c.execute("INSERT INTO security_events(at,action,actor_id,entity,details_json) VALUES(?,? ,NULL,?,?)",
                          (int(time.time()), "recovery.finalized", "recovery", record["after_json"]))
            active_admins = c.execute("SELECT count(*) FROM auth_users WHERE active=1 AND role='管理员'").fetchone()[0] if "auth_users" in tables else 0
            c.commit()
        report = check_database(candidate, full=True)
        if not report["ok"]:
            raise OpsError("最终恢复候选校验未通过，未发布文件")
        finalized = {"format": "erp-finalized-recovery-v1", "backup_sha256": provenance["backup_sha256"],
                     "sha256": file_hash(candidate), "logical_sha256": logical_hash(candidate),
                     "sessions_invalidated": sessions, "business_epoch_rotated": True,
                     "active_admin_count": active_admins, "account_review_required": True}
        try:
            publish_new(candidate, target)
        except FileExistsError:
            raise OpsError("目标已存在，工具拒绝覆盖") from None
        marker = Path(str(target) + ".finalized-recovery.json")
        write_private_json(marker, finalized)
    return {"ok": True, "candidate": str(target), "recovery_record": str(marker), "checks": report,
            "sessions_invalidated": sessions, "business_epoch_rotated": True,
            "active_admin_count": active_admins, "account_review_required": True,
            "warning": "账号启停与管理员名单随备份回退；请在开放访问前核查恢复时点之后的账号变更"}


def restore_drill(backup: Path, directory: Path | None = None):
    parent = private_directory(directory) if directory is not None else None
    with tempfile.TemporaryDirectory(prefix="erp-restore-drill-", dir=parent) as work:
        result = restore_new(backup, Path(work) / "restored.db")
        return {"ok": result["ok"], "isolated_restore": True, "temporary_copy_removed": True,
                "logical_sha256": result["logical_sha256"], "checks": result["checks"]}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OpsError("健康检查不跟随重定向，请核对本机服务地址")


def health(url: str):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise OpsError("健康检查需使用不含凭据的本机 HTTP 地址")
    try:
        local = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        local = False
    if not local or parsed.path not in ("", "/"):
        raise OpsError("健康检查仅允许本机服务根地址")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    started = time.monotonic()
    try:
        with opener.open(url.rstrip("/") + "/api/health", timeout=5) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise OpsError("健康检查响应过大")
            payload = json.loads(raw)
            ok = response.status == 200 and isinstance(payload, dict) and payload.get("status") == "ok"
    except (urllib.error.URLError, ValueError, TimeoutError):
        raise OpsError("本机健康检查未通过，请检查进程、端口及数据库；响应内容未记录") from None
    return {"ok": ok, "http_health_ok": ok, "elapsed_ms": round((time.monotonic() - started) * 1000)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check-db", help="只读检查，不运行迁移")
    check.add_argument("--database", required=True, type=Path)
    check.add_argument("--full", action="store_true")
    prune = commands.add_parser("prune", help="按保留策略清理过期备份（7天全留 / 7-60天每天1份 / 60天以上每月1份，至少保留30份）")
    prune.add_argument("--directory", required=True, type=Path)
    prune.add_argument("--keep-hourly-days", type=int, default=7)
    prune.add_argument("--keep-daily-days", type=int, default=60)
    prune.add_argument("--keep-monthly-months", type=int, default=24)
    prune.add_argument("--min-keep", type=int, default=30)
    prune.add_argument("--dry-run", action="store_true")
    backup = commands.add_parser("backup", help="在线一致性备份，生成独立清单")
    backup.add_argument("--database", required=True, type=Path)
    backup.add_argument("--destination", required=True, type=Path)
    drill = commands.add_parser("restore-drill", help="在自动清理的临时目录实际恢复并校验")
    drill.add_argument("--backup", required=True, type=Path)
    drill.add_argument("--work-directory", type=Path)
    restore = commands.add_parser("prepare-restore", help="只生成新的恢复候选文件，拒绝覆盖现有目标")
    restore.add_argument("--backup", required=True, type=Path)
    restore.add_argument("--target", required=True, type=Path)
    finalize = commands.add_parser("finalize-recovery", help="从恢复候选新建最终候选，清旧会话、换 epoch 并记审计，不改源文件")
    finalize.add_argument("--database", required=True, type=Path)
    finalize.add_argument("--target", required=True, type=Path)
    probe = commands.add_parser("health", help="只访问本机 /api/health，不获取业务数据")
    probe.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args(argv)
    try:
        if args.command == "check-db":
            result = check_database(args.database, full=args.full)
        elif args.command == "backup":
            result = backup_database(args.database, args.destination)
        elif args.command == "prune":
            result = prune_backups(args.directory, keep_hourly_days=args.keep_hourly_days,
                                   keep_daily_days=args.keep_daily_days, keep_monthly_months=args.keep_monthly_months,
                                   min_keep=args.min_keep, dry_run=args.dry_run)
        elif args.command == "restore-drill":
            result = restore_drill(args.backup, args.work_directory)
        elif args.command == "prepare-restore":
            result = restore_new(args.backup, args.target)
        elif args.command == "finalize-recovery":
            result = finalize_recovery(args.database, args.target)
        else:
            result = health(args.url)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    except OpsError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    except (OSError, sqlite3.Error):
        print(json.dumps({"ok": False, "error": "文件或数据库操作未完成；未输出业务数据或底层错误，请检查路径、权限、空间和文件来源"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
