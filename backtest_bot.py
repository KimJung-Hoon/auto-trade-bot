import ccxt
import os
import time
import requests
import pandas as pd
import ta
from datetime import datetime, timedelta
from dotenv import load_dotenv

# ───────────────────────────────
# 1. 환경변수 로드 (백테스팅에는 실제 키 필요 없음, 에러 방지용)
# ───────────────────────────────
load_dotenv()
api_key          = os.getenv('UPBIT_API_KEY') # 실제 사용되지 않지만, ccxt 객체 생성 시 필요
secret_key       = os.getenv('UPBIT_SECRET_KEY') # 실제 사용되지 않지만, ccxt 객체 생성 시 필요

# ───────────────────────────────
# 2. CCXT 업비트 객체 생성 (데이터 로드용)
# ───────────────────────────────
upbit = ccxt.upbit({
    'apiKey': api_key if api_key else 'YOUR_DUMMY_API_KEY', # 더미 키 사용 가능
    'secret': secret_key if secret_key else 'YOUR_DUMMY_SECRET_KEY', # 더미 키 사용 가능
    'enableRateLimit': True # 데이터 요청 속도 제한 준수
})
upbit.load_markets()

# ───────────────────────────────
# 3. 전략 파라미터 (원본 코드와 동일)
# ───────────────────────────────
MA_SHORT        = 20      # 단기 이동평균 기간 (일)
MA_LONG         = 50      # 장기 이동평균 기간 (일)
MDI_WINDOW      = 14      # MDI 계산 기간 (일)
MDI_BUY_THRESH  = 15      # 매수 시 MDI 기준치
MDI_SELL_THRESH = 27      # 매도 시 MDI 기준치
STOP_LOSS_PCT   = 0.06    # 손절 비율 (6%)
MIN_KRW_TRADE   = 5000    # 업비트 최소 거래 금액 (KRW)
TRADE_FEE_RATE  = 0.0005  # 업비트 시장가 수수료율 (0.05%)

symbol          = 'BTC/KRW'
timeframe       = '1d'    # 일봉

# ───────────────────────────────
# 4. 백테스팅 설정 (기간 변경)
# ───────────────────────────────
INITIAL_BALANCE_KRW = 1_000_000 # 초기 투자금 (100만원)

# 백테스팅 시작 및 종료 날짜 명시적 설정
# 지표 계산을 위한 충분한 과거 데이터 확보를 위해 실제 시작일보다 더 이전부터 데이터를 가져옵니다.
data_fetch_start_date = datetime(2018, 10, 1) # 2019년 시작 + 넉넉하게 3개월 전
backtest_start_date   = datetime(2019, 1, 1)
backtest_end_date     = datetime(2020, 12, 31)

print("--- 백테스팅 시작 ---")
print(f"백테스팅 기간: {backtest_start_date.strftime('%Y-%m-%d')} ~ {backtest_end_date.strftime('%Y-%m-%d')}")
print(f"초기 투자금: {INITIAL_BALANCE_KRW:,.0f} KRW")
print(f"전략: MA{MA_SHORT}/MA{MA_LONG} & MDI({MDI_WINDOW}) 매수({MDI_BUY_THRESH})/매도({MDI_SELL_THRESH}) & 손절({STOP_LOSS_PCT*100}%)")
print(f"수수료: {TRADE_FEE_RATE*100}%, 최소 거래: {MIN_KRW_TRADE}원")

# ───────────────────────────────
# 5. 과거 데이터 로드
# ───────────────────────────────
all_ohlcv = []
current_fetch_start = data_fetch_start_date # 데이터 로드 시작 지점 변경

while current_fetch_start <= backtest_end_date + timedelta(days=1): # 종료일 다음 날까지 데이터 로드
    try:
        since_ms = upbit.parse8601(current_fetch_start.isoformat() + 'Z')
        chunk = upbit.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=200)
        if not chunk:
            break
        all_ohlcv.extend(chunk)
        current_fetch_start = datetime.fromtimestamp(chunk[-1][0] / 1000) + timedelta(days=1)
        time.sleep(upbit.rateLimit / 1000)
    except Exception as e:
        print(f"데이터 로드 중 오류 발생: {e}")
        break

df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
df.set_index('timestamp', inplace=True)
df = df.drop_duplicates(keep='first')
df = df.sort_index()

# ───────────────────────────────
# 6. 지표 계산 및 전략 적용
# ───────────────────────────────
df['ma_short'] = df['close'].rolling(MA_SHORT).mean()
df['ma_long']  = df['close'].rolling(MA_LONG).mean()
adx = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=MDI_WINDOW, fillna=False)
df['mdi'] = adx.adx_neg()
df.dropna(inplace=True)

# 실제 백테스팅 시작 날짜 이후 데이터만 사용
df = df[df.index >= backtest_start_date]
df = df[df.index <= backtest_end_date] # 2020년 12월 31일까지의 데이터만 포함

# ───────────────────────────────
# 7. 백테스팅 시뮬레이션
# ───────────────────────────────
balance_krw = INITIAL_BALANCE_KRW
balance_btc = 0
last_buy_price = 0
portfolio_values = []
monthly_returns = {} # 월별 수익률을 저장할 딕셔너리

prev_ma_short = None
prev_ma_long  = None

