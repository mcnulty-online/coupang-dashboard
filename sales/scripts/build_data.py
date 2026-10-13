"""쿠팡 판매·재고·발주 CSV → 대시보드 데이터(JSON)

사용법: python3 build_data.py <입력폴더> <출력 json> [과거판매.csv.gz] [과거발주.csv.gz]
  과거판매: load_history.py로 만든 과거 판매 이력 (있으면 YoY 탭 데이터 생성)
  과거발주: 월별 PO_SKU_LIST를 합친 발주 이력 (있으면 월별 발주금액·마감 예상 검증에 사용)
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
POH = sys.argv[4] if len(sys.argv) > 4 else None


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

# 발주 이력 전체(마감 예상 매입금액용): 발주 이력 + 입력 폴더의 모든 발주 파일.
# 같은 (발주번호, SKU)는 가장 늦게 내려받은 파일 기준 (_ts = 파일명 시각, 이력 파일은 _ts 열에 기록)
pm_parts = []
if POH and os.path.exists(POH):
    pm_parts.append(pd.read_csv(POH, encoding='utf-8', low_memory=False, dtype={'_ts': str}))
for f in sorted(glob.glob(os.path.join(IN, 'PO_SKU_LIST*.csv'))):
    ts = ''.join(ch for ch in os.path.basename(f) if ch.isdigit())[-14:]
    pm_parts.append(pd.read_csv(f, encoding='utf-8-sig').assign(_ts=ts))
pa = None
if pm_parts:
    pa = pd.concat([x[['_ts', '발주번호', '발주현황', 'SKU ID', '발주일', '입고예정일', '총발주 매입금', '입고금액']] for x in pm_parts], ignore_index=True)
    pa = pa.sort_values('_ts', kind='stable').drop_duplicates(['발주번호', 'SKU ID'], keep='last')
    pa['od'] = pd.to_datetime(pa['발주일'].astype(str).str[:10])
    pa['ed'] = pd.to_datetime(pa['입고예정일'].astype(str).str[:10])
    pa['em'] = pa['ed'].dt.to_period('M')
    po_cut = pd.Timestamp(pa['_ts'].max()[:8])          # 발주 자료 기준일 = 가장 최근 발주 파일을 내려받은 날
    print(f'발주 이력: {len(pa):,}건 · 발주일 {pa["od"].min().date()} ~ {pa["od"].max().date()} · 자료 기준일 {po_cut.date()}')

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

# ---- 당월 마감 예상 매입금액 (입고예정일 기준 월, 입고금액) ----
#  예상 = 입고 완료(입고예정일 ≤ 기준일, 입고금액)
#       + 입고 예정(이미 발주됐고 이번 달 안에 입고 예정, 총발주 매입금 × 입고 반영률)
#       + 추가 발주분(아직 발주 전이지만 리드타임 7일 안에 들어와 이번 달 입고될 날 수 × 최근 14일 판매원가×1.1 일평균 × 입고/판매 비율)
#  반영률·비율은 직전 6개월 실적. 지난 달들을 같은 날짜 기준으로 다시 예측해 오차도 같이 저장.
SEP_BEANS = {80661387, 80686777, 80855135, 80855134, 80855137}
ETC_SUB = {'Kitchen Appliance', 'Tools & Gadgets'}
FC_GROUPS = ['커피/차', '음료', '별도 관리 원두', '기타', '그 외']
LEAD = 7
po_fc = None
if pa is not None:
    kby = {k['id']: k for k in skus}
    def group_of(sid):
        sid = int(sid)
        if sid in SEP_BEANS: return '별도 관리 원두'
        k = kby.get(sid)
        if k is None: return '그 외'
        if k.get('sub') in ETC_SUB: return '기타'
        return {'커피': '커피/차', '음료': '음료'}.get(k['grp'], '그 외')
    pa['g'] = pa['SKU ID'].map(group_of)
    s['fg'] = s['SKU ID'].map(group_of)
    cg = (s.groupby([pd.to_datetime(s['d']), 'fg'])['매입원가(COGS)'].sum().unstack(fill_value=0) * 1.1).reindex(columns=FC_GROUPS, fill_value=0)
    cg = cg.reindex(pd.date_range(cg.index.min(), end), fill_value=0)
    cg['전체'] = cg[FC_GROUPS].sum(axis=1)
    send0 = pd.Timestamp(end); lag = (po_cut - send0).days          # 판매 자료가 발주 자료보다 며칠 늦은지
    first_m = pa['od'].min().to_period('M') + 2                      # 이 달부터 입고 실적이 온전함
    by_em = {m: g for m, g in pa.groupby('em')}
    def actual(m): return float(by_em[m]['총발주 매입금'].sum()) if m in by_em else 0.0   # 입고예정일 월 기준 발주금액 (발주된 건 모두 입고 가정)
    def mcost(m): return float(cg['전체'][m.start_time:m.end_time.normalize()].sum())
    # 발주 자료를 내려받은 시각 이후에 그날 더 나올 발주 비중 (쿠팡 발주는 8~17시에 걸쳐 나옴, 최근 6개월 금액 기준)
    dl_ts = pa['_ts'].max(); dl_sec = int(dl_ts[8:10]) * 3600 + int(dl_ts[10:12]) * 60
    tod = pd.to_datetime(pa['발주일'].astype(str), errors='coerce'); recent = tod >= po_cut - pd.Timedelta(days=183)
    tsec = tod.dt.hour * 3600 + tod.dt.minute * 60
    today_left = float(pa.loc[recent & (tsec > dl_sec), '총발주 매입금'].sum() / pa.loc[recent, '총발주 매입금'].sum())
    def at(m, day, left=0.0):
        """m월 day일 기준으로 알 수 있었던 값 (발주금액 기준, 발주된 건 모두 입고된다고 가정)"""
        ms, me = m.start_time, m.end_time.normalize()
        cut = ms + pd.Timedelta(days=min(day, m.days_in_month) - 1); send = cut - pd.Timedelta(days=lag)
        x = by_em.get(m, pa.iloc[:0]); x = x[x['od'] <= cut]
        done, sched = x[x['ed'] <= cut], x[x['ed'] > cut]
        prev = [p for p in pd.period_range(m - 6, m - 1, freq='M') if p >= first_m]
        if not prev: return None
        rin = sum(actual(p) for p in prev) / sum(mcost(p) for p in prev)   # 입고월 기준 발주금액 ÷ 판매원가×1.1
        newdays = max(0, (me - cut).days - LEAD) + (left if (me - cut).days > LEAD else 0)   # left: 기준일 중 아직 안 나온 발주분
        daily = cg.loc[send - pd.Timedelta(days=13):send].mean() if send >= cg.index[0] else cg.iloc[:0].sum()
        rows = []
        for g in FC_GROUPS + ['전체']:
            sel = (lambda d: d) if g == '전체' else (lambda d, g=g: d[d['g'] == g])
            R = float(sel(done)['총발주 매입금'].sum()); S = float(sel(sched)['총발주 매입금'].sum())
            new = newdays * float(daily.get(g, 0)) * rin
            rows.append(dict(g=g, R=R, S=S, new=new, est=R + S + new, daily=float(daily.get(g, 0))))
        return dict(cut=cut, send=send, rin=rin, newdays=newdays, rows=rows, sched=sched, est=rows[-1]['est'])
    cur_m = po_cut.to_period('M')
    back_ms = [m for m in pd.period_range(first_m + 1, cur_m - 1, freq='M')]
    def backtest(day):
        out_ = []
        for m in back_ms:
            f = at(m, day); act = actual(m)
            if f and act: out_.append(dict(m=str(m), act=act, est=f['est'], R=f['rows'][-1]['R'], S=f['rows'][-1]['S'], new=f['rows'][-1]['new'], e=f['est'] / act - 1))
        return out_
    def stat(b):
        e = [x['e'] for x in b]
        return dict(n=len(e), mae=round(float(sum(map(abs, e)) / len(e)), 4), bias=round(float(sum(e) / len(e)), 4), mx=round(float(max(map(abs, e))), 4), in10=int(sum(abs(x) <= .10 for x in e)), in15=int(sum(abs(x) <= .15 for x in e)))
    cday = po_cut.day
    F = at(cur_m, cday, today_left); B = backtest(cday)
    sched_by_day = F['sched'].groupby(F['sched']['ed'].dt.strftime('%Y-%m-%d'))['총발주 매입금'].sum()
    r = lambda v: int(round(v))
    po_fc = dict(month=str(cur_m), cut=po_cut.strftime('%Y-%m-%d'), salesEnd=F['send'].strftime('%Y-%m-%d'), lead=LEAD,
                 rin=round(float(F['rin']), 4), newdays=round(float(F['newdays']), 2), todayLeft=round(today_left, 3),
                 dl=f'{dl_ts[:4]}-{dl_ts[4:6]}-{dl_ts[6:8]} {dl_ts[8:10]}:{dl_ts[10:12]}',
                 groups=[dict(g=x['g'], R=r(x['R']), S=r(x['S']), new=r(x['new']), est=r(x['est']), daily=r(x['daily'])) for x in F['rows']],
                 sched=[[d, r(v)] for d, v in sched_by_day.items()],
                 back=[dict(m=x['m'], act=r(x['act']), est=r(x['est']), R=r(x['R']), S=r(x['S']), new=r(x['new']), e=round(float(x['e']), 4)) for x in B],
                 stat=stat(B) if B else None,
                 byDay=[dict(day=d, **stat(backtest(d))) for d in [5, 10, 15, 20, 25]])
    T = F['rows'][-1]
    print(f'마감 예상({cur_m}, {po_cut.date()} 기준): 이미 발주(입고예정일 지남 {T["R"]/1e8:.2f}억 + 남음 {T["S"]/1e8:.2f}억) + 추가 {F["newdays"]:.2f}일(오늘 남은 발주 {today_left:.0%} 포함)×{T["daily"]/1e4:,.0f}만×{F["rin"]:.2f} = {T["est"]/1e8:.2f}억'
          + (f' · 검증 {po_fc["stat"]["n"]}개월 평균 오차 {po_fc["stat"]["mae"]*100:.1f}%' if B else ''))
    print('  날짜별 평균 오차:', ' · '.join(f'{x["day"]}일 {x["mae"]*100:.1f}%' for x in po_fc['byDay']))

ops_off = days.index(ops_start)
for k in skus:
    for f in OPSF + ['so']:
        k[f] = k[f][ops_off:]
out = dict(opsOffset=ops_off, days=days, asOf=end, generated=datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M'),
           files=dict(sales=[os.path.basename(f) for f in sfiles], ops=[os.path.basename(f) for f in ofiles],
                      po=[os.path.basename(f) for f in pfiles]),
           missingOps=missing_ops, opsStart=ops_start, skus=skus, poOnly=po_only, hist=hist, poFc=po_fc)
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
