import ccxt
import pandas as pd
import ta
import datetime

# 1. Configuration
INITIAL_KRW = 1_000_000  # Starting capital (KRW)
KRW_TO_SPEND_PER_CYCLE = 100000  # Total KRW to spend for one full buy cycle (1st + 2nd)
RSI_PERIOD = 14
RSI_BUY_THRESHOLD_1ST = 35
RSI_BUY_THRESHOLD_2ND = 30
RSI_SELL_THRESHOLD = 55
TRADING_FEE_RATE = 0.0005 # Upbit market order fee (0.05%)

# 2. Upbit object (for historical data)
# No API key needed for backtesting as no real trades are made
upbit = ccxt.upbit()

# 3. Backtest function
def run_backtest():
    print("🚀 Backtest Started: Jan 1, 2022 ~ Dec 31, 2023")
    print(f"Initial Capital: {INITIAL_KRW} KRW")
    print(f"Buy Amount per Cycle: {KRW_TO_SPEND_PER_CYCLE} KRW")
    print(f"RSI Buy 1st: {RSI_BUY_THRESHOLD_1ST}, RSI Buy 2nd: {RSI_BUY_THRESHOLD_2ND}, RSI Sell: {RSI_SELL_THRESHOLD}, Fee: {TRADING_FEE_RATE * 100}%\n")

    current_krw_balance = INITIAL_KRW
    current_btc_balance = 0
    buy_step = 0 # 0: no buy, 1: 1st buy done, 2: 2nd buy done

    monthly_asset_history = [] # Stores (month, total_asset)

    # Load historical data (2 years of 1-hour candles)
    print("📈 Loading Bitcoin 1-hour candle data...")
    since_timestamp = int(datetime.datetime(2022, 1, 1, 0, 0, 0).timestamp() * 1000)
    # Approximately 2 * 365 * 24 = 17520 hours. Setting limit to 20000 for safety.
    ohlcv = upbit.fetch_ohlcv('BTC/KRW', '1h', since=since_timestamp, limit=20000)
    print(f"📊 Loaded {len(ohlcv)} 1-hour candles.\n")

    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df['close'] = pd.to_numeric(df['close'])
    df = df.set_index('timestamp')

    # Calculate RSI
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=RSI_PERIOD).rsi()
    df = df.dropna() # Remove rows with NaN (due to RSI calculation)

    last_month = None
    # Record initial asset for the first month
    if not df.empty:
        first_month = df.index[0].strftime('%Y-%m')
        monthly_asset_history.append((first_month, INITIAL_KRW))
        last_month = first_month

    # Backtest Loop
    for index, row in df.iterrows():
        current_time = index
        current_price = row['close']
        current_rsi = row['rsi']

        # Monthly asset tracking
        current_month = current_time.strftime('%Y-%m')
        if current_month != last_month and last_month is not None:
            end_of_month_asset = current_krw_balance + (current_btc_balance * current_price)
            monthly_asset_history.append((current_month, end_of_month_asset))
        last_month = current_month

        # --- Buy Logic ---
        if current_btc_balance == 0 and buy_step == 0 and current_rsi <= RSI_BUY_THRESHOLD_1ST and current_krw_balance >= KRW_TO_SPEND_PER_CYCLE / 2:
            # 1st Buy (50% of total buy amount)
            amount_krw = KRW_TO_SPEND_PER_CYCLE / 2
            amount_btc = amount_krw / current_price
            fee = amount_krw * TRADING_FEE_RATE
            
            current_krw_balance -= (amount_krw + fee)
            current_btc_balance += amount_btc
            buy_step = 1

        elif buy_step == 1 and current_rsi <= RSI_BUY_THRESHOLD_2ND and current_krw_balance >= KRW_TO_SPEND_PER_CYCLE / 2:
            # 2nd Buy (remaining 50%)
            amount_krw = KRW_TO_SPEND_PER_CYCLE / 2
            amount_btc = amount_krw / current_price
            fee = amount_krw * TRADING_FEE_RATE
            
            current_krw_balance -= (amount_krw + fee)
            current_btc_balance += amount_btc
            buy_step = 2

        # --- Sell Logic ---
        elif current_rsi >= RSI_SELL_THRESHOLD and current_btc_balance > 0:
            # Sell all BTC
            sell_value_krw = current_btc_balance * current_price
            fee = sell_value_krw * TRADING_FEE_RATE
            
            current_krw_balance += (sell_value_krw - fee)
            current_btc_balance = 0
            buy_step = 0 # Reset buy step after selling

    # Final asset recording for the last month
    final_asset_value = current_krw_balance + (current_btc_balance * df['close'].iloc[-1] if not df.empty else 0)
    if not monthly_asset_history or monthly_asset_history[-1][0] != df.index[-1].strftime('%Y-%m'):
        monthly_asset_history.append((df.index[-1].strftime('%Y-%m') if not df.empty else datetime.datetime.now().strftime('%Y-%m'), final_asset_value))

    # --- Calculate Returns ---
    calculated_monthly_returns = {}
    for i in range(len(monthly_asset_history)):
        month, end_asset = monthly_asset_history[i]
        if i == 0: # First month's return is calculated from initial capital
            start_asset = INITIAL_KRW
        else: # Subsequent months' returns are calculated from previous month's end asset
            start_asset = monthly_asset_history[i-1][1]
        
        if start_asset != 0:
            monthly_return = ((end_asset - start_asset) / start_asset) * 100
            calculated_monthly_returns[month] = monthly_return
        else:
            calculated_monthly_returns[month] = 0 # Handle division by zero

    # --- Print Results ---
    print("\n" + "="*50)
    print("📊 Backtest Results")
    print("="*50)

    print("\n--- Monthly Returns ---")
    total_return_product = 1
    sorted_monthly_returns = sorted(calculated_monthly_returns.items())
    
    for month, returns in sorted_monthly_returns:
        print(f"{month}: {returns:.2f}%")
        total_return_product *= (1 + returns / 100)

    cumulative_return = (total_return_product - 1) * 100
    
    if len(calculated_monthly_returns) > 0:
        average_monthly_return = sum(calculated_monthly_returns.values()) / len(calculated_monthly_returns)
    else:
        average_monthly_return = 0

    print("\n" + "-"*30)
    print(f"Average Monthly Return: {average_monthly_return:.2f}%")
    print(f"Final Cumulative Return: {cumulative_return:.2f}%")
    print(f"Starting Capital: {INITIAL_KRW:.0f} KRW")
    print(f"Final Capital: {final_asset_value:.0f} KRW")
    print("-" * 30)
    print("="*50)

# Run Backtest
if __name__ == "__main__":
    run_backtest()