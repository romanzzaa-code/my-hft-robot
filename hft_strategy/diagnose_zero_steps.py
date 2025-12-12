# hft_strategy/diagnose_zero_steps.py
import numpy as np
import logging
import sys
import os
# [FIX] Убираем numba
# from numba import njit, objmode
from hftbacktest import HashMapMarketDepthBacktest, BacktestAsset

logging.basicConfig(level=logging.INFO, format="%(message)s")

# [FIX] Убираем декоратор @njit - запускаем как обычный Python
def test_engine(hbt):
    print(f"   [PYTHON] Engine started. Initial TS: {hbt.current_timestamp}")

    # Тест 1: Микро-шаг (1 микросекунда)
    # Это эмуляция того, что делал debug_backtest (который работал)
    res1 = hbt.elapse(1_000)
    print(f"👉 Step 1 (1us): Result Code = {res1}")
    
    if res1 == 0:
        print(f"   ✅ Success! TS: {hbt.current_timestamp}")
    else:
        print(f"   ❌ FAIL! Engine rejected start.")
        # Если не вышло, нет смысла продолжать
        return False

    # Тест 2: Макро-шаг (100 миллисекунд)
    # Это эмуляция backtest_main (который давал 0 шагов)
    res2 = hbt.elapse(100_000_000)
    print(f"👉 Step 2 (100ms): Result Code = {res2}")
    
    if res2 == 0:
        print(f"   ✅ Success! TS: {hbt.current_timestamp}")
    else:
        print(f"   ❌ FAIL! Engine stopped at Step 2.")

    return True

def run():
    f = "data/SOLUSDT_v2.npz"
    if not os.path.exists(f):
        print("❌ File not found")
        return

    print("📦 Loading data...")
    # Загружаем
    try:
        data = np.load(f)['data']
    except Exception as e:
        print(f"❌ Load Error: {e}")
        return

    print(f"✅ Data loaded: {len(data)} rows.")
    print(f"   First EV Flag: {data[0]['ev']}")
    print(f"   First TS:      {data[0]['local_ts']}")

    # Конфигурация
    asset = (
        BacktestAsset()
        .data([data])
        .linear_asset(1.0)
        .constant_order_latency(10_000_000, 10_000_000)
    )
    
    hbt = HashMapMarketDepthBacktest([asset])
    
    print("🚀 Running Diagnostics (Pure Python Mode)...")
    try:
        test_engine(hbt)
    except Exception as e:
        print(f"💥 CRASH: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run()