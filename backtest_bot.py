import ccxt 
import os 
import time 
import requests 
from dotenv import load_dotenv 
import pandas as pd 
import ta 
from datetime import datetime, timedelta

# ───────────────────────────────
# 1. 환경변수 로드 (백테스트에서는 API 키 사용 안 함)
# ───────────────────────────────
load_dotenv()
# 백테스트에서는 실제 API 키 및 텔레그램 토큰 사용 안 함
# telegram_token = os.getenv('TELEGRAM_TOKEN') 
# telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID') 

# ───────────────────────────────
# 2. 업비트 객체 생성 (데이터 로드용)
# ───────────────────────────────
# 백테스트에서는 실제 거래가 아닌 데이터 로드용으로만 사용
upbit = ccxt.upbit({ 
    'options': { 
        'defaultType': 'spot', 
    }, 
}) 

# ───────────────────────────────
# 3. 텔레그램 전송 함수 (백테스트에서는 사용 안 함)
# ───────────────────────────────
def send_telegram(message):
    # 백테스트에서는 텔레그램 메시지 전송하지 않음
    pass

# ───────────────────────────────
# 4. 설정 값 (자동매매 코드와 동일하게 유지)
# ───────────────────────────────
MIN_ORDER_KRW = 5000 # 업비트 BTC/KRW 최소 주문 금액 (백테스트에서도 동일 적용)
TRADE_FEE_RATE = 0.0005 # 업비트 수수료 0.05%

RSI_PERIOD = 14 
RSI_BUY_THRESHOLD = 35 
RSI_SELL_THRESHOLD = 55 # 요청에 따라 55로 설정

MA_SHORT_PERIOD = 50 
MA_LONG_PERIOD = 200 

STOP_LOSS_PERCENT = 0.05 

# ───────────────────────────────
# 5. 백테스트 설정
# ───────────────────────────────
INITIAL_KRW_BALANCE = 1000000 # 초기 자본금 100만원
BACKTEST_PERIOD_DAYS = 365 * 2 # 2년치 데이터 (365일 * 2)

print("🚀 비트코인 자동매매 백테스트 시작!\n")

