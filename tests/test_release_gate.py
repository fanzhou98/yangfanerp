"""Release decisions must reflect package bytes and actual browser execution."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from ops.build_release import release_files
from ops.check_release import check

ROOT = Path(__file__).resolve().parents[1]


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='erp-release-gate-')
        self.root = Path(self.temp.name)
        for path in release_files(ROOT):
            dest = self.root / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, dest)
        shutil.copyfile(ROOT / 'ops/release_gate.sh', self.root / 'ops/release_gate.sh')
        (self.root / 'ops/quick_check.sh').write_text('exit 0\n')
        (self.root / 'ops/browser_check.sh').write_text('echo "浏览器回归通过"\n')

    def tearDown(self):
        self.temp.cleanup()

    def package(self):
        files = release_files(self.root)
        version = (self.root / 'VERSION').read_text().strip()
        package = self.root / 'output/releases' / ('yangfan-erp-' + version + '.tar.gz')
        package.parent.mkdir(parents=True, exist_ok=True)
        manifest = {'version': version, 'data_included': False, 'files': {str(p): hashlib.sha256((self.root / p).read_bytes()).hexdigest() for p in files}}
        with tarfile.open(package, 'w:gz') as archive:
            for path in files:
                archive.add(self.root / path, arcname=str(path))
            raw = json.dumps(manifest).encode()
            member = tarfile.TarInfo('release.json'); member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
        package.with_suffix('.gz.sha256').write_text(hashlib.sha256(package.read_bytes()).hexdigest() + '  ' + package.name + '\n')
        return package

    def gate(self, *args):
        result = subprocess.run(['bash', str(self.root / 'ops/release_gate.sh'), *args], capture_output=True, text=True, timeout=20)
        self.assertNotIn('unbound variable', result.stderr)
        return result

    def test_exact_current_package_can_pass(self):
        self.package()
        self.assertTrue(check(self.root)['ok'])
        self.assertEqual(self.gate().returncode, 0)

    def test_missing_package_cannot_pass(self):
        self.assertNotEqual(self.gate().returncode, 0)

    def test_source_changed_after_packaging_cannot_pass(self):
        self.package()
        (self.root / 'server.py').write_text('# changed after validation\n')
        self.assertNotEqual(self.gate().returncode, 0)

    def test_checksum_mismatch_cannot_pass(self):
        package = self.package()
        package.with_suffix('.gz.sha256').write_text('0' * 64 + '  wrong.tar.gz\n')
        self.assertNotEqual(self.gate().returncode, 0)

    def test_browser_skip_cannot_pass(self):
        self.package()
        (self.root / 'ops/browser_check.sh').write_text('echo "skip: no browser"\nexit 0\n')
        self.assertNotEqual(self.gate().returncode, 0)
        self.assertNotEqual(self.gate('--no-browser').returncode, 0)

    def test_manifest_omitting_required_file_cannot_pass(self):
        package = self.package()
        with tarfile.open(package) as archive:
            content = {m.name: archive.extractfile(m).read() for m in archive.getmembers()}
        content.pop('server.py')
        manifest = json.loads(content['release.json']); manifest['files'].pop('server.py')
        content['release.json'] = json.dumps(manifest).encode()
        with tarfile.open(package, 'w:gz') as archive:
            for name, raw in content.items():
                member = tarfile.TarInfo(name); member.size = len(raw)
                archive.addfile(member, io.BytesIO(raw))
        package.with_suffix('.gz.sha256').write_text(hashlib.sha256(package.read_bytes()).hexdigest() + '  ' + package.name + '\n')
        self.assertNotEqual(self.gate().returncode, 0)
