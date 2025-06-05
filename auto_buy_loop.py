import ccxt
import os
import time
from dotenv import load_dotenv

# 1. 환경변수(.env 파일)에서 API 키 불러오기
load_dotenv()
api_key = os.getenv('UPBIT_API_KEY')
secret_key = os.getenv('UPBIT_SECRET_KEY')

# 2. 업비트 객체 생성
upbit = ccxt.upbit({
    'apiKey': api_key,
    'secret': secret_key,
})

# 3. 반복 감시 로직 시작
buy_price_threshold = 40000000   # 매수 기준 가격
krw_to_spend = 5000              # 한 번에 매수할 금액 (원)

print("🚀 자동 매수 봇 시작! 60초마다 시세 확인 중...\n")

while True:
    try:
        # ① 현재 가격 불러오기
        ticker = upbit.fetch_ticker('BTC/KRW')
        current_price = ticker['last']
        print(f"[{time.strftime('%H:%M:%S')}] 현재 BTC 가격: {current_price}원")

        # ② 매수 조건 판단
        if current_price < buy_price_threshold:
            print("💡 조건 만족! 매수 주문을 실행합니다.")
            amount = krw_to_spend / current_price

            order = upbit.create_market_buy_order(
                symbol='BTC/KRW',
                amount=round(amount, 8)
            )

            print("✅ 매수 주문 완료:", order)
            print("⏸️ 5분간 쉬었다가 다시 시작합니다.\n")
            time.sleep(300)  # 5분 대기 후 다시 시작

        else:
            print("⏳ 조건 미충족: 매수하지 않고 대기 중.\n")

    except Exception as e:
        print("❌ 오류 발생:", e)

    # ③ 다음 확인 전 60초 대기
    time.sleep(60)