def run_backtest():
    # 백테스트 시작 및 종료 날짜 설정
    end_date = datetime.now()
    start_date = end_date - timedelta(days=BACKTEST_PERIOD_DAYS)

    print(f"백테스트 기간: {start_date.strftime('%Y-%m-%d %H:%M:%S')} 부터 {end_date.strftime('%Y-%m-%d %H:%M:%S')} 까지")

    # 과거 1시간봉 데이터 로드
    all_ohlcv = []
    current_fetch_time = start_date
    
    # Upbit API 호출 제한 (1초에 60회) 고려, 한 번에 200개 데이터 가져옴
    while current_fetch_time < end_date:
        try:
            # 타임스탬프는 밀리초 단위로 변환
            ohlcv_chunk = upbit.fetch_ohlcv(
                'BTC/KRW', 
                '1h', 
                since=int(current_fetch_time.timestamp() * 1000), 
                limit=200
            )
            if not ohlcv_chunk:
                break # 더 이상 데이터가 없으면 종료
            all_ohlcv.extend(ohlcv_chunk)
            # 다음 요청 시작 시간을 마지막 데이터의 시간 + 1시간으로 설정
            current_fetch_time = datetime.fromtimestamp((all_ohlcv[-1][0] + 3600000) / 1000)
            time.sleep(0.1) # Upbit API 요청 제한을 위한 대기
            print(f"데이터 로드 중... 현재까지 {len(all_ohlcv)}개의 봉 데이터 확보. 마지막 봉 시각: {datetime.fromtimestamp(all_ohlcv[-1][0]/1000).strftime('%Y-%m-%d %H:%M:%S')}")
            
            # API 제한에 걸리지 않도록 넉넉하게 대기
            if len(all_ohlcv) % 1000 == 0:
                 time.sleep(1)

        except ccxt.NetworkError as e:
            print(f"❌ 네트워크 오류 발생: {e}. 잠시 후 재시도...")
            time.sleep(5)
        except ccxt.ExchangeError as e:
            print(f"❌ 거래소 오류 발생: {e}. 잠시 후 재시도...")
            time.sleep(5)
        except Exception as e:
            print(f"❌ 데이터 로드 중 예상치 못한 오류 발생: {e}. 잠시 후 재시도...")
            time.sleep(5)
    
    if not all_ohlcv:
        print("백테스트를 위한 과거 데이터를 충분히 불러오지 못했습니다. 종료합니다.")
        return

    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df['close'] = pd.to_numeric(df['close'])
    
    # 시간 순서로 정렬 (혹시 뒤섞여 있을 경우를 대비)
    df.sort_index(inplace=True)

    # RSI 및 이동평균선 계산
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=RSI_PERIOD).rsi() 
    df['ma_short'] = ta.trend.SMAIndicator(df['close'], window=MA_SHORT_PERIOD).sma_indicator()
    df['ma_long'] = ta.trend.SMAIndicator(df['close'], window=MA_LONG_PERIOD).sma_indicator()

    # NaN 값 제거 (지표 계산을 위해 필요한 초기 데이터 부족 부분)
    df.dropna(inplace=True)
    
    if df.empty:
        print("지표 계산 후 유효한 데이터가 없습니다. 백테스트를 진행할 수 없습니다.")
        return

    print(f"\n총 {len(df)}개의 유효한 1시간봉 데이터로 백테스트를 시작합니다.")

    # 백테스트를 위한 변수 초기화
    krw_balance = INITIAL_KRW_BALANCE
    btc_balance = 0.0
    bought_price = 0.0 # 매수했던 가격
    trades = [] # 거래 내역 저장 (날짜, 유형, 가격, 수량, KRW 변화, BTC 변화, 잔고)

    # 이전 달 기록을 위한 변수
    last_month = df.index[0].month
    monthly_start_krw = INITIAL_KRW_BALANCE
    monthly_returns = {}

    for i, row in df.iterrows():
        current_time = row.name
        current_price = row['close']
        current_rsi = row['rsi']
        current_ma_short = row['ma_short']
        current_ma_long = row['ma_long']

        # 월별 수익률 계산을 위한 로직
        if current_time.month != last_month:
            # 이전 달의 수익률 계산 및 저장
            monthly_end_krw = krw_balance + (btc_balance * current_price)
            monthly_profit = monthly_end_krw - monthly_start_krw
            monthly_return_percent = (monthly_profit / monthly_start_krw) * 100 if monthly_start_krw > 0 else 0
            monthly_returns[current_time.replace(day=1)] = monthly_return_percent 
            
            # 다음 달의 시작 자본금 설정
            monthly_start_krw = krw_balance + (btc_balance * current_price)
            last_month = current_time.month

        # ── 손절 조건 (가장 먼저 검사) ──
        if btc_balance > 0 and bought_price > 0:
            loss_percent = (bought_price - current_price) / bought_price 
            if loss_percent >= STOP_LOSS_PERCENT:
                # 손절 매도
                sell_amount_btc = btc_balance
                krw_gained = sell_amount_btc * current_price * (1 - TRADE_FEE_RATE)
                krw_balance += krw_gained
                btc_balance = 0.0
                trades.append({
                    'timestamp': current_time,
                    'type': 'SELL (Stop Loss)',
                    'price': current_price,
                    'btc_amount': sell_amount_btc,
                    'krw_change': krw_gained,
                    'btc_change': -sell_amount_btc,
                    'krw_balance': krw_balance,
                    'btc_balance': btc_balance
                })
                bought_price = 0 # 매수 가격 초기화
                continue # 손절 후 다른 조건 확인하지 않고 다음 봉으로 넘어감

        # ── 매수 조건 ──
        if (btc_balance == 0 and 
            current_rsi <= RSI_BUY_THRESHOLD and 
            krw_balance >= MIN_ORDER_KRW and
            current_ma_short > current_ma_long): # 골든 크로스 조건

            amount_to_buy_krw = krw_balance # KRW 전액 매수 
            
            if amount_to_buy_krw >= MIN_ORDER_KRW:
                buy_amount_btc = (amount_to_buy_krw / current_price) * (1 - TRADE_FEE_RATE)
                krw_balance -= amount_to_buy_krw
                btc_balance += buy_amount_btc
                bought_price = current_price # 매수 가격 기록
                trades.append({
                    'timestamp': current_time,
                    'type': 'BUY',
                    'price': current_price,
                    'btc_amount': buy_amount_btc,
                    'krw_change': -amount_to_buy_krw,
                    'btc_change': buy_amount_btc,
                    'krw_balance': krw_balance,
                    'btc_balance': btc_balance
                })

        # ── 매도 조건 ──
        elif btc_balance > 0 and current_rsi >= RSI_SELL_THRESHOLD: 
            sell_amount_btc = btc_balance
            krw_gained = sell_amount_btc * current_price * (1 - TRADE_FEE_RATE)
            krw_balance += krw_gained
            btc_balance = 0.0
            trades.append({
                'timestamp': current_time,
                'type': 'SELL',
                'price': current_price,
                'btc_amount': sell_amount_btc,
                'krw_change': krw_gained,
                'btc_change': -sell_amount_btc,
                'krw_balance': krw_balance,
                'btc_balance': btc_balance
            })
            bought_price = 0 # 매도했으므로 매수 가격 초기화

    # 백테스트 종료 시점에 남아있는 자산 처리 (현금 + BTC 평가액)
    final_krw_balance = krw_balance + (btc_balance * df['close'].iloc[-1])
    
    # 마지막 월 수익률 계산 (백테스트 종료 시점의 달)
    monthly_end_krw = krw_balance + (btc_balance * df['close'].iloc[-1])
    monthly_profit = monthly_end_krw - monthly_start_krw
    monthly_return_percent = (monthly_profit / monthly_start_krw) * 100 if monthly_start_krw > 0 else 0
    monthly_returns[df.index[-1].replace(day=1)] = monthly_return_percent

    # ───────────────────────────────
    # 6. 백테스트 결과 출력
    # ───────────────────────────────
    print("\n--- 백테스트 결과 ---")

    # 누적 수익률 계산
    cumulative_return = ((final_krw_balance - INITIAL_KRW_BALANCE) / INITIAL_KRW_BALANCE) * 100
    print(f"초기 자본: {INITIAL_KRW_BALANCE:,.0f}원")
    print(f"최종 자산: {final_krw_balance:,.0f}원")
    print(f"누적 수익률: {cumulative_return:.2f}%")

    # 월별 수익률 출력
    print("\n--- 월별 수익률 ---")
    # 월별 수익률 딕셔너리를 날짜 기준으로 정렬
    sorted_monthly_returns = sorted(monthly_returns.items())
    for month_start, ret in sorted_monthly_returns:
        print(f"{month_start.strftime('%Y년 %m월')}: {ret:.2f}%")

    print("\n--- 전체 거래 내역 (상위 10개) ---")
    trades_df = pd.DataFrame(trades)
    if not trades_df.empty:
        print(trades_df.head(10))
        print(f"\n총 {len(trades_df)}건의 거래 발생.")
    else:
        print("거래가 발생하지 않았습니다.")

    # 추가적으로 원금만으로 비트코인을 보유했을 때의 수익률 (벤치마크)
    print("\n--- 벤치마크 (BTC 단순 보유) ---")
    # 시작 시점 비트코인 가격
    benchmark_initial_price = df['close'].iloc[0]
    # 종료 시점 비트코인 가격
    benchmark_final_price = df['close'].iloc[-1]
    
    # 초기 자본으로 구매할 수 있었던 BTC 수량
    initial_btc_amount_benchmark = INITIAL_KRW_BALANCE / benchmark_initial_price
    # 최종 BTC 가치
    final_btc_value_benchmark = initial_btc_amount_benchmark * benchmark_final_price
    # 벤치마크 수익률
    benchmark_return = ((final_btc_value_benchmark - INITIAL_KRW_BALANCE) / INITIAL_KRW_BALANCE) * 100
    print(f"시작 시점 BTC 가격: {benchmark_initial_price:,.0f}원")
    print(f"종료 시점 BTC 가격: {benchmark_final_price:,.0f}원")
    print(f"BTC 단순 보유 시 최종 자산: {final_btc_value_benchmark:,.0f}원")
    print(f"BTC 단순 보유 시 수익률: {benchmark_return:.2f}%")

# 백테스트 실행
if __name__ == "__main__":
    run_backtest()