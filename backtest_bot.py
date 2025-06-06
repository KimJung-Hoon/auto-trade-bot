import ccxt
import os
import time
import requests
from dotenv import load_dotenv
import pandas as pd
import ta
import datetime

# ───────────────────────────────
# 1. 환경변수 로드 (백테스트는 API 키 필요 없지만, 원본 코드 유지)
# ───────────────────────────────
load_dotenv()
api_key = os.getenv('UPBIT_API_KEY')
secret_key = os.getenv('UPBIT_SECRET_KEY')

# ───────────────────────────────
# 2. 업비트 객체 생성 (데이터 로딩용)
# ───────────────────────────────
upbit = ccxt.upbit({
    'apiKey': api_key,
    'secret': secret_key,
    'options': {
        'defaultType': 'spot',
    },
})

# ───────────────────────────────
# 3. 설정 값 (원본 코드와 동일)
# ───────────────────────────────
MIN_ORDER_KRW = 5000 # 업비트 BTC/KRW 최소 주문 금액
RSI_PERIOD = 14
RSI_BUY_THRESHOLD = 35
RSI_SELL_THRESHOLD = 55
TRADE_COOLDOWN_SECONDS = 300 # 5분 (백테스트에서는 시간 단위로 시뮬레이션되므로, 의미가 약간 다름)
FEE_RATE = 0.0005 # 업비트 거래 수수료 (시장가 기준 0.05%)

