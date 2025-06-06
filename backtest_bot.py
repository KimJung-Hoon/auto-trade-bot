import ccxt
import pandas as pd
from datetime import datetime, timedelta
import time

# ───────────────────────────────
# 1. 업비트 객체 생성 (백테스팅용, 실제 키 필요 없음)
# ───────────────────────────────
upbit = ccxt.upbit()

# ───────────────────────────────
# 2. 기술 지표 계산 함수 (MACD, RSI, ADX) - 기존 코드와 동일
# ───────────────────────────────
def compute_indicators(df):
    if len(df) < 60:
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

    # 주의: 백테스팅에서는 loop를 돌면서 계산해도 괜찮지만, 실제 봇에서는 성능 이슈가 있을 수 있음.
    # ADX 계산은 충분한 데이터가 필요하며, 누락된 값이 있을 수 있으므로 fillna(0) 처리
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
# 3. 백테스팅 설정
# ───────────────────────────────
SYMBOL = 'BTC/KRW'
TIMEFRAME = '4h'
MAX_OHLCV_LIMIT = 200 # ccxt fetch_ohlcv의 최대 limit

# 백테스팅 시작 및 종료 날짜 설정 (약 3년 전부터 현재까지)
end_date = datetime.now()
start_date = end_date - timedelta(days=3 * 365) # 약 3년

# 백테스팅 초기 자본금
INITIAL_KRW_BALANCE = 10_000_000 # 1,000만원 시작

# 매매 설정 (실제 봇 코드와 동일하게 적용)
PERCENTAGE_OF_KRW_BALANCE_TO_INVEST = 0.20 # 가용 원화 잔고의 20%를 매매에 사용 (총 투자금)
MIN_TRADE_KRW = 5000 # 업비트 최소 주문 금액
TRADING_FEE_RATE = 0.0005 # 업비트 거래 수수료 0.05% (매수/매도 각각)

# 리스크 관리 설정
TRAILING_STOP_PERCENTAGE = 0.03 # 3% 하락 시 트레일링 스톱 발동
INITIAL_STOP_LOSS_PERCENTAGE = 0.05 # 5% 하락 시 하드 손절
BUY_DIP_PERCENTAGE = 0.01 # 1% 하락 시 2차 분할 매수

# ───────────────────────────────
# 4. 데이터 로드 함수
# ───────────────────────────────
def fetch_all_ohlcv(symbol, timeframe, since, limit):
    all_ohlcv = []
    current_timestamp = since
    while True:
        print(f"데이터 로드 중: {datetime.fromtimestamp(current_timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')} 부터...")
        ohlcv = upbit.fetch_ohlcv(symbol, timeframe, current_timestamp, limit)
        if not ohlcv:
            break
        all_ohlcv.extend(ohlcv)
        # 다음 fetch를 위해 마지막 데이터의 타임스탬프를 기준으로 설정
        current_timestamp = ohlcv[-1][0] + 1 # 마지막 봉의 다음 밀리초부터

        # 무한 루프 방지: 현재 시간까지 데이터를 모두 가져왔으면 중단
        if datetime.fromtimestamp(current_timestamp / 1000) > datetime.now():
            break
        # API 요청 제한을 준수하기 위한 대기
        time.sleep(0.1) # Upbit API는 초당 10회 요청 제한

    # 중복 제거 및 시간 순서 정렬
    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df.drop_duplicates(subset=['timestamp'], inplace=True)
    df = df.sort_values('timestamp').reset_index(drop=True)
    return df

