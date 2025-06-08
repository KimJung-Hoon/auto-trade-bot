import ccxt
import os
import time
import requests
import pandas as pd
import ta
from dotenv import load_dotenv

# ───────────────────────────────
# 1. 환경변수 로드 및 검증
# ───────────────────────────────
load_dotenv()
api_key          = os.getenv('UPBIT_API_KEY')
secret_key       = os.getenv('UPBIT_SECRET_KEY')
telegram_token   = os.getenv('TELEGRAM_TOKEN')
telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')

if not all([api_key, secret_key, telegram_token, telegram_chat_id]):
    raise RuntimeError("환경변수(API 키, 시크릿 키, Telegram 토큰/채팅 ID)가 모두 설정되어야 합니다.")

# ───────────────────────────────
# 2. CCXT 업비트 객체 생성
# ───────────────────────────────
upbit = ccxt.upbit({
    'apiKey': api_key,
    'secret': secret_key,
})
upbit.load_markets()

# ───────────────────────────────
# 3. Telegram 전송 함수
# ───────────────────────────────
def send_telegram(message: str):
    try:
        url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
        payload = {"chat_id": telegram_chat_id, "text": message}
        requests.post(url, data=payload)
    except Exception as e:
        print("❌ 텔레그램 전송 실패:", e)

# ───────────────────────────────
# 4. 전략 파라미터
# ───────────────────────────────
MA_SHORT        = 20      # 단기 이동평균 기간 (일)
MA_LONG         = 50      # 장기 이동평균 기간 (일)
MDI_WINDOW      = 14      # MDI 계산 기간 (일)
MDI_BUY_THRESH  = 15      # 매수 시 MDI 기준치
MDI_SELL_THRESH = 27      # 매도 시 MDI 기준치
STOP_LOSS_PCT   = 0.06    # 손절 비율 (6%)
MIN_KRW_TRADE   = 5000    # 업비트 최소 거래 금액 (KRW)
TRADE_FEE_RATE  = 0.0005  # 업비트 시장가 수수료율 (0.05%)

symbol          = 'BTC/KRW'
timeframe       = '1d'    # 일봉
ohlcv_limit     = 100     # 과거 100일치 데이터 확보

last_buy_price = None

print("🚀 자동매매 봇 시작! (일봉, 24시간 주기)")
print(f"    • MA{MA_SHORT} vs MA{MA_LONG} 골든/데드 크로스")
print(f"    • MDI ≤{MDI_BUY_THRESH} → 매수, MDI ≥{MDI_SELL_THRESH} → 매도")
print(f"    • 손절: {int(STOP_LOSS_PCT*100)}% 손실 시")
print(f"    • 최소 거래 금액: {MIN_KRW_TRADE}원")
print(f"    • 거래 수수료율: {TRADE_FEE_RATE*100}%")
send_telegram("🤖 비트코인 자동매매 봇(일봉, 하루 1회) 시작되었습니다.")

