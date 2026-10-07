"""과거 판매 파일(형식이 달라도) → 통일된 일별 SKU 데이터(pkl)

사용법: python3 load_history.py <폴더> <출력.pkl>
옛 형식(판매수량(Units Sold), PV 등)과 새 형식(판매 수량 (SKU ID), 조회수 등)을 같은 열 이름으로 맞춤.
같은 날짜가 여러 파일에 있으면 파일명 정렬상 뒤 파일 기준.
"""
import glob, os, sys
import pandas as pd

IN, OUT = sys.argv[1], sys.argv[2]
REN = {
    'Product ID': '상품 ID', 'SKU 명': 'SKU명',
    '판매수량(Units Sold)': '판매 수량 (SKU ID)', '반품수량(Return Units)': '반품 수량',
    '프로모션발생매출액(GMV)': '프로모션 발생 매출액', '프로모션발생판매수량(Units Sold)': '프로모션 발생 판매 수량',
    '평균판매금액(ASP)': '평균 판매 금액', '구매전환율': '구매전환율 (%)', 'PV': '조회수',
    '쿠폰 할인가(쿠팡 추가 할인쿠폰 제외)': '쿠폰 할인가(쿠팡 추가 할인가 제외)', '쿠팡 추가 할인쿠폰 할인가': '쿠팡 추가 할인가',
}
KEEP = ['날짜', 'SKU ID', '바코드', 'SKU명', '벤더아이템 ID', '상품카테고리', '하위카테고리', '세부카테고리', '브랜드',
        '매출액(GMV)', '판매 수량 (SKU ID)', '반품 수량', '매입원가(COGS)', '프로모션 발생 매출액', '프로모션 발생 판매 수량',
        '쿠팡 추가 할인가', '주문건수', '조회수', '상품평 수', '평균 상품 평점']


def read(f):
    for enc in ('utf-8-sig', 'cp949'):
        try:
            return pd.read_csv(f, encoding=enc, low_memory=False)
        except UnicodeDecodeError:
            continue
    raise ValueError(f)


parts = []
for rank, f in enumerate(sorted(glob.glob(os.path.join(IN, '*.csv')))):
    d = read(f).rename(columns=REN)
    miss = [c for c in KEEP if c not in d.columns]
    if miss:
        sys.exit(f'{os.path.basename(f)}: 열 없음 {miss}')
    d = d[KEEP].copy()
    d['날짜'] = pd.to_datetime(d['날짜'].astype(str).str.replace('-', '').str[:8], format='%Y%m%d')
    d['_f'] = os.path.basename(f); d['_rank'] = rank
    parts.append(d)
df = pd.concat(parts, ignore_index=True)
df = df[df['_rank'] == df.groupby('날짜')['_rank'].transform('max')].drop(columns='_rank')
for c in ['매출액(GMV)', '판매 수량 (SKU ID)', '반품 수량', '매입원가(COGS)', '프로모션 발생 매출액', '프로모션 발생 판매 수량', '쿠팡 추가 할인가', '주문건수', '조회수', '상품평 수']:
    df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
df['반품 수량'] = df['반품 수량'].abs()   # 옛 형식은 반품이 음수로 기록됨
df.to_pickle(OUT)
print(f'{len(parts)}개 파일 · {len(df):,}행 · {df["날짜"].min().date()} ~ {df["날짜"].max().date()} · SKU {df["SKU ID"].nunique()}개')
