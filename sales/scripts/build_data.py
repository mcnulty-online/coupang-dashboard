"""쿠팡 판매·재고·발주 CSV → 대시보드 데이터(JSON)

사용법: python3 build_data.py <입력폴더> <출력 json> [과거판매.pkl]
  과거판매.pkl: load_history.py로 만든 과거 판매 이력 (있으면 YoY 탭 데이터 생성)
입력폴더에 아래 파일을 넣어두면 됨 (기간이 겹쳐도 됨, 같은 날짜는 최신 파일 기준)
  - *SALES_ANALYSIS_DAILY_PERFORMANCE*.csv  (판매분석 일별 성과)
  - basic_operation_rocket*.csv              (로켓 기본운영 재고)
  - PO_SKU_LIST*.csv                         (발주 SKU 리스트)
"""
import glob, json, os, sys
from datetime import datetime, timedelta, timezone
import pandas as pd

IN, OUT = sys.argv[1], sys.argv[2]
HIST = sys.argv[3] if len(sys.argv) > 3 else None


def read_hist(path):
    """과거 판매 이력: .csv.gz(GitHub용) 또는 .pkl"""
    if path.endswith('.pkl'):
        return pd.read_pickle(path)
    h = pd.read_csv(path, encoding='utf-8', low_memory=False)
    h['날짜'] = pd.to_datetime(h['날짜'])
    return h

COFFEE = {'기타전통차', '드립백/티백', '라떼분말', '원두', '원두커피믹스', '율무/견과차', '커피믹스', '커피세트'}
DRINK = {'과일음료', '농축액(음료베이스)', '둥글레/옥수수/보리/결명자차', '야채음료', '차음료', '커피음료'}
grp = lambda c: '커피' if c in COFFEE else ('음료' if c in DRINK else '기타')


def load(pattern, date_col, parse):
    """여러 파일을 합치되, 같은 날짜는 파일명이 가장 뒤(최신)인 파일의 행만 남김."""
    files = sorted(glob.glob(os.path.join(IN, pattern)))
    if not files:
        sys.exit(f'입력 파일 없음: {pattern}')
    parts = []
    for rank, f in enumerate(files):
        df = pd.read_csv(f, encoding='utf-8-sig')
        df['d'] = parse(df[date_col])
        df['_rank'] = rank
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    best = df.groupby('d')['_rank'].transform('max')
    df = df[df['_rank'] == best].drop(columns='_rank')
    print(f'{pattern}: 파일 {len(files)}개, {df["d"].min()} ~ {df["d"].max()}, {len(df)}행')
    return df, files


s, sfiles = load('*SALES_ANALYSIS_DAILY_PERFORMANCE*.csv', '날짜', lambda x: pd.to_datetime(x).dt.strftime('%Y-%m-%d'))
o, ofiles = load('basic_operation_rocket*.csv', '날짜', lambda x: pd.to_datetime(x.astype(str), format='%Y%m%d').dt.strftime('%Y-%m-%d'))

# 발주: 여러 파일이면 (발주번호, SKU) 기준 최신 파일 우선
pfiles = sorted(glob.glob(os.path.join(IN, 'PO_SKU_LIST*.csv')))[-1:]   # 가장 최근 발주 파일만 사용
po = pd.concat([pd.read_csv(f, encoding='utf-8-sig').assign(_rank=i) for i, f in enumerate(pfiles)], ignore_index=True) if pfiles else pd.DataFrame()
if len(po):
    po = po.sort_values('_rank').drop_duplicates(['발주번호', 'SKU ID'], keep='last')
    print(f'PO: 파일 {len(pfiles)}개, {len(po)}건, 발주일 {po["발주일"].min()[:10]} ~ {po["발주일"].max()[:10]}')

# 과거 판매 이력을 앞에 이어 붙임 (최근 파일에 있는 날짜는 최근 파일 우선)
s_recent = s
if HIST:
    h0 = read_hist(HIST)
    h0['d'] = h0['날짜'].dt.strftime('%Y-%m-%d')
    h0 = h0[h0['d'] < s['d'].min()]
    s = pd.concat([h0[[c for c in h0.columns if c in s.columns]], s], ignore_index=True)
    print(f'과거 이력 연결: {s["d"].min()} ~ (총 {len(s):,}행)')

