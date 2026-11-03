import unittest, io, zipfile
import data_package

class Stub:
    def execute(self, sql, args=()):
        return []

class DataPackageTests(unittest.TestCase):
    def test_empty_range_builds_all_sheets_and_valid_zip(self):
        sheets = data_package.build(Stub(), '2026-11-01', '2026-11-30')
        names = [s[0] for s in sheets]
        self.assertEqual(names, data_package.SHEETS)
        for name, headers, rows in sheets:
            self.assertTrue(headers)
            self.assertIsInstance(rows, list)
        raw = data_package.xlsx(sheets)
        self.assertTrue(raw.startswith(b'PK'))
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = z.namelist()
            self.assertIn('[Content_Types].xml', names)
            self.assertIn('xl/workbook.xml', names)
            self.assertEqual(len([n for n in names if n.startswith('xl/worksheets/sheet')]), len(data_package.SHEETS))
            wb = z.read('xl/workbook.xml').decode()
            for sheet in data_package.SHEETS:
                self.assertIn(sheet, wb)

    def test_save_writes_month_file(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            info = data_package.save(Stub(), '2026-11', tmp)
            self.assertTrue(info['path'].endswith('ERP数据包-2026-11.xlsx'))
            self.assertEqual(info['start'], '2026-11-01')
            self.assertEqual(info['end'], '2026-11-30')
            self.assertTrue(os.path.getsize(info['path']) > 1000)

    def test_missing_flags_closed_month_without_file(self):
        import tempfile, os
        class Closed(Stub):
            def execute(self, sql, args=()):
                return [('{"month":"2026-09","state":"closed"}',)]
        with tempfile.TemporaryDirectory() as tmp:
            original = data_package._dirs
            data_package._dirs = lambda: [tmp]
            try:
                self.assertEqual([x['month'] for x in data_package.missing(Closed())], ['2026-09'])
                with open(os.path.join(tmp, 'ERP数据包-2026-09.xlsx'), 'wb') as f:
                    f.write(b'x' * 200)
                self.assertEqual(data_package.missing(Closed()), [])
            finally:
                data_package._dirs = original

    def test_photo_bundle_includes_excel_photo_and_manifest(self):
        import tempfile, os
        class PhotoStub(Stub):
            def execute(self, sql, args=()):
                if 'driver_photos' in sql:
                    return [('SO-1','weight','2026-11-01 10:00:00',photo_path,'C001',0,'{}')]
                if 'FROM customers' in sql:
                    return [('C001','岐峰')]
                return []
        with tempfile.TemporaryDirectory() as tmp:
            photo_path = os.path.join(tmp, 'weight.jpg')
            with open(photo_path, 'wb') as f: f.write(b'JPEG-PHOTO')
            raw, name, count = data_package.photo_bundle(PhotoStub(), '2026-11-01', '2026-11-30')
            self.assertEqual(count, 1)
            self.assertTrue(name.endswith('-photos.zip'))
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                names = z.namelist()
                self.assertTrue(any(n.endswith('.xlsx') for n in names))
                self.assertTrue(any(n.startswith('司机照片/') and n.endswith('.jpg') for n in names))
                self.assertIn('司机照片清单.csv', names)
                self.assertEqual(z.read([n for n in names if n.endswith('.jpg')][0]), b'JPEG-PHOTO')

if __name__ == '__main__':
    unittest.main()
