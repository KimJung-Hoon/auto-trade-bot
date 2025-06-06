import ccxt
import os
import time
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
buy_price_threshold = 142400000    # 4천만 원 이하일 때 매수
sell_price_threshold = 142379000    # 4천5백만 원 이상일 때 매도
krw_to_spend = 5000                # 매수 금액

print("🚀 자동 매수·매도 봇 시작! 1분마다 시세 확인 중...\n")

# ───────────────────────────────
# 4. 반복 감시
# ───────────────────────────────
while True:
    try:
        # 현재 시세 확인
        ticker = upbit.fetch_ticker('BTC/KRW')
        current_price = ticker['last']
        print(f"[{time.strftime('%H:%M:%S')}] 현재 BTC 가격: {current_price}원")

        # 내 잔고 정보 가져오기
        balances = upbit.fetch_balance()
        krw_balance = balances['total'].get('KRW', 0)
        btc_balance = balances['total'].get('BTC', 0)

        # ── 매수 조건 ──
        if current_price < buy_price_threshold and krw_balance >= krw_to_spend:
            amount = krw_to_spend / current_price
            print("💡 매수 조건 만족! 비트코인 매수 실행")
            order = upbit.create_market_buy_order('BTC/KRW', krw_to_spend, params={"cost": krw_to_spend})
            print("✅ 매수 완료:", order)
            time.sleep(300)  # 5분 대기 후 재시작

        # ── 매도 조건 ──
        elif current_price > sell_price_threshold and btc_balance > 0:
            print("📈 매도 조건 만족! 비트코인 전량 매도 실행")
            order = upbit.create_market_sell_order('BTC/KRW', round(btc_balance, 8))
            print("✅ 매도 완료:", order)
            time.sleep(300)  # 5분 대기 후 재시작

        else:
            print("⏳ 조건 미충족: 대기 중...\n")

    except Exception as e:
        print("❌ 오류 발생:", e)

    time.sleep(60)  # 1분마다 반복