# 날짜 축: 판매·재고 중 이른 날짜 ~ 둘 다 있는 마지막 날짜
end = min(s['d'].max(), o['d'].max())
start = min(s['d'].min(), o['d'].min())
days = [d.strftime('%Y-%m-%d') for d in pd.date_range(start, end)]
di = {d: i for i, d in enumerate(days)}
N = len(days)
s = s[s['d'] <= end]; o = o[o['d'] <= end]

sa = s.groupby(['SKU ID', 'd']).agg(
    g=('매출액(GMV)', 'sum'), q=('판매 수량 (SKU ID)', 'sum'), r=('반품 수량', 'sum'),
    c=('매입원가(COGS)', 'sum'), p=('프로모션 발생 매출액', 'sum'),
    v=('조회수', 'sum'), o=('주문건수', 'sum'), pq=('프로모션 발생 판매 수량', 'sum'),
    pmc=('쿠팡 추가 할인가', 'sum')).reset_index()   # PMC = 쿠팡 추가 할인가

o['so'] = (o['품절여부'] == 'YES').astype(int)
o['ctr'] = o['센터'].fillna('미지정')
o['cg'] = o['ctr'].map(lambda c: c if c in ('FC', 'RC') else 'ETC')
oa = o.groupby(['SKU ID', 'd']).agg(st=('현재재고수량', 'sum'), out=('출고수량', 'sum'),
                                    inq=('입고수량', 'sum'), so=('so', 'max')).reset_index()
cgd = o.pivot_table(index=['SKU ID', 'd'], columns='cg', values='현재재고수량', aggfunc='sum', fill_value=0).reset_index()

meta = {}
for sid, r in s.sort_values('d').groupby('SKU ID').tail(1).set_index('SKU ID').iterrows():
    meta[sid] = dict(name=r['SKU명'], cat=r['세부카테고리'], brand=r['브랜드'], sub=r['하위카테고리'])
last_o = o.sort_values('d').groupby('SKU ID').tail(1).set_index('SKU ID')
for sid, r in last_o.iterrows():
    m = meta.setdefault(sid, dict(name=r['SKU 명'], cat=r['세부 카테고리'], brand=r['브랜드'], sub=r['하위 카테고리']))
    m.update(status=r['발주가능상태_세부'], order=r['발주가능상태'], uc=int(r['매입원가']), lastOps=r['d'])
lastday = o[o['d'] == end]
ctr_last = {sid: {c: int(v) for c, v in g.groupby('ctr')['현재재고수량'].sum().sort_values(ascending=False).items() if v > 0}
            for sid, g in lastday.groupby('SKU ID')}
lv = s_recent.sort_values('d').groupby(['SKU ID', '벤더아이템 ID']).tail(1)
for sid, gdf in lv.groupby('SKU ID'):
    n = int(gdf['상품평 수'].sum())
    meta[sid]['reviews'] = n
    meta[sid]['rating'] = round(float((gdf['평균 상품 평점'] * gdf['상품평 수']).sum() / n), 2) if n else None

# 발주 라인 (SKU별)
po_lines = {}
po_only = []
if len(po):
    for sid, g in po.groupby('SKU ID'):
        po_lines[sid] = [[int(r['발주번호']), r['물류센터'], r['입고예정일'], r['발주일'][:10], int(r['확정수량']), int(r['입고수량']),
                          int(r['총발주 매입금']), r['발주현황'], r['발주유형']] for _, r in g.sort_values('입고예정일').iterrows()]
        if sid not in meta:
            po_only.append(dict(id=int(sid), name=g['SKU 이름'].iloc[0], po=po_lines[sid]))

