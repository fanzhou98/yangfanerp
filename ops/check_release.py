#!/usr/bin/env python3
"""Validate the release archive, manifest and current source bytes without writes."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
try:
    from .build_release import release_files
except ImportError:
    from build_release import release_files


def check(root):
    root = Path(root)
    version = (root / 'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('VERSION格式无效')
    package = root / 'output' / 'releases' / ('yangfan-erp-' + version + '.tar.gz')
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    if digest != package.with_suffix('.gz.sha256').read_text().split()[0]:
        raise ValueError('发布包SHA-256不一致')
    with tarfile.open(package) as archive:
        members = {}
        for item in archive.getmembers():
            path = PurePosixPath(item.name)
            if path.is_absolute() or '..' in path.parts or not item.isfile():
                raise ValueError('包内存在不安全路径或非普通文件')
            name = str(path)
            if name in members:
                raise ValueError('包内路径重复')
            if any(part in ('data', 'tests', 'docs', '__pycache__') for part in path.parts):
                raise ValueError('发布包含有禁止的目录')
            members[name] = item
        def read(name):
            return archive.extractfile(members[name]).read()
        manifest = json.loads(read('release.json'))
        if read('VERSION').decode().strip() != version or manifest.get('version') != version:
            raise ValueError('包内版本与当前VERSION不一致')
        if manifest.get('data_included') is not False:
            raise ValueError('发布清单未声明排除业务库')
        files = manifest.get('files')
        if not isinstance(files, dict) or set(members) != set(files) | {'release.json'}:
            raise ValueError('包内容与清单不一致')
        if set(files) != {str(path) for path in release_files(root)}:
            raise ValueError('发布清单与构建白名单不一致')
        for name, expected in files.items():
            if hashlib.sha256(read(name)).hexdigest() != expected:
                raise ValueError('包内文件哈希错误：' + name)
            source = root / name
            if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
                raise ValueError('当前源码与发布包不一致：' + name)
    return {'ok': True, 'version': version, 'files': len(files), 'sha256': digest}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.root), ensure_ascii=False))
    except (OSError, ValueError, KeyError, IndexError, tarfile.TarError) as error:
        parser.exit(1, '发布包检查失败：' + str(error) + '\n')
