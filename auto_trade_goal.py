import ccxt
import os
import time
import requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

# ───────────────────────────────
# 1. 환경변수 로드
# ───────────────────────────────
load_dotenv()
api_key = os.getenv('UPBIT_API_KEY')
secret_key = os.getenv('UPBIT_SECRET_KEY')
telegram_token = os.getenv('TELEGRAM_TOKEN')
telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')

# ───────────────────────────────
# 2. 업비트 객체 생성
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
# 4. 전역 변수 설정
# ───────────────────────────────
symbol = 'BTC/KRW'
k = 0.5
profit_target = 0.025      # +2.5%
trailing_trigger = 0.015   # +1.5%
trailing_gap = 0.005       # -0.5%
stop_loss = 0.012          # -1.2%
krw_to_spend = 5000

bought = False
buy_price = 0
peak_price = 0

# ───────────────────────────────
# 5. 전략에 필요한 가격 정보 계산
# ───────────────────────────────
def get_target_price():
    ohlcv = upbit.fetch_ohlcv(symbol, timeframe='1d', limit=2)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    yesterday = df.iloc[-2]
    today_open = df.iloc[-1]['open']
    target_price = today_open + (yesterday['high'] - yesterday['low']) * k
    return round(target_price, 0)

def get_current_price():
    return upbit.fetch_ticker(symbol)['last']

def get_balance():
    balance = upbit.fetch_balance()
    return balance['total'].get('BTC', 0)

# ───────────────────────────────
# 6. 메인 루프
# ───────────────────────────────
send_telegram("🚀 자동매매 봇 시작 (전략: 변동성 돌파 + 수익목표 + 트레일링 스탑)")

while True:
    try:
        now = datetime.now()

        # 9:00~22:00 사이만 실행
        if now.hour < 9 or now.hour >= 22:
            time.sleep(60)
            continue

        current_price = get_current_price()
        target_price = get_target_price()

        # ── 매수 조건 ──
        if not bought and current_price > target_price:
            # 업비트는 market buy에서 KRW를 cost로 넘겨야 함
            order = upbit.create_market_buy_order(symbol, krw_to_spend, params={"cost": krw_to_spend})
            buy_price = current_price
            peak_price = current_price
            bought = True
            btc_amount = get_balance()
            send_telegram(f"✅ 매수 완료: 가격={buy_price:,.0f}원, 수량={btc_amount:.6f} BTC")

        # ── 매도 조건 ──
        elif bought:
            # ① 최고가 갱신 시 peak_price 업데이트
            if current_price > peak_price:
                peak_price = current_price

            # ② 수익 목표 도달 시 매도
            if current_price >= buy_price * (1 + profit_target):
                amount = get_balance()
                upbit.create_market_sell_order(symbol, amount)
                send_telegram(f"🎯 목표 수익 도달! 매도 완료: 현재가={current_price:,.0f}원")
                bought = False
                time.sleep(60)
                continue

            # ③ 트레일링 스탑 발동 시 매도
            if peak_price >= buy_price * (1 + trailing_trigger) and current_price <= peak_price * (1 - trailing_gap):
                amount = get_balance()
                upbit.create_market_sell_order(symbol, amount)
                send_telegram(f"📉 트레일링 스탑 발동! 매도 완료: 현재가={current_price:,.0f}원")
                bought = False
                time.sleep(60)
                continue

            # ④ 손절 조건 만족 시 매도
            if current_price <= buy_price * (1 - stop_loss):
                amount = get_balance()
                upbit.create_market_sell_order(symbol, amount)
                send_telegram(f"🛑 손절 매도 실행: 현재가={current_price:,.0f}원")
                bought = False
                time.sleep(60)
                continue

        time.sleep(30)

    except Exception as e:
        print("❌ 오류 발생:", e)
        send_telegram(f"❌ 오류 발생: {str(e)}")
        time.sleep(60)