F = ['g', 'q', 'r', 'c', 'p', 'v', 'o', 'pq', 'pmc', 'st', 'out', 'inq', 'so', 'sFC', 'sRC', 'sETC']
skus, idx = [], {}
for sid in sorted(meta):
    m = meta[sid]; idx[sid] = len(skus)
    skus.append(dict(id=int(sid), name=m['name'], cat=m['cat'], brand=m['brand'], sub=m.get('sub'), grp=grp(m['cat']),
                     status=m.get('status', '정보없음'), order=m.get('order', '정보없음'),
                     rating=m.get('rating'), reviews=m.get('reviews', 0),
                     inOps=sid in last_o.index and m.get('lastOps') == end, uc=m.get('uc'), ctr=ctr_last.get(sid, {}),
                     po=po_lines.get(sid, []), **{k: [0] * N for k in F}))
ops_days = set(o['d'])
OPSF = ['st', 'out', 'inq', 'sFC', 'sRC', 'sETC']
for k in skus:   # 재고 리포트가 없는 날은 null (0이면 품절처럼 보이므로)
    for f in OPSF:
        k[f] = [0 if d in ops_days else None for d in days]
for _, r in sa.iterrows():
    k = skus[idx[r['SKU ID']]]; i = di[r['d']]
    for f in ['g', 'q', 'r', 'c', 'p', 'v', 'o', 'pq', 'pmc']:
        k[f][i] = int(r[f])
for _, r in oa.iterrows():
    k = skus[idx[r['SKU ID']]]; i = di[r['d']]
    for f in ['st', 'out', 'inq', 'so']:
        k[f][i] = int(r[f])
for _, r in cgd.iterrows():
    k = skus[idx[r['SKU ID']]]; i = di[r['d']]
    for c in ('FC', 'RC', 'ETC'):
        k['s' + c][i] = int(r.get(c, 0))
ops_start = min(ops_days)
missing_ops = [d for d in days if d >= ops_start and d not in ops_days]


# ---------------- 과거 이력 (YoY) ----------------
hist = None
if HIST:
    h = read_hist(HIST)
    h['d'] = h['날짜'].dt.strftime('%Y-%m-%d')
    cols = ['d', 'SKU ID', 'SKU명', '세부카테고리', '브랜드', '매출액(GMV)', '판매 수량 (SKU ID)', '반품 수량', '매입원가(COGS)',
            '프로모션 발생 매출액', '주문건수', '조회수']
    allS = s[cols].copy()
    allS = allS[allS['d'] <= end]
    allS['ym'] = allS['d'].str[:7]
    months = sorted(allS['ym'].unique())
    mi = {m: i for i, m in enumerate(months)}
    M = len(months)
    # SKU 메타 (현재 목록 우선, 없으면 과거 마지막 이름)
    hm = allS.sort_values('d').groupby('SKU ID').tail(1).set_index('SKU ID')
    agg = allS.groupby(['SKU ID', 'ym']).agg(g=('매출액(GMV)', 'sum'), q=('판매 수량 (SKU ID)', 'sum'), r=('반품 수량', 'sum'),
                                            c=('매입원가(COGS)', 'sum'), p=('프로모션 발생 매출액', 'sum'),
                                            o=('주문건수', 'sum'), v=('조회수', 'sum')).reset_index()
    # 이번 달(부분)과 같은 날짜 범위의 작년 값
    endd = pd.Timestamp(end)
    ly_start, ly_end = (endd.replace(day=1) - pd.DateOffset(years=1)).strftime('%Y-%m-%d'), (endd - pd.DateOffset(years=1)).strftime('%Y-%m-%d')
    lym = allS[(allS['d'] >= ly_start) & (allS['d'] <= ly_end)].groupby('SKU ID').agg(
        g=('매출액(GMV)', 'sum'), q=('판매 수량 (SKU ID)', 'sum'), c=('매입원가(COGS)', 'sum'), p=('프로모션 발생 매출액', 'sum'),
        r=('반품 수량', 'sum'), o=('주문건수', 'sum'), v=('조회수', 'sum'))
    HF = ['g', 'q', 'r', 'c', 'p', 'o', 'v']
    hsku = {}
    for sid, r in hm.iterrows():
        cat = meta[sid]['cat'] if sid in meta else r['세부카테고리']
        hsku[sid] = dict(id=int(sid), name=meta[sid]['name'] if sid in meta else r['SKU명'], cat=cat,
                         brand=meta[sid]['brand'] if sid in meta else r['브랜드'], grp=grp(cat), cur=sid in meta,
                         **{f: [0] * M for f in HF},
                         ly={f: int(lym.loc[sid, f]) if sid in lym.index else 0 for f in HF})
    for _, r in agg.iterrows():
        k = hsku[r['SKU ID']]; i = mi[r['ym']]
        for f in HF:
            k[f][i] = int(r[f])
    # 일별 합계 (카테고리 그룹 × 브랜드)
    allS['grp'] = allS['SKU ID'].map(lambda x: hsku[x]['grp'])
    allS['brand'] = allS['SKU ID'].map(lambda x: hsku[x]['brand'])
    hdays = [d.strftime('%Y-%m-%d') for d in pd.date_range(allS['d'].min(), end)]
    hdi = {d: i for i, d in enumerate(hdays)}
    dd = allS.groupby(['grp', 'brand', 'd']).agg(g=('매출액(GMV)', 'sum'), q=('판매 수량 (SKU ID)', 'sum'), c=('매입원가(COGS)', 'sum')).reset_index()
    daily = []
    for (gname, bname), gdf in dd.groupby(['grp', 'brand']):
        row = dict(grp=gname, brand=bname, g=[0] * len(hdays), q=[0] * len(hdays), c=[0] * len(hdays))
        for _, r in gdf.iterrows():
            i = hdi[r['d']]; row['g'][i] = int(r['g']); row['q'][i] = int(r['q']); row['c'][i] = int(r['c'])
        daily.append(row)
    hist = dict(months=months, mtdDays=int(endd.day), lyStart=ly_start, lyEnd=ly_end, skus=list(hsku.values()), days0=hdays[0], daily=daily)
    tot = sum(sum(k['g']) for k in hsku.values())
    print(f'이력: {months[0]} ~ {months[-1]} ({M}개월) · SKU {len(hsku)} · GMV {tot:,} = {int(allS["매출액(GMV)"].sum()):,} · 일별 {len(hdays)}일 × {len(daily)}그룹')