# ───────────────────────────────
# 5. 백테스팅 메인 함수
# ───────────────────────────────
def run_backtest():
    print(f"📊 백테스팅 시작: {start_date.strftime('%Y-%m-%d')} 부터 {end_date.strftime('%Y-%m-%d')} 까지")
    print(f"초기 자본금: {INITIAL_KRW_BALANCE:,.0f} KRW")

    # 모든 과거 데이터 로드
    ohlcv_df = fetch_all_ohlcv(SYMBOL, TIMEFRAME, int(start_date.timestamp() * 1000), MAX_OHLCV_LIMIT)
    
    if ohlcv_df.empty:
        print("❌ 백테스팅을 위한 OHLCV 데이터가 없습니다. 날짜 범위 또는 API 연결을 확인하세요.")
        return

    ohlcv_df['datetime'] = pd.to_datetime(ohlcv_df['timestamp'], unit='ms')
    ohlcv_df = ohlcv_df.set_index('datetime')
    ohlcv_df.index = ohlcv_df.index.tz_localize('UTC').tz_convert('Asia/Seoul')

    # 백테스팅 시뮬레이션 변수 초기화
    current_krw_balance = INITIAL_KRW_BALANCE
    current_btc_balance = 0
    last_buy_price = 0
    highest_price_after_buy = 0
    buy_step = 0 # 0: 대기, 1: 1차 매수 완료, 2: 2차 매수 완료

    trade_history = [] # 거래 내역 저장
    monthly_returns = {} # 월별 수익률 저장

    # 지표 계산에 필요한 최소 데이터 포인트
    min_required_data_for_indicators = max(60, 26 + 9, 14 * 2) 

    # 백테스팅 루프
    # df.iterrows() 대신 range(len(df))를 사용하는 것이 인덱스 기반 접근에 유리
    for i in range(len(ohlcv_df)):
        # 데이터가 충분하지 않으면 지표 계산 스킵
        if i < min_required_data_for_indicators + 1: # +1은 이전 봉 지표 비교를 위함
            continue

        # 현재 봉과 이전 봉 데이터 가져오기
        current_candle = ohlcv_df.iloc[i]
        prev_candle = ohlcv_df.iloc[i-1] # 이전 봉

        # 지표 계산 (매 루프마다 전체 DF를 계산하는 것은 비효율적이나, 백테스팅 편의상 이렇게 구현)
        # 실제로는 새로운 봉이 추가될 때마다 필요한 지표만 업데이트하는 것이 성능상 유리
        temp_df = ohlcv_df.iloc[:i+1].copy() # 현재까지의 데이터만 복사하여 지표 계산
        computed_df = compute_indicators(temp_df)

        # 지표 계산에 필요한 데이터가 부족하면 스킵
        if len(computed_df) < min_required_data_for_indicators + 1:
            continue

        current_price = current_candle['close']
        
        # 지표 값 로드
        ema_20 = computed_df['EMA_20'].iloc[-1]
        ema_60 = computed_df['EMA_60'].iloc[-1]
        macd = computed_df['MACD'].iloc[-1]
        macd_signal = computed_df['MACD_Signal'].iloc[-1]
        macd_hist = computed_df['MACD_Hist'].iloc[-1]
        adx = computed_df['ADX'].iloc[-1]
        
        ema_20_prev = computed_df['EMA_20'].iloc[-2]
        ema_60_prev = computed_df['EMA_60'].iloc[-2]
        macd_prev = computed_df['MACD'].iloc[-2]
        macd_signal_prev = computed_df['MACD_Signal'].iloc[-2]

        current_datetime = current_candle.name # 봉의 datetime 인덱스

        # 🔔 현재 가용 원화 잔고에 따라 투자 금액 동적 설정
        # 0.05% 수수료를 감안하여 투자금의 99.9%만 BTC로 바꿀 수 있다고 가정
        total_investment_this_cycle_krw = current_krw_balance * PERCENTAGE_OF_KRW_BALANCE_TO_INVEST

        # ───────────────────────────────
        # ── 매수 조건 확인 ──
        # ───────────────────────────────
        if current_btc_balance == 0 and buy_step == 0:
            golden_cross = (ema_20_prev < ema_60_prev and ema_20 >= ema_60)
            macd_buy_signal = (macd_prev < macd_signal_prev and macd >= macd_signal and macd_hist > 0)
            adx_strong_trend = (adx >= 25)

            if golden_cross and macd_buy_signal and adx_strong_trend:
                amount_to_buy_krw = total_investment_this_cycle_krw * 0.5
                if amount_to_buy_krw < MIN_TRADE_KRW:
                    amount_to_buy_krw = MIN_TRADE_KRW 

                if current_krw_balance >= amount_to_buy_krw and amount_to_buy_krw >= MIN_TRADE_KRW:
                    # 매수 시뮬레이션
                    bought_btc_amount = (amount_to_buy_krw / current_price) * (1 - TRADING_FEE_RATE)
                    current_btc_balance += bought_btc_amount
                    current_krw_balance -= amount_to_buy_krw # 실제 지불 금액 (수수료 포함된 금액)
                    
                    last_buy_price = current_price
                    highest_price_after_buy = current_price
                    buy_step = 1
                    
                    trade_history.append({
                        'datetime': current_datetime,
                        'type': 'BUY_1ST',
                        'price': current_price,
                        'amount_btc': bought_btc_amount,
                        'investment_krw': amount_to_buy_krw,
                        'krw_balance': current_krw_balance,
                        'btc_balance': current_btc_balance,
                        'info': '1차 매수'
                    })

        # ───────────────────────────────
        # ── 분할 매수 조건 확인 (1차 매수 후) ──
        # ───────────────────────────────
        elif buy_step == 1:
            if current_price <= last_buy_price * (1 - BUY_DIP_PERCENTAGE):
                amount_to_buy_krw = total_investment_this_cycle_krw * 0.5
                if amount_to_buy_krw < MIN_TRADE_KRW:
                    amount_to_buy_krw = MIN_TRADE_KRW 

                if current_krw_balance >= amount_to_buy_krw and amount_to_buy_krw >= MIN_TRADE_KRW:
                    # 매수 시뮬레이션
                    bought_btc_amount = (amount_to_buy_krw / current_price) * (1 - TRADING_FEE_RATE)
                    current_btc_balance += bought_btc_amount
                    current_krw_balance -= amount_to_buy_krw # 실제 지불 금액
                    
                    # 2차 매수 시 평균 단가 업데이트
                    # 정확한 평균 단가를 계산하려면 기존 BTC 수량과 매수 가격을 알아야 함
                    # 백테스팅에서는 편의상 current_price를 last_buy_price로 갱신 (실제 봇에서는 avg_buy_price 활용)
                    last_buy_price = current_price # 2차 매수 시점의 가격으로 업데이트
                    highest_price_after_buy = current_price # 2차 매수 후 최고가 초기화
                    buy_step = 2

                    trade_history.append({
                        'datetime': current_datetime,
                        'type': 'BUY_2ND',
                        'price': current_price,
                        'amount_btc': bought_btc_amount,
                        'investment_krw': amount_to_buy_krw,
                        'krw_balance': current_krw_balance,
                        'btc_balance': current_btc_balance,
                        'info': '2차 분할 매수'
                    })

        # ───────────────────────────────
        # ── 매도 조건 확인 (보유 중일 때) ──
        # ───────────────────────────────
        elif current_btc_balance > 0:
            if current_price > highest_price_after_buy:
                highest_price_after_buy = current_price
            
            # 트레일링 스톱 발동 조건
            trailing_stop_activated = False
            if last_buy_price > 0 and current_price > last_buy_price: # 수익 구간에서만 트레일링 스톱 적용
                trailing_stop_price = highest_price_after_buy * (1 - TRAILING_STOP_PERCENTAGE)
                if current_price <= trailing_stop_price:
                    trailing_stop_activated = True

            # 하드 손절 발동 조건
            hard_stop_loss_activated = False
            if last_buy_price > 0 and current_price <= last_buy_price * (1 - INITIAL_STOP_LOSS_PERCENTAGE):
                hard_stop_loss_activated = True
            
            # 추세 반전 매도 조건
            dead_cross = (ema_20_prev >= ema_60_prev and ema_20 < ema_60)
            macd_sell_signal = (macd_prev >= macd_signal_prev and macd < macd_signal and macd_hist < 0)
            trend_reversal_activated = (dead_cross and macd_sell_signal)

            # 매도 실행
            if trailing_stop_activated or hard_stop_loss_activated or trend_reversal_activated:
                # 매도 시뮬레이션
                sold_krw_amount = current_btc_balance * current_price * (1 - TRADING_FEE_RATE) # 수수료 제하고 들어오는 원화
                current_krw_balance += sold_krw_amount
                
                trade_type = ""
                if trailing_stop_activated:
                    trade_type = "SELL_TRAILING_STOP"
                    info_msg = "트레일링 스톱 매도"
                elif hard_stop_loss_activated:
                    trade_type = "SELL_STOP_LOSS"
                    info_msg = "하드 손절 매도"
                elif trend_reversal_activated:
                    trade_type = "SELL_TREND_REVERSAL"
                    info_msg = "추세 반전 매도"

                trade_history.append({
                    'datetime': current_datetime,
                    'type': trade_type,
                    'price': current_price,
                    'amount_btc': current_btc_balance, # 전량 매도
                    'received_krw': sold_krw_amount,
                    'krw_balance': current_krw_balance,
                    'btc_balance': 0, # 전량 매도했으므로 0
                    'info': info_msg
                })

                current_btc_balance = 0
                last_buy_price = 0
                highest_price_after_buy = 0
                buy_step = 0 # 매도 후 초기화
        
        # 월별 수익률 계산을 위한 현재 월 추적
        current_month_year = current_datetime.strftime('%Y-%m')
        
        # 해당 월의 시작 잔고가 아직 기록되지 않았다면 기록
        if current_month_year not in monthly_returns:
            monthly_returns[current_month_year] = {
                'start_krw': current_krw_balance,
                'start_btc_krw_value': current_btc_balance * current_price,
                'end_krw': current_krw_balance,
                'end_btc_krw_value': current_btc_balance * current_price
            }
        
        # 매번 봉이 진행될 때마다 현재 잔고를 업데이트 (마지막 봉에서 최종적으로 사용)
        monthly_returns[current_month_year]['end_krw'] = current_krw_balance
        monthly_returns[current_month_year]['end_btc_krw_value'] = current_btc_balance * current_price

    # ───────────────────────────────
    # 6. 결과 출력
    # ───────────────────────────────
    print("\n--- 백테스팅 결과 ---")
    final_krw_balance = current_krw_balance + (current_btc_balance * current_price) # 마지막 남은 BTC가 있다면 KRW로 환산

    total_return_krw = final_krw_balance - INITIAL_KRW_BALANCE
    total_return_percentage = (total_return_krw / INITIAL_KRW_BALANCE) * 100 if INITIAL_KRW_BALANCE > 0 else 0

    print(f"최종 자본금: {final_krw_balance:,.0f} KRW")
    print(f"총 수익 (KRW): {total_return_krw:,.0f} KRW")
    print(f"총 수익률: {total_return_percentage:.2f} %")

    print("\n--- 월별 수익률 ---")
    # 월별 수익률 계산 및 출력
    monthly_summary = []
    sorted_months = sorted(monthly_returns.keys())

    for i, month_year in enumerate(sorted_months):
        data = monthly_returns[month_year]
        start_total = data['start_krw'] + data['start_btc_krw_value']
        end_total = data['end_krw'] + data['end_btc_krw_value']
        
        if i > 0: # 이전 달의 마지막 잔고를 이번 달의 시작 잔고로 가져옴 (연속성을 위함)
            prev_month_data = monthly_returns[sorted_months[i-1]]
            start_total = prev_month_data['end_krw'] + prev_month_data['end_btc_krw_value']
            # 실제로 월별 수익률을 계산하기 위해 해당 월의 시작 시점 자산으로 보정
            data['start_krw'] = start_total # 시작 자본을 실제 매달 시작 시점 기준으로 업데이트
            
        # 첫 달은 INITIAL_KRW_BALANCE를 시작 자본으로 사용
        if i == 0:
            start_total = INITIAL_KRW_BALANCE
        else:
            # 이전 달의 최종 자본이 이번 달의 시작 자본이 됨
            # 이 로직은 `monthly_returns` 딕셔너리 내에서 `start_krw`와 `end_krw`를 직접 수정하는 것보다
            # 매달 "가상의" 시작 자본을 계산하는 방식이 더 직관적일 수 있음
            # 여기서는 마지막 봉이 끝난 시점의 잔고를 해당 월의 'end' 잔고로 보고, 다음 월의 'start' 잔고로 이어받는 개념
            pass # 이미 루프 내에서 마지막 봉의 값이 업데이트되어있음

        # 월별 수익률 계산 (해당 월의 최종 잔고 / 해당 월의 시작 잔고 - 1)
        # 중요: 월별 수익률은 해당 월에 발생한 순 자산 변화를 기준으로 해야 합니다.
        # 즉, 해당 월의 시작 시점의 총 자산과 종료 시점의 총 자산을 비교해야 합니다.
        
        # 현재는 각 월의 마지막 봉에서 기록된 end_krw와 end_btc_krw_value를 사용하고 있습니다.
        # start_krw는 해당 월에 처음 진입했을 때의 KRW 잔고입니다.
        # 실제 월별 수익률 계산은 `current_krw_balance + current_btc_balance * current_price`로
        # 매 봉마다 현재 총 자산 가치를 계산하여 비교하는 것이 더 정확합니다.
        
        # 간략화된 월별 수익률 계산 (해당 월의 마지막 시점 총 자산 / 초기 자산)
        # 이 방식은 누적 수익률에 가까움.
        # 정확한 월별 수익률은 '해당 월의 (총 자산 증가분 / 월초 총 자산)'으로 계산해야 함.
        
        # 보다 정확한 월별 수익률 계산
        if i == 0:
            month_start_total = INITIAL_KRW_BALANCE
        else:
            prev_month_data = monthly_returns[sorted_months[i-1]]
            month_start_total = prev_month_data['end_krw'] + prev_month_data['end_btc_krw_value']
        
        month_end_total = data['end_krw'] + data['end_btc_krw_value']
        
        if month_start_total > 0:
            monthly_gain_percentage = ((month_end_total - month_start_total) / month_start_total) * 100
        else: # 시작 자본이 0인 경우 (극히 드물지만)
            monthly_gain_percentage = 0 if month_end_total == 0 else float('inf') # 자본 없는데 수익나면 무한대

        monthly_summary.append({
            'Month': month_year,
            'Start_Balance': month_start_total,
            'End_Balance': month_end_total,
            'Monthly_Return_Perc': monthly_gain_percentage
        })
        print(f"{month_year}: {monthly_gain_percentage:.2f} %")

    # 모든 거래 내역 출력 (선택 사항, 양이 많을 수 있음)
    # trade_df = pd.DataFrame(trade_history)
    # print("\n--- 전체 거래 내역 ---")
    # print(trade_df.to_string()) # 모든 열을 출력

    return {
        'final_krw_balance': final_krw_balance,
        'total_return_krw': total_return_krw,
        'total_return_percentage': total_return_percentage,
        'monthly_returns': monthly_summary,
        'trade_history': trade_history
    }

if __name__ == '__main__':
    results = run_backtest()
    print("\n백테스팅 완료.")