#!/usr/bin/env python3
"""CSP 内联样式守卫：web/*.js 或 web/*.html 里出现 style="…" 即判失败。

服务端 CSP 为 style-src 'self'（server.py 的 _security_headers），
浏览器会整段丢弃 style 属性，样式静默失效、控制台不报警。
页面样式必须写进 web/style.css 的类里。

确属打印窗口、导出片段等不受页面 CSP 约束的场景，可在该行加
注释 `csp-allow-inline-style` 说明原因后放行。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(r"""style\s*=\s*["']""")
ALLOW = 'csp-allow-inline-style'


def offenders():
    hits = []
    for path in sorted(list((ROOT / 'web').glob('*.js')) + list((ROOT / 'web').glob('*.html'))):
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if PATTERN.search(line) and ALLOW not in line:
                hits.append((path.relative_to(ROOT).as_posix(), number, line.strip()[:120]))
    return hits


def main():
    hits = offenders()
    if not hits:
        print('内联样式 0 处（CSP style-src self 会丢弃 style 属性）')
        return 0
    print('发现内联样式，CSP 会整段丢弃 style 属性，请改为 web/style.css 中的类：')
    for path, number, text in hits:
        print(f'  {path}:{number}  {text}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
