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

if __name__ == '__main__':
    unittest.main()