# ───────────────────────────────
# 5. 메인 루프 (24시간마다 실행)
# ───────────────────────────────
while True:
    try:
        # 1) 일봉 데이터 조회
        ohlcv = upbit.fetch_ohlcv(symbol, timeframe=timeframe, limit=ohlcv_limit)
        df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','vol'])

        # 2) 지표 계산
        df['ma_short'] = df['close'].rolling(MA_SHORT).mean()
        df['ma_long']  = df['close'].rolling(MA_LONG).mean()
        adx = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=MDI_WINDOW)
        df['mdi'] = adx.adx_neg()
        df.dropna(inplace=True)

        prev = df.iloc[-2]
        curr = df.iloc[-1]

        # 3) 오늘 종가 및 잔고 조회
        today_close  = curr['close']
        today_str    = time.strftime('%Y-%m-%d')
        balances     = upbit.fetch_balance()
        krw_balance  = balances['total'].get('KRW', 0)
        btc_balance  = balances['total'].get('BTC', 0)

        print(f"[{today_str}] 종가: {today_close:.0f}원 | MA{MA_SHORT}:{curr['ma_short']:.0f} vs MA{MA_LONG}:{curr['ma_long']:.0f} | MDI:{curr['mdi']:.2f}")

        # 4) 손절 조건 (6% 손실)
        if last_buy_price and btc_balance > 0:
            if today_close <= last_buy_price * (1 - STOP_LOSS_PCT):
                print("⚠️ 손절 조건 충족! 전량 매도 실행")
                try:
                    order = upbit.create_market_sell_order(symbol, round(btc_balance, 8))
                    send_telegram(f"⚠️ 손절 매도 완료\n가격: {order['price']:.0f}원\n수량: {order['amount']:.8f} BTC\n체결액: {order['cost']:.0f}원")
                    last_buy_price = None
                except ccxt.NetworkError as e:
                    print(f"네트워크 오류 발생: {e}")
                    send_telegram(f"❌ 손절 매도 중 네트워크 오류 발생: {e}")
                except ccxt.ExchangeError as e:
                    print(f"거래소 오류 발생: {e}")
                    send_telegram(f"❌ 손절 매도 중 거래소 오류 발생: {e}")
                except Exception as e:
                    print(f"알 수 없는 오류 발생: {e}")
                    send_telegram(f"❌ 손절 매도 중 알 수 없는 오류 발생: {e}")


        # 5) 매수 조건: 골든 크로스 발생 중 & MDI ≤ 기준 & KRW 보유
        # 매수 시 수수료를 고려하여 매수 가능한 최대 KRW를 계산하고, 최소 주문 금액 확인
        eligible_krw_for_buy = krw_balance * (1 - TRADE_FEE_RATE)
        golden = ((prev['ma_short'] <= prev['ma_long'] and curr['ma_short'] > curr['ma_long'])
                  or (curr['ma_short'] > curr['ma_long']))

        if golden and curr['mdi'] <= MDI_BUY_THRESH and eligible_krw_for_buy >= MIN_KRW_TRADE:
            buy_amt_btc = eligible_krw_for_buy / today_close
            
            print(f"💡 매수 조건 충족! (매수 가능 KRW: {eligible_krw_for_buy:.0f}원)")
            try:
                order = upbit.create_market_buy_order(symbol, round(buy_amt_btc, 8))
                send_telegram(f"💰 매수 완료\n가격: {order['price']:.0f}원\n수량: {order['amount']:.8f} BTC\n체결액: {order['cost']:.0f}원")
                last_buy_price = order['price'] # 실제 체결된 가격을 last_buy_price로 저장
            except ccxt.NetworkError as e:
                print(f"네트워크 오류 발생: {e}")
                send_telegram(f"❌ 매수 중 네트워크 오류 발생: {e}")
            except ccxt.ExchangeError as e:
                print(f"거래소 오류 발생: {e}")
                send_telegram(f"❌ 매수 중 거래소 오류 발생: {e}")
            except Exception as e:
                print(f"알 수 없는 오류 발생: {e}")
                send_telegram(f"❌ 매수 중 알 수 없는 오류 발생: {e}")
                

        # 6) 매도 조건: 데드 크로스 발생 중 OR MDI ≥ 기준 & BTC 보유
        death = ((prev['ma_short'] >= prev['ma_long'] and curr['ma_short'] < curr['ma_long'])
                 or (curr['ma_short'] < curr['ma_long']))
        
        # 매도 시에는 BTC 잔고가 0보다 클 때만 실행
        if (death or curr['mdi'] >= MDI_SELL_THRESH) and btc_balance > 0:
            print("📈 매도 조건 충족! 전량 매도 실행")
            try:
                order = upbit.create_market_sell_order(symbol, round(btc_balance, 8))
                send_telegram(f"📤 매도 완료\n가격: {order['price']:.0f}원\n수량: {order['amount']:.8f} BTC\n체결액: {order['cost']:.0f}원")
                last_buy_price = None
            except ccxt.NetworkError as e:
                print(f"네트워크 오류 발생: {e}")
                send_telegram(f"❌ 매도 중 네트워크 오류 발생: {e}")
            except ccxt.ExchangeError as e:
                print(f"거래소 오류 발생: {e}")
                send_telegram(f"❌ 매도 중 거래소 오류 발생: {e}")
            except Exception as e:
                print(f"알 수 없는 오류 발생: {e}")
                send_telegram(f"❌ 매도 중 알 수 없는 오류 발생: {e}")

    except Exception as e:
        print("❌ 주요 루프 오류 발생:", e)
        send_telegram(f"❌ 자동매매 주요 루프 오류:\n{str(e)}")

    # 24시간 대기 (86400초)
    time.sleep(86400)