ops_off = days.index(ops_start)
for k in skus:
    for f in OPSF + ['so']:
        k[f] = k[f][ops_off:]
out = dict(opsOffset=ops_off, days=days, asOf=end, generated=datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M'),
           files=dict(sales=[os.path.basename(f) for f in sfiles], ops=[os.path.basename(f) for f in ofiles],
                      po=[os.path.basename(f) for f in pfiles]),
           missingOps=missing_ops, opsStart=ops_start, skus=skus, poOnly=po_only, hist=hist)
import gzip, base64
raw = json.dumps(out, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
with open(OUT, 'w', encoding='utf-8') as f:
    f.write(base64.b64encode(gzip.compress(raw, 9)).decode('ascii'))
print(f'데이터 {len(raw)/1e6:.1f}MB → 압축 후 {os.path.getsize(OUT)/1e6:.2f}MB')

# 검증
print('기간', days[0], '~', end, N, '일 · SKU', len(skus), '· 발주만 있는 SKU', len(po_only), '· 재고 누락일', missing_ops)
print('GMV', sum(sum(k['g']) for k in skus), '=', int(s['매출액(GMV)'].sum()), '· 최근 파일분', int(s_recent['매출액(GMV)'].sum()))
print('판매수량', sum(sum(k['q']) for k in skus), '=', int(s['판매 수량 (SKU ID)'].sum()))
print('PMC', sum(sum(k['pmc']) for k in skus), '=', int(pd.to_numeric(s['쿠팡 추가 할인가'], errors='coerce').fillna(0).sum()))
print(f'{end} 재고', sum(k['st'][-1] for k in skus), '=', int(lastday['현재재고수량'].sum()))
if len(po):
    print('발주 확정', sum(l[4] for k in skus for l in k['po']) + sum(l[4] for k in po_only for l in k['po']), '=', int(po['확정수량'].sum()))
