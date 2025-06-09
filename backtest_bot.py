import ccxt
import pandas as pd
import ta
import datetime
import time
import json

# 1. CCXT 업비트 객체 생성
upbit = ccxt.upbit({
    'enableRateLimit': True, # 너무 빠르게 요청하는 것을 방지
})
upbit.load_markets()

# 2. 전략 파라미터
MA_SHORT = 20
MA_LONG = 50
ADX_WINDOW = 30
ADX_BUY_THRESH = 23
ADX_SELL_THRESH = 22
STOP_LOSS_PCT = 0.06
MIN_KRW_TRADE = 5000 # <<--- 이 변수는 정상적으로 선언되어 있습니다.
TRADE_FEE_RATE = 0.0005

symbol = 'BTC/KRW'
timeframe = '1d'

# 백테스팅 기간 설정
START_DATE = '2020-01-01 00:00:00'
END_DATE = '2024-12-31 23:59:59'

# 백테스팅 초기 자산 설정
INITIAL_KRW_BALANCE = 1_000_000 # 100만원 시작

# 3. 데이터 로드 및 전처리 함수
def fetch_historical_ohlcv(exchange, symbol, timeframe, start_date_str, end_date_str):
    all_ohlcv = []
    
    start_timestamp_ms = int(pd.to_datetime(start_date_str).timestamp() * 1000)
    end_timestamp_ms = int(pd.to_datetime(end_date_str).timestamp() * 1000)

    print(f"⏳ {symbol} 과거 데이터 ({timeframe}) 로딩 중... ({start_date_str} ~ {end_date_str})")
    
    fetch_limit = 199 

    current_since = start_timestamp_ms

    while True:
        try:
            ohlcvs = exchange.fetch_ohlcv(symbol, timeframe, since=current_since, limit=fetch_limit)
            
            if not ohlcvs:
                break
            
            filtered_ohlcvs = [data for data in ohlcvs if data[0] <= end_timestamp_ms]
            all_ohlcv.extend(filtered_ohlcvs)

            if filtered_ohlcvs:
                current_since = filtered_ohlcvs[-1][0] + 1
            else:
                break
            
            if ohlcvs[-1][0] >= end_timestamp_ms:
                break

            time.sleep(exchange.rateLimit / 1000)
            
        except ccxt.NetworkError as e:
            print(f"❌ 네트워크 오류 발생: {e}. 잠시 후 재시도합니다.")
            time.sleep(5)
        except ccxt.ExchangeError as e:
            print(f"❌ 거래소 오류 발생: {e}. 데이터 로딩을 중단합니다.")
            break
        except Exception as e:
            print(f"❌ 알 수 없는 오류 발생: {e}. 데이터 로딩을 중단합니다.")
            break
            
    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'vol'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    
    df = df.loc[start_date_str:end_date_str] 
    df.drop_duplicates(inplace=True)
    df.sort_index(inplace=True)
    
    return df

