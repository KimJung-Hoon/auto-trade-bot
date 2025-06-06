import ccxt
import os
import time
import requests
from dotenv import load_dotenv
import pandas as pd
import ta

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
    'options': {
        'defaultType': 'spot',
    },
})

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
# 4. 설정 값
# ───────────────────────────────
# KRW 전액 매수를 위해 krw_to_spend 대신 실제 잔고를 사용합니다.
MIN_ORDER_KRW = 5000 # 업비트 BTC/KRW 최소 주문 금액

RSI_PERIOD = 14
RSI_BUY_THRESHOLD = 35
RSI_SELL_THRESHOLD = 55

# 매수/매도 후 잠시 대기하여 중복 주문 방지
TRADE_COOLDOWN_SECONDS = 300 # 5분

print("🚀 자동 매수·매도 봇 시작! 1분마다 시세 및 RSI 확인 중...\n")
send_telegram("🤖 자동매매 봇 시작됨 (1분마다 시세 및 RSI 감시 중)")

# ───────────────────────────────
# 5. 반복 감시
# ───────────────────────────────
while True:
    try:
        # 현재 시세 확인
        ticker = upbit.fetch_ticker('BTC/KRW')
        current_price = ticker['last']
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{now}] 현재 BTC 가격: {current_price}원")

        # 내 잔고 정보 가져오기
        balances = upbit.fetch_balance()
        krw_balance = balances['total'].get('KRW', 0)
        btc_balance = balances['total'].get('BTC', 0)
        
        # 보유 BTC의 현재가치 (평가액)
        btc_value_in_krw = btc_balance * current_price

        print(f"현재 KRW 잔고: {krw_balance:,.0f}원")
        print(f"현재 BTC 잔고: {btc_balance:.8f} BTC ({btc_value_in_krw:,.0f}원)\n")

        # 60분봉 데이터 가져오기 (RSI 계산에 충분한 과거 데이터)
        ohlcv = upbit.fetch_ohlcv('BTC/KRW', '1h', limit=RSI_PERIOD * 2)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df['close'] = pd.to_numeric(df['close'])

        # RSI 계산
        df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=RSI_PERIOD).rsi()
        current_rsi = df['rsi'].iloc[-1] # 가장 최근 60분봉의 RSI 값
        print(f"현재 60분봉 RSI: {current_rsi:.2f}\n")

        # ── 매수 조건 ──
        # BTC 잔고가 없고 (현금 보유), RSI가 매수 임계값 이하이며, 매수 가능한 KRW가 최소 주문 금액 이상일 때
        if btc_balance == 0 and current_rsi <= RSI_BUY_THRESHOLD and krw_balance >= MIN_ORDER_KRW:
            amount_to_buy_krw = krw_balance # KRW 전액 매수
            
            # Upbit 최소 주문 금액 (5000원) 미만이면 매수 시도하지 않음
            if amount_to_buy_krw < MIN_ORDER_KRW:
                print(f"⏳ 매수 가능 KRW가 최소 주문 금액({MIN_ORDER_KRW}원) 미만입니다. 대기 중...\n")
            else:
                amount_btc = amount_to_buy_krw / current_price
                print("💡 매수 조건 만족 (RSI 35 이하)! 비트코인 KRW 전액 매수 실행")
                order = upbit.create_market_buy_order('BTC/KRW', round(amount_btc, 8))
                print("✅ 매수 완료:", order)
                send_telegram(f"💰 KRW 전액 매수 완료 (RSI: {current_rsi:.2f})\n가격: {current_price:,.0f}원\n수량: {round(amount_btc, 8)} BTC\n매수 금액: {amount_to_buy_krw:,.0f}원")
                time.sleep(TRADE_COOLDOWN_SECONDS) # 5분 대기 (중복 매수 방지)

        # ── 매도 조건 ──
        # BTC 잔고가 0보다 크고 (비트코인 보유), RSI가 매도 임계값 이상일 때
        elif btc_balance > 0 and current_rsi >= RSI_SELL_THRESHOLD:
            print("📈 매도 조건 만족 (RSI 55 이상)! 비트코인 전량 매도 실행")
            # Upbit 최소 매도 수량은 코인마다 다르지만, 일반적으로 0보다 크면 매도 가능.
            # 정확한 최소 수량 확인 필요시 'min_amount_sell' 등을 사용해야 함.
            order = upbit.create_market_sell_order('BTC/KRW', round(btc_balance, 8))
            print("✅ 매도 완료:", order)
            send_telegram(f"📤 전량 매도 완료 (RSI: {current_rsi:.2f})\n가격: {current_price:,.0f}원\n수량: {round(btc_balance, 8)} BTC")
            time.sleep(TRADE_COOLDOWN_SECONDS) # 5분 대기 (중복 매도 방지)

        else:
            print("⏳ 조건 미충족: 대기 중...\n")

    except ccxt.NetworkError as e:
        print(f"❌ 네트워크 오류 발생: {e}")
        send_telegram(f"❌ 네트워크 오류: {str(e)}")
        time.sleep(10) # 잠시 대기 후 재시도
    except ccxt.ExchangeError as e:
        print(f"❌ 거래소 오류 발생: {e}")
        send_telegram(f"❌ 거래소 오류: {str(e)}")
        # 예: 최소 주문 금액 미달, 잔고 부족 등. 오류 메시지에 따라 대응 필요.
        time.sleep(10)
    except Exception as e:
        print(f"❌ 예상치 못한 오류 발생: {e}")
        send_telegram(f"❌ 예상치 못한 오류: {str(e)}")
        time.sleep(10)

    time.sleep(60) # 1분마다 반복 (매수/매도 후 대기시간은 별도 적용)