import ccxt
import os
import time
import csv
import pandas as pd
from dotenv import load_dotenv

# ─────── 1. API 키 로드 ───────
load_dotenv()
api_key = os.getenv('UPBIT_API_KEY')
secret_key = os.getenv('UPBIT_SECRET_KEY')

upbit = ccxt.upbit({
    'apiKey': api_key,
    'secret': secret_key,
})

# ─────── 2. CSV 로그 초기화 ───────
LOG_FILE = 'trade_log.csv'
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['시간', '유형', '가격', '수량', '금액', '수익률(%)'])

# ─────── 3. 상태 변수 ───────
krw_to_spend = 5000
last_buy_price = None
last_buy_amount = None
symbol = 'BTC/KRW'
interval = '1m'  # ← 1분봉으로 변경
limit = 100

# ─────── 4. 지표 계산 함수 ───────
def get_ohlcv(symbol='BTC/KRW', timeframe='1m', limit=100):
    ohlcv = upbit.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def calculate_indicators(df):
    close = df['close']

    # RSI 계산
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()
    rs = avg_gain / avg_loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # MACD 계산
    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    macd = ema_12 - ema_26
    signal = macd.ewm(span=9, adjust=False).mean()
    df['macd_osc'] = macd - signal

    # 볼린저밴드 계산
    ma20 = close.rolling(window=20).mean()
    std = close.rolling(window=20).std()
    df['bb_upper'] = ma20 + (2 * std)
    df['bb_lower'] = ma20 - (2 * std)
    df['bb_mid'] = ma20

    return df

# ─────── 5. 매매 루프 ───────
print("🚀 1분봉 + RSI≥35 전략 자동매매 봇 시작!\n")

while True:
    try:
        df = get_ohlcv(symbol, interval, limit)
        df = calculate_indicators(df)

        current_price = df['close'].iloc[-1]
        macd_osc = df['macd_osc'].iloc[-1]
        rsi_prev = df['rsi'].iloc[-2]
        rsi_curr = df['rsi'].iloc[-1]
        bb_lower = df['bb_lower'].iloc[-1]
        bb_mid = df['bb_mid'].iloc[-1]

        balances = upbit.fetch_balance()
        krw_balance = balances['total'].get('KRW', 0)
        btc_balance = balances['total'].get('BTC', 0)

        print(f"[{time.strftime('%H:%M:%S')}] 가격: {current_price}, MACD Osc: {macd_osc:.4f}, RSI: {rsi_curr:.2f}")

        # 🔄 복합 매수 조건 (RSI 기준 완화)
        is_macd_up = macd_osc > 0
        is_rsi_rebound = rsi_prev < 35 and rsi_curr >= 35
        is_bb_rebound = current_price > bb_lower and current_price > bb_mid

        if is_macd_up and is_rsi_rebound and is_bb_rebound and krw_balance >= krw_to_spend:
            amount = krw_to_spend / current_price
            order = upbit.create_market_buy_order(symbol, round(amount, 8))
            last_buy_price = current_price
            last_buy_amount = amount
            print("✅ 매수 완료:", order)

            with open(LOG_FILE, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    time.strftime('%Y-%m-%d %H:%M:%S'), '매수',
                    current_price, round(amount, 8), krw_to_spend, ''
                ])
            time.sleep(300)

        # 🔁 매도 조건 (기존 유지)
        elif (rsi_curr > 70 or (last_buy_price and current_price > last_buy_price * 1.05)) and btc_balance > 0:
            order = upbit.create_market_sell_order(symbol, round(btc_balance, 8))
            sell_total = current_price * btc_balance
            buy_total = last_buy_price * last_buy_amount if last_buy_price else 0
            profit_percent = round((sell_total - buy_total) / buy_total * 100, 2) if buy_total else 'N/A'

            print("✅ 매도 완료:", order)
            print(f"📊 수익률: {profit_percent}%")

            with open(LOG_FILE, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    time.strftime('%Y-%m-%d %H:%M:%S'), '매도',
                    current_price, round(btc_balance, 8), round(sell_total, 2), profit_percent
                ])
            time.sleep(300)

        else:
            print("⏳ 조건 미충족: 대기 중...\n")

    except Exception as e:
        print("❌ 오류 발생:", e)

    time.sleep(60)