for i in range(len(df)):
    current_date = df.index[i]
    today_close  = df['close'].iloc[i]
    curr_ma_short = df['ma_short'].iloc[i]
    curr_ma_long  = df['ma_long'].iloc[i]
    curr_mdi      = df['mdi'].iloc[i]

    # 이전 데이터가 없으면 초기화 (df.dropna로 인해 첫 인덱스는 지표가 계산된 첫 날이 됨)
    if i == 0:
        prev_ma_short = curr_ma_short
        prev_ma_long  = curr_ma_long
        # 첫 날 포트폴리오 가치 기록
        portfolio_values.append({
            'date': current_date,
            'krw': balance_krw,
            'btc': balance_btc,
            'total_krw': balance_krw + balance_btc * today_close
        })
        continue

    # 4) 손절 조건 (6% 손실)
    if last_buy_price and balance_btc > 0:
        if today_close <= last_buy_price * (1 - STOP_LOSS_PCT):
            sell_amount_krw = balance_btc * today_close * (1 - TRADE_FEE_RATE)
            balance_krw += sell_amount_krw
            balance_btc = 0
            last_buy_price = 0
            # print(f"[{current_date.strftime('%Y-%m-%d')}] ⚠️ 손절 매도! 가격: {today_close:,.0f}원, 잔고: {balance_krw:,.0f}원")

    # 5) 매수 조건: 골든 크로스 발생 중 & MDI ≤ 기준 & KRW 보유
    golden_cross_occurred = (prev_ma_short <= prev_ma_long and curr_ma_short > curr_ma_long)
    golden_cross_maintained = (curr_ma_short > curr_ma_long)

    eligible_krw_for_buy = balance_krw * (1 - TRADE_FEE_RATE)

    if (golden_cross_occurred or golden_cross_maintained) and \
       curr_mdi <= MDI_BUY_THRESH and \
       eligible_krw_for_buy >= MIN_KRW_TRADE and \
       balance_btc == 0:
        
        buy_amt_btc = eligible_krw_for_buy / today_close
        
        balance_btc = buy_amt_btc
        balance_krw = 0
        last_buy_price = today_close
        # print(f"[{current_date.strftime('%Y-%m-%d')}] 💰 매수! 가격: {today_close:,.0f}원, 수량: {balance_btc:.8f} BTC")

    # 6) 매도 조건: 데드 크로스 발생 중 OR MDI ≥ 기준 & BTC 보유
    death_cross_occurred = (prev_ma_short >= prev_ma_long and curr_ma_short < curr_ma_long)
    death_cross_maintained = (curr_ma_short < curr_ma_long)

    if (death_cross_occurred or death_cross_maintained or curr_mdi >= MDI_SELL_THRESH) and \
       balance_btc > 0:
        
        sell_amount_krw = balance_btc * today_close * (1 - TRADE_FEE_RATE)
        balance_krw += sell_amount_krw
        balance_btc = 0
        last_buy_price = 0
        # print(f"[{current_date.strftime('%Y-%m-%d')}] 📤 매도! 가격: {today_close:,.0f}원, 잔고: {balance_krw:,.0f}원")
    
    # 일별 포트폴리오 가치 기록
    total_krw_value = balance_krw + balance_btc * today_close
    portfolio_values.append({
        'date': current_date,
        'krw': balance_krw,
        'btc': balance_btc,
        'total_krw': total_krw_value
    })

    # 다음 루프를 위한 이전 MA 값 업데이트
    prev_ma_short = curr_ma_short
    prev_ma_long  = curr_ma_long

# 최종 포트폴리오 가치 (마지막 날짜 기준)
final_balance_krw = balance_krw + balance_btc * df['close'].iloc[-1]
total_return = (final_balance_krw / INITIAL_BALANCE_KRW - 1) * 100

print("\n--- 백테스팅 결과 ---")
print(f"최종 포트폴리오 가치: {final_balance_krw:,.0f} KRW")
print(f"총 수익률: {total_return:.2f}%")

# 월별 수익률 계산
portfolio_df = pd.DataFrame(portfolio_values)
portfolio_df.set_index('date', inplace=True)
portfolio_df['monthly_total_krw'] = portfolio_df['total_krw'].resample('M').last()

print("\n--- 월별 수익률 ---")
total_monthly_returns_list = [] # 월별 수익률 값을 저장할 리스트
for month_end_date in portfolio_df['monthly_total_krw'].dropna().index:
    current_month_value = portfolio_df.loc[month_end_date, 'monthly_total_krw']
    
    prev_month_start_value = INITIAL_BALANCE_KRW # 초기 투자금으로 시작
    prev_month_end_dt = month_end_date - pd.DateOffset(months=1)
    
    prev_month_values_before_current_month = portfolio_df.loc[portfolio_df.index <= prev_month_end_dt, 'total_krw']
    if not prev_month_values_before_current_month.empty:
        prev_month_start_value = prev_month_values_before_current_month.iloc[-1]
    
    monthly_return_pct = ((current_month_value / prev_month_start_value) - 1) * 100
    month_str = month_end_date.strftime('%Y-%m')
    
    print(f"{month_str}: {monthly_return_pct:.2f}%")
    total_monthly_returns_list.append(monthly_return_pct)

# 월평균 수익률 (산술 평균)
if total_monthly_returns_list:
    avg_monthly_return = sum(total_monthly_returns_list) / len(total_monthly_returns_list)
    print(f"\n월평균 수익률: {avg_monthly_return:.2f}%")
else:
    print("\n월별 수익률 데이터가 충분하지 않습니다.")

print("\n--- 백테스팅 종료 ---")