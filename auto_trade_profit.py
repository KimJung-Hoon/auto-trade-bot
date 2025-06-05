import ccxt
import os
import time
import csv
from dotenv import load_dotenv

# ───────────────────────────────
# 1. API 키 불러오기
# ───────────────────────────────
load_dotenv()
api_key = os.getenv('UPBIT_API_KEY')
secret_key = os.getenv('UPBIT_SECRET_KEY')

# ───────────────────────────────
# 2. 업비트 객체 생성
# ───────────────────────────────
upbit = ccxt.upbit({
    'apiKey': api_key,
    'secret': secret_key,
})

# ───────────────────────────────
# 3. 설정 값
# ───────────────────────────────
buy_price_threshold = 40000000
sell_price_threshold = 45000000
krw_to_spend = 5000

# 거래 기록 저장용 CSV 파일
LOG_FILE = 'trade_log.csv'

# ───────────────────────────────
# 4. CSV 로그 파일 초기화 (없으면 생성)
# ───────────────────────────────
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['시간', '유형', '가격', '수량', '금액', '수익률(%)'])

# ───────────────────────────────
# 5. 매매 이력 보관용 변수
# ───────────────────────────────
last_buy_price = None
last_buy_amount = None

# ───────────────────────────────
# 6. 반복 감시 시작
# ───────────────────────────────
print("🚀 자동 수익률 계산 봇 시작!\n")

while True:
    try:
        ticker = upbit.fetch_ticker('BTC/KRW')
        current_price = ticker['last']
        print(f"[{time.strftime('%H:%M:%S')}] 현재 BTC 가격: {current_price}원")

        balances = upbit.fetch_balance()
        krw_balance = balances['total'].get('KRW', 0)
        btc_balance = balances['total'].get('BTC', 0)

        # ── 매수 조건 ──
        if current_price < buy_price_threshold and krw_balance >= krw_to_spend:
            amount = krw_to_spend / current_price
            order = upbit.create_market_buy_order('BTC/KRW', round(amount, 8))
            last_buy_price = current_price
            last_buy_amount = amount
            print("✅ 매수 완료:", order)

            with open(LOG_FILE, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    time.strftime('%Y-%m-%d %H:%M:%S'),
                    '매수',
                    current_price,
                    round(amount, 8),
                    krw_to_spend,
                    ''
                ])
            time.sleep(300)

        # ── 매도 조건 ──
        elif current_price > sell_price_threshold and btc_balance > 0:
            order = upbit.create_market_sell_order('BTC/KRW', round(btc_balance, 8))
            sell_amount = round(btc_balance, 8)
            sell_total = current_price * sell_amount

            if last_buy_price:
                buy_total = last_buy_price * last_buy_amount
                profit_percent = round((sell_total - buy_total) / buy_total * 100, 2)
            else:
                profit_percent = 'N/A'

            print("✅ 매도 완료:", order)
            print(f"📊 예상 수익률: {profit_percent}%")

            with open(LOG_FILE, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    time.strftime('%Y-%m-%d %H:%M:%S'),
                    '매도',
                    current_price,
                    sell_amount,
                    round(sell_total, 2),
                    profit_percent
                ])
            time.sleep(300)

        else:
            print("⏳ 조건 미충족: 대기 중...\n")

    except Exception as e:
        print("❌ 오류 발생:", e)

    time.sleep(60)
