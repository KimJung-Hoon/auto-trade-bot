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
MIN_ORDER_KRW = 5000

RSI_PERIOD = 14 
RSI_BUY_THRESHOLD = 35 
RSI_SELL_THRESHOLD = 55 # 매도 RSI 임계값을 60에서 55로 변경

MA_SHORT_PERIOD = 50 
MA_LONG_PERIOD = 200 

TRADE_COOLDOWN_SECONDS = 300 
STOP_LOSS_PERCENT = 0.05 
bought_price = 0 

print("🚀 자동 매수·매도 봇 시작! 1분마다 시세 및 RSI, 이동평균선 확인 중...\n") 
send_telegram("🤖 자동매매 봇 시작됨 (1분마다 시세 및 RSI, 이동평균선 감시 중)") 

# ─────────────────────────────── 
# 5. 반복 감시 
# ─────────────────────────────── 
while True: 
    try: 
        ticker = upbit.fetch_ticker('BTC/KRW') 
        current_price = ticker['last'] 
        now = time.strftime('%Y-%m-%d %H:%M:%S') 
        print(f"[{now}] 현재 BTC 가격: {current_price:,.0f}원") 

        balances = upbit.fetch_balance() 
        krw_balance = balances['total'].get('KRW', 0) 
        btc_balance = balances['total'].get('BTC', 0) 
        btc_value_in_krw = btc_balance * current_price 

        print(f"현재 KRW 잔고: {krw_balance:,.0f}원") 
        print(f"현재 BTC 잔고: {btc_balance:.8f} BTC ({btc_value_in_krw:,.0f}원)\n") 

        ohlcv = upbit.fetch_ohlcv('BTC/KRW', '1h', limit=max(RSI_PERIOD * 2, MA_LONG_PERIOD + 10)) 
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']) 
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') 
        df['close'] = pd.to_numeric(df['close']) 

        df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=RSI_PERIOD).rsi() 
        current_rsi = df['rsi'].iloc[-1] 
        print(f"현재 60분봉 RSI: {current_rsi:.2f}\n") 

        df['ma_short'] = ta.trend.SMAIndicator(df['close'], window=MA_SHORT_PERIOD).sma_indicator()
        df['ma_long'] = ta.trend.SMAIndicator(df['close'], window=MA_LONG_PERIOD).sma_indicator()

        current_ma_short = df['ma_short'].iloc[-1] 
        current_ma_long = df['ma_long'].iloc[-1] 

        print(f"현재 50분 이동평균선: {current_ma_short:,.0f}원") 
        print(f"현재 200분 이동평균선: {current_ma_long:,.0f}원\n") 

        if btc_balance > 0 and bought_price > 0: 
            loss_percent = (bought_price - current_price) / bought_price 
            if loss_percent >= STOP_LOSS_PERCENT: 
                print(f"🚨 손절 조건 만족 (손실률: {loss_percent:.2%})! 비트코인 전량 매도 실행") 
                order = upbit.create_market_sell_order('BTC/KRW', round(btc_balance, 8)) 
                print("✅ 손절 매도 완료:", order) 
                send_telegram(f"🚨 손절 매도 완료! (손실률: {loss_percent:.2%})\n매수 가격: {bought_price:,.0f}원\n현재 가격: {current_price:,.0f}원\n수량: {round(btc_balance, 8)} BTC") 
                bought_price = 0 
                time.sleep(TRADE_COOLDOWN_SECONDS) 
                continue 

        if (btc_balance == 0 and 
            current_rsi <= RSI_BUY_THRESHOLD and 
            krw_balance >= MIN_ORDER_KRW and 
            current_ma_short > current_ma_long): 
            
            amount_to_buy_krw = krw_balance 
            if amount_to_buy_krw < MIN_ORDER_KRW: 
                print(f"⏳ 매수 가능 KRW가 최소 주문 금액({MIN_ORDER_KRW}원) 미만입니다. 대기 중...\n") 
            else: 
                amount_btc = amount_to_buy_krw / current_price 
                print("💡 매수 조건 만족 (RSI 35 이하 AND 골든 크로스)! 비트코인 KRW 전액 매수 실행") 
                order = upbit.create_market_buy_order('BTC/KRW', round(amount_btc, 8)) 
                print("✅ 매수 완료:", order) 
                send_telegram(f"💰 KRW 전액 매수 완료 (RSI: {current_rsi:.2f}, 골든 크로스)\n가격: {current_price:,.0f}원\n수량: {round(amount_btc, 8)} BTC\n매수 금액: {amount_to_buy_krw:,.0f}원") 
                bought_price = current_price 
                time.sleep(TRADE_COOLDOWN_SECONDS) 

        elif btc_balance > 0 and current_rsi >= RSI_SELL_THRESHOLD: 
            print("📈 매도 조건 만족 (RSI 55 이상)! 비트코인 전량 매도 실행") # 메시지도 55로 변경
            order = upbit.create_market_sell_order('BTC/KRW', round(btc_balance, 8)) 
            print("✅ 매도 완료:", order) 
            send_telegram(f"📤 전량 매도 완료 (RSI: {current_rsi:.2f})\n가격: {current_price:,.0f}원\n수량: {round(btc_balance, 8)} BTC") 
            bought_price = 0 
            time.sleep(TRADE_COOLDOWN_SECONDS) 

        else: 
            print("⏳ 조건 미충족: 대기 중...\n") 

    except ccxt.NetworkError as e: 
        print(f"❌ 네트워크 오류 발생: {e}") 
        send_telegram(f"❌ 네트워크 오류: {str(e)}") 
        time.sleep(10) 
    except ccxt.ExchangeError as e: 
        print(f"❌ 거래소 오류 발생: {e}") 
        send_telegram(f"❌ 거래소 오류: {str(e)}") 
        time.sleep(10) 
    except Exception as e: 
        print(f"❌ 예상치 못한 오류 발생: {e}") 
        send_telegram(f"❌ 예상치 못한 오류: {str(e)}") 
        time.sleep(10) 

    time.sleep(60)