# ───────────────────────────────
# 4. 백테스트 함수
# ───────────────────────────────
def run_backtest(start_date_str, end_date_str, initial_krw_balance):
    print(f"🚀 백테스트 시작: {start_date_str} ~ {end_date_str}\n")

    # 데이터 로드
    symbol = 'BTC/KRW'
    timeframe = '1h'
    all_ohlcv = []
    
    start_timestamp_ms = upbit.parse8601(start_date_str + 'T00:00:00Z')
    end_timestamp_ms = upbit.parse8601(end_date_str + 'T23:59:59Z')

    current_timestamp = start_timestamp_ms
    limit = 200 # 한 번에 가져올 수 있는 최대 데이터 개수

    print("데이터 로딩 중...")
    while current_timestamp <= end_timestamp_ms:
        try:
            ohlcv = upbit.fetch_ohlcv(symbol, timeframe, since=current_timestamp, limit=limit)
            if not ohlcv:
                # 더 이상 데이터가 없거나, 끝점에 도달하면 종료
                break
            
            # 마지막 데이터의 타임스탬프가 end_timestamp_ms를 초과하는지 확인
            if ohlcv[-1][0] > end_timestamp_ms:
                # 필요한 기간까지만 포함
                for i in range(len(ohlcv)):
                    if ohlcv[i][0] > end_timestamp_ms:
                        ohlcv = ohlcv[:i]
                        break
            
            all_ohlcv.extend(ohlcv)
            
            # 다음 요청을 위해 마지막 데이터의 타임스탬프 + 1시간
            if ohlcv: # ohlcv가 비어있지 않은 경우에만 업데이트
                current_timestamp = ohlcv[-1][0] + (60 * 60 * 1000) 
            else: # ohlcv가 비어있으면 더 이상 데이터가 없다는 의미이므로 루프 종료
                break
            
            # 목표 기간을 초과하면 데이터 로딩 중단
            if current_timestamp > end_timestamp_ms and ohlcv:
                break

            time.sleep(0.05) # 과도한 요청 방지
        except Exception as e:
            print(f"데이터 로딩 중 오류 발생: {e}")
            time.sleep(5)
            continue
    
    if not all_ohlcv:
        print("❌ 지정된 기간 동안의 데이터를 불러오지 못했습니다. 백테스트를 중단합니다.")
        return

    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df['close'] = pd.to_numeric(df['close'])

    # RSI 계산 ( 충분한 과거 데이터 필요 )
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=RSI_PERIOD).rsi()
    df.dropna(inplace=True) # RSI 계산을 위해 NaN 값 제거

    # 백테스트 시작 일자와 RSI 계산으로 인해 데이터 시작 일자가 달라질 수 있음.
    # 시작 일자를 기준으로 다시 필터링
    df = df[df.index >= pd.to_datetime(start_date_str)]
    
    if df.empty:
        print("❌ RSI 계산 후 유효한 데이터가 없습니다. 백테스트를 중단합니다.")
        return

    print(f"\n✅ 총 {len(df)}개의 데이터 포인트 로드 및 준비 완료. 백테스트 시뮬레이션 시작...\n")
    
    # 백테스트 변수 초기화
    krw_balance = initial_krw_balance
    btc_balance = 0.0
    total_trades = 0
    trade_cooldown_end_time = datetime.datetime.min # 거래 쿨다운 종료 시간

    # 월별 수익률 기록
    monthly_results = {}
    # 백테스트 시작 시점의 총 자산을 해당 월의 시작 자산으로 설정
    current_month_start_asset = initial_krw_balance
    last_processed_month = df.index[0].strftime('%Y-%m')

    # 시뮬레이션 시작
    for idx, row in df.iterrows():
        current_time = idx # DatetimeIndex 직접 사용
        current_price = row['close']
        current_rsi = row['rsi']

        # 월이 바뀌는 시점 처리
        if current_time.strftime('%Y-%m') != last_processed_month:
            # 이전 월의 마지막 자산 = 현재까지의 KRW 잔고 + (BTC 잔고 * 이전 월 마지막 봉의 종가)
            # (주의: 이 부분은 정확한 월말 자산 스냅샷이 아닌, 현재 loop 시점의 잔고와 이전 봉 종가를 사용)
            # -> 더 정확한 월별 수익률 계산을 위해, 이전 월의 마지막 봉의 종가를 가져와야 합니다.
            # 하지만 이미 DatetimeIndex를 순회하므로, 현재 `row`는 이미 다음 달의 첫 봉입니다.
            # 따라서 `current_month_start_asset`은 현재 달의 첫 봉 시점의 총 자산이 되어야 합니다.
            # 월별 수익률은 '이전 달의 시작 자산 대비 이전 달의 마지막 자산'으로 계산됩니다.

            # 이전 월의 최종 자산 (current_time은 이미 새 월의 시작이므로, 이전 월의 마지막 봉을 찾아야 함)
            # df.index에서 현재 인덱스(idx)의 바로 이전 인덱스를 찾기
            prev_idx_loc = df.index.get_loc(idx) - 1
            if prev_idx_loc >= 0: # 첫 봉이 아니라면
                prev_time_index = df.index[prev_idx_loc]
                prev_month_close = df.loc[prev_time_index, 'close']
                prev_month_end_asset = krw_balance + (btc_balance * prev_month_close)
                
                # 이전 월의 수익률 계산
                if current_month_start_asset > 0:
                    monthly_profit_rate = ((prev_month_end_asset - current_month_start_asset) / current_month_start_asset) * 100
                else: # 시작 자산이 0이거나 음수일 경우 (예외 처리)
                    monthly_profit_rate = 0 
                monthly_results[last_processed_month] = monthly_profit_rate
                
                # 다음 월의 시작 자산 업데이트
                current_month_start_asset = prev_month_end_asset
            
            # 현재 월 업데이트
            last_processed_month = current_time.strftime('%Y-%m')


        # 쿨다운 중인지 확인
        if current_time < trade_cooldown_end_time:
            continue # 쿨다운 중이면 거래 스킵

        # ── 매수 조건 ──
        if btc_balance == 0 and current_rsi <= RSI_BUY_THRESHOLD and krw_balance >= MIN_ORDER_KRW:
            amount_to_buy_krw = krw_balance # KRW 전액 매수
            
            if amount_to_buy_krw >= MIN_ORDER_KRW: # 매수 금액이 최소 주문 금액 이상일 때만 진행
                buy_amount_btc = (amount_to_buy_krw / current_price) * (1 - FEE_RATE) # 수수료 반영
                krw_balance -= amount_to_buy_krw
                btc_balance += buy_amount_btc
                total_trades += 1
                trade_cooldown_end_time = current_time + datetime.timedelta(seconds=TRADE_COOLDOWN_SECONDS)
        
        # ── 매도 조건 ──
        elif btc_balance > 0 and current_rsi >= RSI_SELL_THRESHOLD:
            # 최소 매도 수량 고려 (업비트 BTC/KRW는 0.00008 BTC 정도이지만, 안전하게 0보다 크면 매도 시도)
            if btc_balance * current_price >= MIN_ORDER_KRW: # BTC 보유액이 최소 매도 금액 이상일 때만 매도
                sell_amount_btc = btc_balance
                krw_received = sell_amount_btc * current_price * (1 - FEE_RATE)
                krw_balance += krw_received
                btc_balance = 0.0 # 전량 매도
                total_trades += 1
                trade_cooldown_end_time = current_time + datetime.timedelta(seconds=TRADE_COOLDOWN_SECONDS)

    # 루프 종료 후 마지막 월의 수익률 계산
    final_total_asset = krw_balance + (btc_balance * df['close'].iloc[-1]) # 최종 자산
    if current_month_start_asset > 0:
        monthly_profit_rate = ((final_total_asset - current_month_start_asset) / current_month_start_asset) * 100
    else:
        monthly_profit_rate = 0
    monthly_results[last_processed_month] = monthly_profit_rate

    # 누적 수익률 계산
    cumulative_return = ((final_total_asset - initial_krw_balance) / initial_krw_balance) * 100

    # 결과 출력
    print("\n" + "="*30)
    print("📊 백테스트 결과")
    print("="*30)
    print(f"📈 초기 자산: {initial_krw_balance:,.0f} KRW")
    print(f"📊 최종 자산: {final_total_asset:,.0f} KRW")
    print(f"💰 최종 KRW 잔고: {krw_balance:,.0f} KRW")
    print(f"₿ 최종 BTC 잔고: {btc_balance:.8f} BTC")
    print(f"📈 누적 수익률: {cumulative_return:.2f} %")
    print(f"총 거래 횟수: {total_trades}회")

    print("\n--- 월별 수익률 ---")
    total_cumulative_monthly_return = 1.0 # 누적 수익률 계산을 위한 변수 (곱셈)
    sorted_months = sorted(monthly_results.keys())
    for month in sorted_months:
        rate = monthly_results[month]
        print(f" {month}: {rate:.2f}%")
        total_cumulative_monthly_return *= (1 + rate / 100)
    
    # 월별 합산 누적 수익률 (복리 계산)
    final_monthly_cumulative_return_percentage = (total_cumulative_monthly_return - 1) * 100
    print(f"\n누적 수익률 (월별 복리): {final_monthly_cumulative_return_percentage:.2f} %")


# ───────────────────────────────
# 5. 백테스트 실행
# ───────────────────────────────
if __name__ == "__main__":
    initial_balance = 10_000_000 # 1,000만 원 시작
    # 2022년 1월 1일부터 2023년 12월 31일까지 백테스트
    run_backtest('2022-01-01', '2023-12-31', initial_balance)