import ccxt
import os
import time
import requests
import pandas as pd
import ta
from dotenv import load_dotenv

# 1. 환경변수 로드 및 검증
load_dotenv()
api_key          = os.getenv('UPBIT_API_KEY')
secret_key       = os.getenv('UPBIT_SECRET_KEY')
telegram_token   = os.getenv('TELEGRAM_TOKEN')
telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')

if not all([api_key, secret_key, telegram_token, telegram_chat_id]):
    raise RuntimeError("❌ 모든 환경변수가 설정되어야 합니다.")

# 2. 업비트 객체 생성
upbit = ccxt.upbit({
    'apiKey': api_key,
    'secret': secret_key,
})
upbit.load_markets()

# 3. 텔레그램 전송 함수
def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
        requests.post(url, data={"chat_id": telegram_chat_id, "text": message})
    except Exception as e:
        print("❌ 텔레그램 전송 실패:", e)

# 4. 전략 파라미터
MA_SHORT = 20
MA_LONG = 50
ADX_WINDOW = 30
ADX_BUY_THRESH = 23
ADX_SELL_THRESH = 22
STOP_LOSS_PCT = 0.06
MIN_KRW_TRADE = 5000
TRADE_FEE_RATE = 0.0005
symbol = 'BTC/KRW'
timeframe = '1d'
ohlcv_limit = 100
last_buy_price = None

print("🚀 자동매매 봇 시작! (일봉)")
send_telegram("🤖 비트코인 자동매매 봇(ADX 기반, 일봉) 시작되었습니다.")

# 5. 메인 루프
while True:
    try:
        df = pd.DataFrame(
            upbit.fetch_ohlcv(symbol, timeframe=timeframe, limit=ohlcv_limit),
            columns=['ts', 'open', 'high', 'low', 'close', 'vol']
        )

        df['ma_short'] = df['close'].rolling(MA_SHORT).mean()
        df['ma_long'] = df['close'].rolling(MA_LONG).mean()
        adx = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=ADX_WINDOW)
        df['adx'] = adx.adx()
        df.dropna(inplace=True)

        prev, curr = df.iloc[-2], df.iloc[-1]
        today_close = curr['close']
        today_str = time.strftime('%Y-%m-%d')

        balances = upbit.fetch_balance()
        krw_balance = balances.get('total', {}).get('KRW', 0)
        btc_balance = balances.get('total', {}).get('BTC', 0)

        print(f"[{today_str}] 종가: {today_close:.0f}원 | ADX: {curr['adx']:.2f}")

        # ─────────────── 손절 조건 ───────────────
        if last_buy_price and btc_balance > 0:
            if today_close <= last_buy_price * (1 - STOP_LOSS_PCT):
                print("⚠️ 손절 조건 충족! 매도 실행")
                try:
                    order = upbit.create_market_sell_order(symbol, round(btc_balance, 8))
                    avg_price = order['cost'] / order['filled'] if order['filled'] > 0 else 0
                    send_telegram(f"⚠️ 손절 매도\n가격: {avg_price:.0f}원\n수량: {order['amount']} BTC")
                    last_buy_price = None
                except ccxt.NetworkError as e:
                    print("❌ 네트워크 오류:", e)
                    send_telegram(f"❌ 손절 중 네트워크 오류 발생:\n{e}")
                except ccxt.ExchangeError as e:
                    print("❌ 거래소 오류:", e)
                    send_telegram(f"❌ 손절 중 거래소 오류 발생:\n{e}")
                except Exception as e:
                    print("❌ 기타 오류:", e)
                    send_telegram(f"❌ 손절 중 알 수 없는 오류 발생:\n{e}")

        # ─────────────── 매수 조건 ───────────────
        golden = (prev['ma_short'] <= prev['ma_long'] and curr['ma_short'] > curr['ma_long']) or (curr['ma_short'] > curr['ma_long'])

        if golden and curr['adx'] > ADX_BUY_THRESH and krw_balance > MIN_KRW_TRADE:
            buy_amt = krw_balance * (1 - TRADE_FEE_RATE) / today_close
            try:
                order = upbit.create_market_buy_order(symbol, round(buy_amt, 8))
                avg_price = order['cost'] / order['filled'] if order['filled'] > 0 else 0
                send_telegram(f"💰 매수 완료\n가격: {avg_price:.0f}원\n수량: {order['amount']} BTC")
                last_buy_price = avg_price
            except ccxt.NetworkError as e:
                print("❌ 네트워크 오류:", e)
                send_telegram(f"❌ 매수 중 네트워크 오류 발생:\n{e}")
            except ccxt.ExchangeError as e:
                print("❌ 거래소 오류:", e)
                send_telegram(f"❌ 매수 중 거래소 오류 발생:\n{e}")
            except Exception as e:
                print("❌ 기타 오류:", e)
                send_telegram(f"❌ 매수 중 알 수 없는 오류 발생:\n{e}")

        # ─────────────── 매도 조건 ───────────────
        death = (prev['ma_short'] >= prev['ma_long'] and curr['ma_short'] < curr['ma_long']) or (curr['ma_short'] < curr['ma_long'])

        if (death or curr['adx'] < ADX_SELL_THRESH) and btc_balance > 0:
            try:
                order = upbit.create_market_sell_order(symbol, round(btc_balance, 8))
                avg_price = order['cost'] / order['filled'] if order['filled'] > 0 else 0
                send_telegram(f"📤 매도 완료\n가격: {avg_price:.0f}원\n수량: {order['amount']} BTC")
                last_buy_price = None
            except ccxt.NetworkError as e:
                print("❌ 네트워크 오류:", e)
                send_telegram(f"❌ 매도 중 네트워크 오류 발생:\n{e}")
            except ccxt.ExchangeError as e:
                print("❌ 거래소 오류:", e)
                send_telegram(f"❌ 매도 중 거래소 오류 발생:\n{e}")
            except Exception as e:
                print("❌ 기타 오류:", e)
                send_telegram(f"❌ 매도 중 알 수 없는 오류 발생:\n{e}")

    except Exception as e:
        print("❌ 주요 루프 오류 발생:", e)
        send_telegram(f"❌ 루프 오류 발생:\n{str(e)}")

    time.sleep(86400)  # 하루 1회 실행
