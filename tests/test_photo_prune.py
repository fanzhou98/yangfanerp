"""Driver photo retention: archive old settled orders, never delete open ones."""
import json
import sqlite3
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

from ops import erp_ops

NOW = date(2026, 11, 4)
AUDIT = "CREATE TABLE audit(id INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT,role TEXT,action TEXT,entity TEXT,before_json TEXT,after_json TEXT, actor_id TEXT NOT NULL DEFAULT '', actor_name TEXT NOT NULL DEFAULT '', request_id TEXT NOT NULL DEFAULT '', prev_hash TEXT NOT NULL DEFAULT '', hash TEXT NOT NULL DEFAULT '')"


def order(state, business_date, reviewed_at=None, review_return=None):
    return {"state": state, "business_date": business_date, "reviewed_at": reviewed_at,
            "updated_at": reviewed_at, "review_return": review_return or {},
            "customer_id": "C001", "customer_name": "测试客户", "lines": []}


class PhotoPruneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "erp.db"
        self.photos = self.root / "driver-photos"
        self.photos.mkdir()
        self.archive = self.root / "photo-archives"
        self.c = sqlite3.connect(self.db)
        self.c.execute("CREATE TABLE orders(id TEXT PRIMARY KEY,payload TEXT NOT NULL)")
        self.c.execute("CREATE TABLE driver_photos(order_id TEXT NOT NULL,kind TEXT NOT NULL,at TEXT NOT NULL,driver_id TEXT NOT NULL DEFAULT '',customer_id TEXT NOT NULL DEFAULT '',path TEXT NOT NULL,mime TEXT NOT NULL DEFAULT 'image/jpeg',bytes INTEGER NOT NULL DEFAULT 0,meta TEXT NOT NULL DEFAULT '{}',PRIMARY KEY(order_id,kind))")
        self.c.execute("CREATE TABLE factory_settings(id TEXT PRIMARY KEY,version INTEGER NOT NULL,payload TEXT NOT NULL)")
        self.c.execute(AUDIT)
        self.c.execute("INSERT INTO factory_settings VALUES('default',1,?)", (json.dumps({"driver_photo_keep_days": "180"}),))
        self.c.row_factory = sqlite3.Row

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def add(self, oid, o, month="01", day="01"):
        self.c.execute("INSERT INTO orders VALUES(?,?)", (oid, json.dumps(o)))
        at = f"2025-{month}-{day}T10:00:00+08:00"
        path = self.photos / "2025" / month / f"{oid}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"photo-" + oid.encode())
        self.c.execute("INSERT INTO driver_photos(order_id,kind,at,path,bytes) VALUES(?,?,?,?,?)",
                       (oid, "weight-P001", at, str(path), path.stat().st_size))
        self.c.commit()

    def test_prune_only_old_settled_undisputed_orders(self):
        self.add("OLD", order("reviewed", "2025-01-01", "2025-06-01"))
        self.add("GRACE", order("reviewed", "2025-01-01", "2026-10-30"))
        self.add("OPEN", order("dispatched", "2025-01-01"))
        self.add("DISPUTE", order("reviewed", "2025-01-01", "2025-06-01", {"status": "pending"}))
        self.add("RECENT", order("reviewed", "2026-10-01", "2026-10-02"))
        preview = erp_ops.photo_prune(self.db, self.photos, self.archive, now=NOW)
        self.assertTrue(preview["dry_run"])
        self.assertEqual(preview["deleted_photos"], 1)
        self.assertEqual(self.c.execute("SELECT count(*) FROM driver_photos").fetchone()[0], 5)
        result = erp_ops.photo_prune(self.db, self.photos, self.archive, dry_run=False, now=NOW)
        self.assertEqual(result["deleted_photos"], 1)
        self.assertEqual([m["month"] for m in result["months"]], ["2025-01"])
        self.assertEqual(self.c.execute("SELECT count(*) FROM driver_photos").fetchone()[0], 4)
        with zipfile.ZipFile(self.archive / "driver-photos-2025-01.zip") as z:
            self.assertEqual(z.namelist(), ["2025/01/OLD.jpg"])
        self.assertFalse((self.photos / "2025" / "01" / "OLD.jpg").exists())
        self.assertEqual(self.c.execute("SELECT action FROM audit").fetchone()[0], "归档并清理司机照片")

    def test_keep_days_parameter_and_default(self):
        self.assertEqual(erp_ops.photo_keep_days(self.db), 180)
        self.assertEqual(erp_ops.photo_keep_days(self.db, 365), 365)
        self.assertEqual(erp_ops.photo_keep_days(self.db, 1), 30)
        self.assertEqual(erp_ops.photo_keep_days(self.db, 9999), 3650)


if __name__ == "__main__":
    unittest.main()
