"""대시보드 틀(template.html)에 데이터를 넣어 완성된 페이지(index.html)를 만든다.

사용법: python3 render.py <template.html> <data.b64> <index.html>
"""
import sys

TPL, DATA, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
tpl = open(TPL, encoding='utf-8').read()
data = open(DATA, encoding='utf-8').read().strip()
assert '__DATA__' in tpl, '틀에 __DATA__ 자리가 없습니다'

# 틀은 <title>·<style>로 시작하고 그 뒤가 본문이므로, 완전한 HTML 문서로 감싼다
cut = tpl.index('</style>') + len('</style>')
head, body = tpl[:cut], tpl[cut:]
page = ('<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<style>html{color-scheme:light}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>\n'
        + head + '\n</head>\n<body>\n' + body.replace('__DATA__', data) + '\n</body>\n</html>\n')
open(OUT, 'w', encoding='utf-8').write(page)
print(f'{OUT} 생성 · {len(page) / 1e6:.2f}MB')
