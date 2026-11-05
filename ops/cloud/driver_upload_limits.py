"""Apply only the two driver photo locations to an existing nginx site."""
from pathlib import Path
import subprocess
import sys


def updated_config(current, template):
    marker = '    location = /api/auth/login {'
    start = template.index('    # Driver photos:')
    locations = template[start:template.index(marker)]
    if locations in current:
        return current
    if any('location = '+path in current for path in ('/api/driver/weights', '/api/driver/returns')):
        raise ValueError('司机照片路由已有不同配置，请先核对；不覆盖自定义配置')
    if current.count(marker) != 1:
        raise ValueError('未找到唯一ERP登录路由，请先核对站点配置')
    return current.replace(marker, locations+marker, 1)


def main():
    path = Path(sys.argv[1])
    template = Path(__file__).with_name('nginx-https.conf.template').read_text()
    old = path.read_text()
    new = updated_config(old, template)
    if new == old:
        return
    backup = path.with_name(path.name+'.before-driver-photo-limits')
    with backup.open('x') as f:
        f.write(old)
    path.write_text(new)
    try:
        subprocess.run(['nginx', '-t'], check=True)
    except BaseException:
        path.write_text(old)
        raise


if __name__ == '__main__':
    main()
