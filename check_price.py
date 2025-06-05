import ccxt

# 1. 업비트 객체 만들기
upbit = ccxt.upbit()

# 2. 비트코인 가격 가져오기
ticker = upbit.fetch_ticker('BTC/KRW')
current_price = ticker['last']
print(f"현재 비트코인 가격: {current_price}원")

# 3. 아주 간단한 매매 전략: 싸졌으면 사자
buy_price_threshold = 40000000  # 4천만 원

if current_price < buy_price_threshold:
    print("💡 지금은 싸니까 비트코인을 사야 해요!")
else:
    print("⏳ 아직 기다려야 해요.")
