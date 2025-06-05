import ccxt
import os
import time
import requests
import pandas as pd
import datetime
from dotenv import load_dotenv

# ───────────────────────────────
# 1. 환경 변수 로드
# ───────────────────────────────
load_dotenv()
api_key = os.getenv('UPBIT_API_KEY')
secret_key = os.getenv('UPBIT_SECRET_KEY')
telegram_token = os.getenv('TELEGRAM_TOKEN')
telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')

# ───────────────────────────────
# 2. 객체 생성
# ───────────────────────────────
upbit = ccxt.upbit({
    'apiKey': api_key,
    'secret': secret_key,
})
upbit.load_markets()

# ───────────────────────────────
# 3. 텔레그램 전송 함수
# ───────────────────────────────
def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
        payload = {"chat_id": telegram_chat_id, "text": message}
        requests.post(url, data=payload)
    except Exception as e:
        print("❌ 텔레그램 전송 실패:", e)

# ───────────────────────────────
# 4. 기술 지표 함수 (RSI, MACD)
# ───────────────────────────────
def get_ohlcv():
    ohlcv = upbit.fetch_ohlcv('BTC/KRW', timeframe='1m', limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def compute_rsi(df, period=14):
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ma_up = up.rolling(window=period).mean()
    ma_down = down.rolling(window=period).mean()
    rs = ma_up / ma_down
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def compute_macd(df):
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()
    osc = macd - signal
    return osc.iloc[-1]

# ───────────────────────────────
# 5. 거래 가능 시간 확인 함수 (오전 8시 ~ 오후 11시로 수정)
# ───────────────────────────────
def is_trading_hour():
    hour = datetime.datetime.now().hour
    return 8 <= hour < 23  # 오전 8시 ~ 오후 10시 59분까지만 실행

# ───────────────────────────────
# 6. 봇 시작 메시지
# ───────────────────────────────
print("📊 RSI + MACD 기반 자동매매 봇 실행 시작")
send_telegram("🚀 RSI + MACD 자동매매 봇 시작됨!")

# ───────────────────────────────
# 7. 메인 루프
# ───────────────────────────────
while True:
    try:
        df = get_ohlcv()
        rsi = compute_rsi(df)
        macd_osc = compute_macd(df)

        ticker = upbit.fetch_ticker('BTC/KRW')
        current_price = ticker['last']
        now_str = time.strftime('%H:%M:%S')
        print(f"[{now_str}] 가격: {current_price}, MACD Osc: {macd_osc:.4f}, RSI: {rsi:.2f}")

        if not is_trading_hour():
            print("🌙 오전 8시~오후 11시 외 시간: 매매 중단 (분석만 수행)\n")
            time.sleep(90)  # 대기 시간도 늘림
            continue

        balances = upbit.fetch_balance()
        krw = balances['total'].get('KRW', 0)
        btc = balances['total'].get('BTC', 0)

        # ── 매수 전략: 분할 매수 2회 ──
        if rsi < 30 and macd_osc > 0 and krw >= 1000:
            for i in range(2):
                half_krw = krw * 0.5
                amount = half_krw / current_price
                order = upbit.create_market_buy_order('BTC/KRW', round(amount, 8))
                print(f"✅ {i+1}차 매수 완료:", order)
                send_telegram(f"✅ {i+1}차 매수 완료!\n금액: {half_krw:.0f}원\n수량: {round(amount, 8)} BTC\n가격: {current_price}원\nRSI: {rsi:.2f}, MACD Osc: {macd_osc:.2f}")
                time.sleep(300)
                krw = upbit.fetch_balance()['total'].get('KRW', 0)
                if rsi >= 30 or macd_osc <= 0:
                    print("📉 조건 변경으로 매수 중단\n")
                    break

        # ── 매도 전략: 전량 매도 ──
        elif rsi > 70 and macd_osc < 0 and btc > 0.0001:
            order = upbit.create_market_sell_order('BTC/KRW', round(btc, 8))
            print("📤 전량 매도 완료:", order)
            send_telegram(f"📤 전량 매도 완료!\n수량: {round(btc, 8)} BTC\n가격: {current_price}원\nRSI: {rsi:.2f}, MACD Osc: {macd_osc:.2f}")
            time.sleep(300)

        else:
            print("⏳ 조건 미충족: 대기 중...\n")

    except Exception as e:
        print("❌ 오류 발생:", e)
        send_telegram(f"❌ 오류 발생:\n{str(e)}")

    time.sleep(90)  # ➕ 반복 간격 늘려서 Railway 시간 절약