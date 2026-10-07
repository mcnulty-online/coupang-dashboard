# 쿠팡 판매·재고·발주 대시보드

주소: https://mcnulty-online.github.io/coupang-dashboard/sales/

## 매일 갱신하는 법

1. 쿠팡 서플라이어허브에서 아래 3개 파일을 내려받습니다.
   - 판매분석 일별 성과 (`A00046945_SALES_ANALYSIS_DAILY_PERFORMANCE_….csv`) — 최근 7일
   - 로켓 기본운영 재고 (`basic_operation_rocket_….csv`) — 최근 7일
   - 발주 SKU 리스트 (`PO_SKU_LIST_….csv`) — 최근 30일 발주분
2. GitHub 저장소에서 `sales/input` 폴더로 들어가 **Add file → Upload files**로 3개를 올리고 **Commit changes**를 누릅니다.
3. 1~2분 뒤 대시보드 주소를 새로고침하면 반영돼 있습니다. (진행 상황은 저장소 위쪽 **Actions** 탭에서 볼 수 있습니다.)

파일명은 바꾸지 말고 그대로 올려주세요. 기간이 겹쳐도 괜찮습니다. 같은 날짜는 파일명 기준 가장 최근 파일 값을 씁니다. 발주는 가장 최근 발주 파일 하나만 씁니다.

## 폴더 구성

| 경로 | 내용 |
|---|---|
| `index.html` | 완성된 대시보드 (자동 생성 — 직접 고치지 않음) |
| `template.html` | 대시보드 화면 틀 |
| `input/` | 매일 올리는 쿠팡 CSV |
| `data/history.csv.gz` | 24년 7월 ~ 26년 9월 과거 판매 이력 |
| `data/data.b64` | 계산된 데이터 (자동 생성) |
| `scripts/build_data.py` | CSV → 데이터 계산 |
| `scripts/render.py` | 틀 + 데이터 → index.html |
| `scripts/load_history.py` | 과거 판매 파일(옛 형식 포함)을 이력 파일로 정리할 때 사용 |

## 계산 기준

- PPM = (매출 − 매입원가 × 1.1) ÷ 매출
- 커피/차 · 음료 구분은 세부카테고리 기준
- PMC = 판매 파일의 '쿠팡 추가 할인가' 합계
- 재고일수 = 기준일 재고 ÷ 최근 30일 일평균 판매량 (긴급 7일 미만 · 주의 14일 미만 · 과잉 90일 이상)
- 입고 예정 = 발주 확정수량 − 입고수량
