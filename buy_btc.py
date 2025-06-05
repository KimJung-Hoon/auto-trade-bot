import ccxt
import os
from dotenv import load_dotenv

# 1. .env 파일에서 API 키 불러오기
load_dotenv()
api_key = os.getenv('UPBIT_API_KEY')
secret_key = os.getenv('UPBIT_SECRET_KEY')

# 2. 업비트 객체 생성 (API 키 포함)
upbit = ccxt.upbit({
    'apiKey': api_key,
    'secret': secret_key,
})

# 3. 현재 BTC/KRW 가격 조회
ticker = upbit.fetch_ticker('BTC/KRW')
current_price = ticker['last']
print(f"현재 비트코인 가격: {current_price}원")

# 4. 매수 조건: 가격이 40000000원 미만일 때
buy_price_threshold = 40000000

if current_price < buy_price_threshold:
    print("💡 조건 만족! 자동으로 5,000원어치 매수 주문 실행 중...")

    # 5. 매수 주문 실행 (시장가, 5천원어치 = 약 5000 / 현재가격 개수)
    krw_to_spend = 5000  # 구매 금액 (원)
    amount = krw_to_spend / current_price

    order = upbit.create_market_buy_order(
        symbol='BTC/KRW',
        amount=round(amount, 8)  # 소수점 8자리로 제한
    )

    print("✅ 매수 주문 완료:", order)
else:
    print("⏳ 아직 조건에 맞지 않아서 대기 중입니다.")
