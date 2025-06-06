import ccxt
import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

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
# 4. 기술 지표 계산 함수 (MACD, RSI, ADX)
# ───────────────────────────────
def compute_indicators(df):
    if len(df) < 60: # 최소 60기간 EMA 계산을 위함, ADX는 더 필요
        return df

    df['EMA_20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['EMA_60'] = df['close'].ewm(span=60, adjust=False).mean()

    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

    df['H_L'] = df['high'] - df['low']
    df['H_prevC'] = abs(df['high'] - df['close'].shift(1))
    df['L_prevC'] = abs(df['low'] - df['close'].shift(1))
    df['TR'] = df[['H_L', 'H_prevC', 'L_prevC']].max(axis=1)

    df['up_move'] = df['high'] - df['high'].shift(1)
    df['down_move'] = df['low'].shift(1) - df['low']

    df['PlusDM'] = 0.0
    df['MinusDM'] = 0.0

    for i in range(1, len(df)):
        if df['up_move'].iloc[i] > df['down_move'].iloc[i] and df['up_move'].iloc[i] > 0:
            df.loc[df.index[i], 'PlusDM'] = df['up_move'].iloc[i]
        elif df['down_move'].iloc[i] > df['up_move'].iloc[i] and df['down_move'].iloc[i] > 0:
            df.loc[df.index[i], 'MinusDM'] = df['down_move'].iloc[i]

    df['ATR'] = df['TR'].ewm(span=14, adjust=False).mean()

    df['PlusDI'] = (df['PlusDM'].ewm(span=14, adjust=False).mean() / df['ATR']) * 100
    df['MinusDI'] = (df['MinusDM'].ewm(span=14, adjust=False).mean() / df['ATR']) * 100

    df['DX'] = (abs(df['PlusDI'] - df['MinusDI']) / (df['PlusDI'] + df['MinusDI'])).fillna(0) * 100
    df['ADX'] = df['DX'].ewm(span=14, adjust=False).mean()

    return df

# ───────────────────────────────
# 5. 전역 변수 및 초기 설정
# ───────────────────────────────
SYMBOL = 'BTC/KRW'
TIMEFRAME = '4h' # 4시간봉 활용
MAX_OHLCV_LIMIT = 200 # ccxt fetch_ohlcv의 최대 limit

# 🔔🔔🔔 변경된 부분 🔔🔔🔔
# 계좌 잔고 기반 투자 비율 설정
PERCENTAGE_OF_KRW_BALANCE_TO_INVEST = 0.20 # 가용 원화 잔고의 20%를 매매에 사용 (총 투자금)
# 🔔🔔🔔 이전 TOTAL_INVESTMENT_PER_TRADE_KRW 상수는 제거됨 🔔🔔🔔

MIN_TRADE_KRW = 5000 # 업비트 최소 주문 금액
TRADING_FEE_RATE = 0.0005 # 업비트 거래 수수료 0.05% (매수/매도 각각)

# 리스크 관리 설정
TRAILING_STOP_PERCENTAGE = 0.03 # 3% 하락 시 트레일링 스톱 발동
INITIAL_STOP_LOSS_PERCENTAGE = 0.05 # 5% 하락 시 하드 손절
BUY_DIP_PERCENTAGE = 0.01 # 1% 하락 시 2차 분할 매수

# 봇 상태 변수
current_btc_balance = 0
current_krw_balance = 0
last_buy_price = 0 # 마지막 매수 시점의 가격 (분할매수 시 평균 단가)
highest_price_after_buy = 0 # 매수 후 최고가 (트레일링 스톱용)
buy_step = 0 # 0: 대기, 1: 1차 매수 완료, 2: 2차 매수 완료

print(f"🚀 자동 매수·매도 봇 시작! {TIMEFRAME}봉 기반 추세 추종 전략\n")
send_telegram(f"🤖 자동매매 봇 시작됨 ({TIMEFRAME}봉 기반, 추세 추종 전략)")

# ───────────────────────────────
# 6. 메인 반복 감시 루프
# ───────────────────────────────
while True:
    try:
        # ── 1. 잔고 업데이트 ──
        balances = upbit.fetch_balance()
        current_krw_balance = balances['total'].get('KRW', 0)
        current_btc_balance = balances['total'].get('BTC', 0)
        
        # 🔔🔔🔔 변경된 부분 🔔🔔🔔
        # 현재 가용 원화 잔고에 따라 투자 금액 동적 설정
        total_investment_this_cycle_krw = current_krw_balance * PERCENTAGE_OF_KRW_BALANCE_TO_INVEST
        # 🔔🔔🔔 이전 TOTAL_INVESTMENT_PER_TRADE_KRW 변수 사용 대신 이 변수 사용 🔔🔔🔔


        # ── 2. OHLCV 데이터 및 지표 계산 ──
        ohlcv = upbit.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=MAX_OHLCV_LIMIT)
        
        if not ohlcv: 
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ OHLCV 데이터를 불러오지 못했습니다. API 제한 또는 네트워크 문제 확인. 대기 중...")
            send_telegram("❌ OHLCV 데이터 로드 실패. API 제한 또는 네트워크 문제.")
            time.sleep(300)
            continue 

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.set_index('datetime')
        df.index = df.index.tz_localize('UTC').tz_convert('Asia/Seoul') 

        df = compute_indicators(df)
        
        min_required_data = max(60, 26 + 9, 14 * 2) 
        if len(df) < min_required_data:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ⏳ 데이터 부족 ({len(df)}개), 최소 {min_required_data}개 필요. 대기 중...")
            time.sleep(60)
            continue 

        if len(df) < 2: # 지표 비교를 위한 이전 봉 데이터 확인
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ⏳ 지표 비교를 위한 데이터 부족 ({len(df)}개). 대기 중...")
            time.sleep(60)
            continue

        current_price = df['close'].iloc[-1]
        ema_20 = df['EMA_20'].iloc[-1]
        ema_60 = df['EMA_60'].iloc[-1]
        macd = df['MACD'].iloc[-1]
        macd_signal = df['MACD_Signal'].iloc[-1]
        macd_hist = df['MACD_Hist'].iloc[-1]
        adx = df['ADX'].iloc[-1]
        
        ema_20_prev = df['EMA_20'].iloc[-2]
        ema_60_prev = df['EMA_60'].iloc[-2]
        macd_prev = df['MACD'].iloc[-2]
        macd_signal_prev = df['MACD_Signal'].iloc[-2]


        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{now_str}] BTC 가격: {current_price:,.0f}원 | 20EMA: {ema_20:,.0f} | 60EMA: {ema_60:,.0f} | MACD Hist: {macd_hist:.4f} | ADX: {adx:.2f} | 보유 BTC: {current_btc_balance:.6f} | 보유 KRW: {current_krw_balance:,.0f} | 매수단계: {buy_step} | 금회 투자예정: {total_investment_this_cycle_krw:,.0f} KRW")

        # ───────────────────────────────
        # ── 3. 매수 조건 확인 ──
        # ───────────────────────────────
        if current_btc_balance == 0 and buy_step == 0:
            golden_cross = (ema_20_prev < ema_60_prev and ema_20 >= ema_60)
            macd_buy_signal = (macd_prev < macd_signal_prev and macd >= macd_signal and macd_hist > 0)
            adx_strong_trend = (adx >= 25)

            if golden_cross and macd_buy_signal and adx_strong_trend:
                # 1차 매수 금액 계산: 동적으로 설정된 total_investment_this_cycle_krw의 50%
                amount_to_buy_krw = total_investment_this_cycle_krw * 0.5
                
                # 최소 주문 금액 확인 및 조정
                if amount_to_buy_krw < MIN_TRADE_KRW:
                    amount_to_buy_krw = MIN_TRADE_KRW 
                
                # 원화 잔고가 매수 예정 금액보다 충분하고, 최소 주문 금액 이상일 때만 매수
                if current_krw_balance >= amount_to_buy_krw and amount_to_buy_krw >= MIN_TRADE_KRW:
                    amount_btc = (amount_to_buy_krw / current_price) / (1 + TRADING_FEE_RATE) # 수수료는 매수금액에 포함

                    print(f"💡 1차 매수 조건 만족! (골든크로스, MACD 상승, ADX 추세 확인) {amount_to_buy_krw:,.0f} KRW 매수 시도")
                    order = upbit.create_market_buy_order(SYMBOL, round(amount_btc, 8))
                    
                    if order and order['status'] == 'closed': 
                        print("✅ 1차 매수 완료:", order)
                        send_telegram(f"💰 1차 매수 완료!\n가격: {current_price:,.0f}원\n수량: {round(amount_btc, 8)} BTC\n총 투자: {order['cost']:.0f} KRW")
                        
                        last_buy_price = current_price 
                        highest_price_after_buy = current_price 
                        buy_step = 1 
                        time.sleep(5)
                    else:
                        print("❌ 1차 매수 실패 또는 미체결.")
                        send_telegram("❌ 1차 매수 실패 또는 미체결!")
                else:
                    print(f"⚠️ 1차 매수 대기: 잔고 부족({current_krw_balance:,.0f} KRW) 또는 최소 주문 금액 미달 (매수 예정: {amount_to_buy_krw:,.0f} KRW)")

        # ───────────────────────────────
        # ── 4. 분할 매수 조건 확인 (1차 매수 후) ──
        # ───────────────────────────────
        elif buy_step == 1: 
            if current_price <= last_buy_price * (1 - BUY_DIP_PERCENTAGE):
                # 2차 매수 금액 계산: 동적으로 설정된 total_investment_this_cycle_krw의 나머지 50%
                amount_to_buy_krw = total_investment_this_cycle_krw * 0.5 
                
                if amount_to_buy_krw < MIN_TRADE_KRW:
                    amount_to_buy_krw = MIN_TRADE_KRW 

                if current_krw_balance >= amount_to_buy_krw and amount_to_buy_krw >= MIN_TRADE_KRW:
                    amount_btc = (amount_to_buy_krw / current_price) / (1 + TRADING_FEE_RATE)

                    print(f"💡 2차 분할 매수 조건 만족! (1차 매수 후 {BUY_DIP_PERCENTAGE*100}% 하락) {amount_to_buy_krw:,.0f} KRW 매수 시도")
                    order = upbit.create_market_buy_order(SYMBOL, round(amount_btc, 8))
                    
                    if order and order['status'] == 'closed':
                        print("✅ 2차 분할 매수 완료:", order)
                        send_telegram(f"💰 2차 분할 매수 완료!\n가격: {current_price:,.0f}원\n수량: {round(amount_btc, 8)} BTC\n총 투자: {order['cost']:.0f} KRW")
                        
                        highest_price_after_buy = current_price 
                        buy_step = 2 
                        time.sleep(5)
                    else:
                        print("❌ 2차 분할 매수 실패 또는 미체결.")
                        send_telegram("❌ 2차 분할 매수 실패 또는 미체결!")
                else:
                    print(f"⚠️ 2차 분할 매수 대기: 잔고 부족({current_krw_balance:,.0f} KRW) 또는 최소 주문 금액 미달 (매수 예정: {amount_to_buy_krw:,.0f} KRW)")

        # ───────────────────────────────
        # ── 5. 매도 조건 확인 (보유 중일 때) ──
        # ───────────────────────────────
        elif current_btc_balance > 0: 
            if current_price > highest_price_after_buy:
                highest_price_after_buy = current_price
            
            if last_buy_price > 0 and current_price > last_buy_price:
                trailing_stop_price = highest_price_after_buy * (1 - TRAILING_STOP_PERCENTAGE)

                if current_price <= trailing_stop_price:
                    print(f"💡 트레일링 스톱 발동! (최고가 {highest_price_after_buy:,.0f}원 대비 {TRAILING_STOP_PERCENTAGE*100}% 하락) 전량 매도 시도")
                    order = upbit.create_market_sell_order(SYMBOL, round(current_btc_balance, 8))
                    
                    if order and order['status'] == 'closed':
                        print("✅ 트레일링 스톱 매도 완료:", order)
                        send_telegram(f"📤 트레일링 스톱 매도 완료!\n가격: {current_price:,.0f}원\n수량: {round(current_btc_balance, 8)} BTC")
                        current_btc_balance = 0 
                        last_buy_price = 0 
                        highest_price_after_buy = 0 
                        buy_step = 0 
                        time.sleep(5)
                    else:
                        print("❌ 트레일링 스톱 매도 실패 또는 미체결.")
                        send_telegram("❌ 트레일링 스톱 매도 실패 또는 미체결!")

            elif last_buy_price > 0 and current_price <= last_buy_price * (1 - INITIAL_STOP_LOSS_PERCENTAGE):
                print(f"🚨 하드 손절 발동! (매수 단가 {last_buy_price:,.0f}원 대비 {INITIAL_STOP_LOSS_PERCENTAGE*100}% 하락) 전량 매도 시도")
                order = upbit.create_market_sell_order(SYMBOL, round(current_btc_balance, 8))
                
                if order and order['status'] == 'closed':
                    print("✅ 하드 손절 매도 완료:", order)
                    send_telegram(f"🚨 하드 손절 매도 완료!\n가격: {current_price:,.0f}원\n수량: {round(current_btc_balance, 8)} BTC")
                    current_btc_balance = 0
                    last_buy_price = 0
                    highest_price_after_buy = 0
                    buy_step = 0
                    time.sleep(5)
                else:
                    print("❌ 하드 손절 매도 실패 또는 미체결.")
                    send_telegram("❌ 하드 손절 매도 실패 또는 미체결!")
            
            dead_cross = (ema_20_prev >= ema_60_prev and ema_20 < ema_60)
            macd_sell_signal = (macd_prev >= macd_signal_prev and macd < macd_signal and macd_hist < 0)

            if dead_cross and macd_sell_signal:
                print("📈 매도 조건 만족! (데드크로스, MACD 하락) 전량 매도 시도")
                order = upbit.create_market_sell_order(SYMBOL, round(current_btc_balance, 8))
                
                if order and order['status'] == 'closed':
                    print("✅ 매도 완료:", order)
                    send_telegram(f"📤 매도 완료!\n가격: {current_price:,.0f}원\n수량: {round(current_btc_balance, 8)} BTC")
                    current_btc_balance = 0
                    last_buy_price = 0
                    highest_price_after_buy = 0
                    buy_step = 0
                    time.sleep(5)
                else:
                    print("❌ 매도 실패 또는 미체결.")
                    send_telegram("❌ 매도 실패 또는 미체결!")
            else:
                print("⏳ 조건 미충족: 대기 중...\n")

        else: 
            print("⏳ 조건 미충족: 대기 중...\n")

    except ccxt.NetworkError as e:
        print(f"🌐 네트워크 오류 발생: {e}")
        send_telegram(f"🌐 네트워크 오류 발생: {e}")
        time.sleep(300) 
    except ccxt.ExchangeError as e:
        print(f"거래소 오류 발생: {e}")
        send_telegram(f"거래소 오류 발생: {e}")
        time.sleep(300) 
    except Exception as e:
        print(f"❌ 예상치 못한 오류 발생: {e}")
        send_telegram(f"❌ 예상치 못한 오류 발생:\n{str(e)}")
        time.sleep(300) 

    time.sleep(900)