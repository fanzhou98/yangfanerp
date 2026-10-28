"""Verify a local unpacked release and copy only manifest-listed regular files."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ops.build_release import MODULES


def prepare(source, destination):
    manifest = json.loads((source / 'release.json').read_text())
    version = manifest['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version) or manifest['data_included'] is not False:
        raise ValueError('发布版本或数据范围不正确')
    for name, digest in manifest['files'].items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or path.parts[0] not in {*MODULES, 'web', 'ops'}:
            raise ValueError('发布包包含不允许的路径')
        item = source / path
        if item.is_symlink() or not item.is_file() or source.resolve() not in item.resolve().parents:
            raise ValueError('发布文件类型不正确')
        if hashlib.sha256(item.read_bytes()).hexdigest() != digest:
            raise ValueError('发布文件校验失败: ' + name)
    target = destination / version
    target.mkdir(parents=True, exist_ok=False)
    for name in manifest['files']:
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, dest)
        dest.chmod(0o755 if dest.suffix == '.sh' else 0o644)
    shutil.copyfile(source / 'release.json', target / 'release.json')
    return target


if __name__ == '__main__':
    print(prepare(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()))
