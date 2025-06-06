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
MIN_ORDER_KRW = 5000 # 업비트 BTC/KRW 최소 주문 금액

RSI_PERIOD = 14
RSI_BUY_THRESHOLD_PARTIAL = 35 # 50% 매수 RSI
RSI_BUY_THRESHOLD_FULL = 30    # 100% 매수 RSI
RSI_SELL_THRESHOLD_PARTIAL = 55 # 50% 매도 RSI
RSI_SELL_THRESHOLD_FULL = 60    # 100% 매도 RSI

STOP_LOSS_PERCENTAGE = 0.05 # 5% 손실 시 손절

TRADE_COOLDOWN_SECONDS = 300 # 5분

# 마지막 매수 가격을 저장할 변수 (봇 재시작 시 초기화됨에 유의)
last_buy_price = 0

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
        print(f"[{now}] 현재 BTC 가격: {current_price:,.0f}원")

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

        # ── 손절 조건 (BTC 보유 중일 때만 검사) ──
        if btc_balance > 0 and last_buy_price > 0:
            stop_loss_price = last_buy_price * (1 - STOP_LOSS_PERCENTAGE)
            if current_price <= stop_loss_price:
                print(f"🚨 손절 조건 만족! (매수 가격: {last_buy_price:,.0f}원, 현재 가격: {current_price:,.0f}원)")
                print(f"손실률: {((last_buy_price - current_price) / last_buy_price) * 100:.2f}% 이상")
                order = upbit.create_market_sell_order('BTC/KRW', round(btc_balance, 8))
                print("✅ 손절 매도 완료:", order)
                send_telegram(f"📉 손절 매도 완료! (RSI: {current_rsi:.2f})\n매수가: {last_buy_price:,.0f}원\n현재가: {current_price:,.0f}원\n손실률: {((last_buy_price - current_price) / last_buy_price) * 100:.2f}%\n수량: {round(btc_balance, 8)} BTC")
                last_buy_price = 0 # 손절 후 매수 가격 초기화
                time.sleep(TRADE_COOLDOWN_SECONDS) # 5분 대기

        # ── 매수 조건 ──
        # BTC 잔고가 없고 (현금 보유), 매수 가능한 KRW가 최소 주문 금액 이상일 때
        elif btc_balance == 0 and krw_balance >= MIN_ORDER_KRW:
            amount_to_buy_krw = 0
            if current_rsi <= RSI_BUY_THRESHOLD_FULL: # RSI 30 이하: 100% 매수
                amount_to_buy_krw = krw_balance
                buy_percentage = 100
                print(f"💡 매수 조건 만족 (RSI {RSI_BUY_THRESHOLD_FULL} 이하)! KRW 전액 매수 실행")
            elif current_rsi <= RSI_BUY_THRESHOLD_PARTIAL: # RSI 35 이하: 50% 매수
                amount_to_buy_krw = krw_balance * 0.5
                buy_percentage = 50
                print(f"💡 매수 조건 만족 (RSI {RSI_BUY_THRESHOLD_PARTIAL} 이하)! KRW 50% 매수 실행")
            
            if amount_to_buy_krw >= MIN_ORDER_KRW: # 매수 금액이 최소 주문 금액 이상일 때만 진행
                amount_btc = amount_to_buy_krw / current_price
                order = upbit.create_market_buy_order('BTC/KRW', round(amount_btc, 8))
                print("✅ 매수 완료:", order)
                # 매수 완료 후 last_buy_price 업데이트 (주문 정보에서 실제 체결 가격 가져오기)
                # 정확한 체결 가격을 얻기 위해 fetch_order 또는 fetch_my_trades를 사용할 수 있으나,
                # 여기서는 시장가 매수이므로 current_price를 임시로 사용합니다.
                # 실제 운영 시에는 order['price'] 또는 체결 내역을 확인하는 것이 좋습니다.
                last_buy_price = current_price # 간단하게 현재 가격을 매수 가격으로 가정
                send_telegram(f"💰 KRW {buy_percentage}% 매수 완료 (RSI: {current_rsi:.2f})\n가격: {current_price:,.0f}원\n수량: {round(amount_btc, 8)} BTC\n매수 금액: {amount_to_buy_krw:,.0f}원")
                time.sleep(TRADE_COOLDOWN_SECONDS) # 5분 대기 (중복 매수 방지)
            else:
                print(f"⏳ 매수 가능 KRW가 최소 주문 금액({MIN_ORDER_KRW}원) 미만이거나, RSI 조건에 해당하지 않습니다. 대기 중...\n")

        # ── 매도 조건 ──
        # BTC 잔고가 0보다 크고 (비트코인 보유)
        elif btc_balance > 0:
            amount_to_sell_btc = 0
            if current_rsi >= RSI_SELL_THRESHOLD_FULL: # RSI 60 이상: 100% 매도
                amount_to_sell_btc = btc_balance
                sell_percentage = 100
                print(f"📈 매도 조건 만족 (RSI {RSI_SELL_THRESHOLD_FULL} 이상)! 비트코인 전량 매도 실행")
            elif current_rsi >= RSI_SELL_THRESHOLD_PARTIAL: # RSI 55 이상: 50% 매도
                amount_to_sell_btc = btc_balance * 0.5
                sell_percentage = 50
                print(f"📈 매도 조건 만족 (RSI {RSI_SELL_THRESHOLD_PARTIAL} 이상)! 비트코인 50% 매도 실행")

            # 최소 매도 수량 (BTC/KRW는 0.00008 BTC 정도이나, 안전하게 0보다 크면 매도 시도)
            if amount_to_sell_btc > 0:
                order = upbit.create_market_sell_order('BTC/KRW', round(amount_to_sell_btc, 8))
                print("✅ 매도 완료:", order)
                send_telegram(f"📤 {sell_percentage}% 매도 완료 (RSI: {current_rsi:.2f})\n가격: {current_price:,.0f}원\n수량: {round(amount_to_sell_btc, 8)} BTC")
                
                # 전량 매도 시 last_buy_price 초기화
                if sell_percentage == 100:
                    last_buy_price = 0
                time.sleep(TRADE_COOLDOWN_SECONDS) # 5분 대기 (중복 매도 방지)
            else:
                print("⏳ 매도 조건 미충족: 대기 중...\n")

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