# 백테스팅 로직을 함수로 캡슐화
def run_backtest():
    # 데이터 로딩
    ohlcv_data = fetch_historical_ohlcv(upbit, symbol, timeframe, START_DATE, END_DATE)

    if ohlcv_data.empty:
        print("❌ 지정된 기간의 데이터를 가져오지 못했습니다. 백테스팅을 종료합니다.")
        return

    print(f"✅ 데이터 로딩 완료. 총 {len(ohlcv_data)}개의 일봉 데이터.")

    trade_logs = []
    portfolio_values = []

    current_krw_balance = INITIAL_KRW_BALANCE
    current_btc_balance = 0
    current_last_buy_price = None

    # 4. 백테스팅 메인 루프
    min_data_points_for_indicators = max(MA_LONG, ADX_WINDOW * 2) 

    if len(ohlcv_data) < min_data_points_for_indicators:
        print(f"⚠️ 백테스팅 시작을 위한 최소 데이터 ({min_data_points_for_indicators}개) 부족. 현재 {len(ohlcv_data)}개.")
        print("백테스팅 기간을 짧게 설정했거나, 데이터를 불러오지 못했을 수 있습니다.")
        return

    for i in range(min_data_points_for_indicators, len(ohlcv_data)):
        df_slice = ohlcv_data.iloc[:i+1].copy()

        df_slice['ma_short'] = df_slice['close'].rolling(MA_SHORT).mean()
        df_slice['ma_long'] = df_slice['close'].rolling(MA_LONG).mean()
        
        if len(df_slice) < ADX_WINDOW * 2: 
             continue 

        adx_indicator = ta.trend.ADXIndicator(df_slice['high'], df_slice['low'], df_slice['close'], window=ADX_WINDOW)
        df_slice['adx'] = adx_indicator.adx()
        
        df_slice.dropna(inplace=True)

        if len(df_slice) < 2:
            continue

        prev_day_data, current_day_data = df_slice.iloc[-2], df_slice.iloc[-1]
        today_date = current_day_data.name.date()
        today_close = current_day_data['close']

        portfolio_value_at_close = current_krw_balance + (current_btc_balance * today_close)
        portfolio_values.append({'date': today_date, 'value': portfolio_value_at_close})

        # ─────────────── 손절 조건 ───────────────
        if current_last_buy_price is not None and current_btc_balance > 0:
            if today_close <= current_last_buy_price * (1 - STOP_LOSS_PCT):
                sell_amount_krw = current_btc_balance * today_close * (1 - TRADE_FEE_RATE)
                current_krw_balance += sell_amount_krw
                
                trade_logs.append({
                    'date': today_date,
                    'type': 'SELL (Stop Loss)',
                    'price': today_close,
                    'amount_btc': current_btc_balance,
                    'amount_krw_gained': sell_amount_krw,
                    'balance_krw': current_krw_balance,
                    'balance_btc': 0,
                    'prev_buy_price': current_last_buy_price
                })
                current_btc_balance = 0
                current_last_buy_price = None
                continue

        # ─────────────── 매수 조건 ───────────────
        golden_cross = (prev_day_data['ma_short'] <= prev_day_data['ma_long'] and current_day_data['ma_short'] > current_day_data['ma_long']) or \
                       (current_day_data['ma_short'] > current_day_data['ma_long'])

        # <<<<< 이 부분을 수정했습니다. >>>>>
        if golden_cross and current_day_data['adx'] > ADX_BUY_THRESH and current_krw_balance >= MIN_KRW_TRADE:
            if current_btc_balance == 0:
                buy_amount_krw_to_use = current_krw_balance 
                buy_amount_btc = (buy_amount_krw_to_use * (1 - TRADE_FEE_RATE)) / today_close
                
                current_last_buy_price = today_close

                current_krw_balance = 0 

                trade_logs.append({
                    'date': today_date,
                    'type': 'BUY',
                    'price': today_close,
                    'amount_btc': buy_amount_btc,
                    'amount_krw_used': buy_amount_krw_to_use,
                    'balance_krw': current_krw_balance,
                    'balance_btc': current_btc_balance + buy_amount_btc,
                    'prev_buy_price': current_last_buy_price 
                })
                current_btc_balance += buy_amount_btc

        # ─────────────── 매도 조건 ───────────────
        death_cross = (prev_day_data['ma_short'] >= prev_day_data['ma_long'] and current_day_data['ma_short'] < current_day_data['ma_long']) or \
                      (current_day_data['ma_short'] < current_day_data['ma_long'])

        if (death_cross or current_day_data['adx'] < ADX_SELL_THRESH) and current_btc_balance > 0:
            sell_amount_krw = current_btc_balance * today_close * (1 - TRADE_FEE_RATE)
            current_krw_balance += sell_amount_krw

            trade_logs.append({
                'date': today_date,
                'type': 'SELL',
                'price': today_close,
                'amount_btc': current_btc_balance,
                'amount_krw_gained': sell_amount_krw,
                'balance_krw': current_krw_balance,
                'balance_btc': 0,
                'prev_buy_price': current_last_buy_price 
            })
            current_btc_balance = 0
            current_last_buy_price = None

    # 5. 백테스팅 결과 계산 및 출력
    print("\n📊 백테스팅 결과 분석 중...")

    final_portfolio_value = current_krw_balance
    if current_btc_balance > 0 and not ohlcv_data.empty:
        final_portfolio_value += (current_btc_balance * ohlcv_data.iloc[-1]['close'])

    initial_portfolio_value = INITIAL_KRW_BALANCE

    total_return = (final_portfolio_value / initial_portfolio_value) - 1

    print(f"\n--- 백테스팅 요약 ---")
    print(f"초기 투자 금액: {INITIAL_KRW_BALANCE:,.0f} KRW")
    print(f"최종 포트폴리오 가치: {final_portfolio_value:,.0f} KRW")
    print(f"총 누적 수익률: {total_return * 100:.2f}%")

    portfolio_df = pd.DataFrame(portfolio_values)
    if portfolio_df.empty:
        print("\n포트폴리오 가치 데이터가 없습니다. 월별 수익률 계산 불가.")
        return

    portfolio_df['date'] = pd.to_datetime(portfolio_df['date'])
    portfolio_df.set_index('date', inplace=True)

    monthly_portfolio_values = portfolio_df['value'].resample('M').last()
    
    monthly_returns = monthly_portfolio_values.pct_change()
    
    if not monthly_returns.empty:
        first_month_end_value = monthly_portfolio_values.iloc[0]
        monthly_returns.iloc[0] = (first_month_end_value / INITIAL_KRW_BALANCE) - 1

    print("\n--- 월별 수익률 ---")
    for date, ret in monthly_returns.items():
        if pd.notna(ret):
            print(f"{date.strftime('%Y년 %m월')}: {ret * 100:.2f}%")

    print("\n--- 월별 누적 수익률 (초기자산 대비) ---")
    if not monthly_portfolio_values.empty:
        cumulative_monthly_returns_initial_base = (monthly_portfolio_values / INITIAL_KRW_BALANCE) - 1
        for date, cum_ret in cumulative_monthly_returns_initial_base.items():
            if pd.notna(cum_ret):
                print(f"{date.strftime('%Y년 %m월')}: {cum_ret * 100:.2f}%")
    else:
        print("월별 누적 수익률을 계산할 데이터가 없습니다.")

    valid_monthly_returns = monthly_returns.dropna()
    if not valid_monthly_returns.empty:
        average_monthly_return = valid_monthly_returns.mean()
        print(f"\n월평균 수익률: {average_monthly_return * 100:.2f}%")
    else:
        print("\n월평균 수익률을 계산할 데이터가 충분하지 않습니다.")

# 백테스팅 실행
if __name__ == "__main__":
    run_backtest()