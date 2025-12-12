# hft_strategy/find_breaking_point.py
import numpy as np
import logging
import os
import gc
from hftbacktest import HashMapMarketDepthBacktest, BacktestAsset

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("STRESS_TEST")

def test_size(data_slice, size_name):
    print(f"   Testing size: {size_name} rows...", end=" ")
    
    # Принудительная чистка памяти перед тестом
    gc.collect()
    
    # Создаем contiguous копию для теста
    slice_contiguous = np.ascontiguousarray(data_slice)
    
    asset = (
        BacktestAsset()
        .data([slice_contiguous]) 
        .linear_asset(1.0) 
        .constant_order_latency(0, 0)
    )
    
    try:
        hbt = HashMapMarketDepthBacktest([asset])
        # Пробуем сделать 1 шаг
        if hbt.elapse(1) == 0:
            print("✅ OK")
            return True
        else:
            print("❌ REJECTED (elapse code != 0)")
            return False
    except Exception as e:
        print(f"💥 CRASH: {e}")
        return False

def run():
    f = "data/SOLUSDT_clean.npz" 
    if not os.path.exists(f):
        f = "data/SOLUSDT_v2.npz"
    
    print(f"📦 Loading {f}...")
    data = np.load(f)['data']
    total_rows = len(data)
    print(f"   Total rows: {total_rows}")

    # СТЕПЕНИ НАГРУЗКИ
    checkpoints = [
        100_000,      # Мы знаем, что это работает
        1_000_000,    # 1 млн
        3_000_000,    # 3 млн
        6_000_000,    # Половина
        9_000_000,
        total_rows    # Весь файл
    ]

    print("\n🚀 STARTING STRESS TEST")
    print("="*30)

    for limit in checkpoints:
        if limit > total_rows:
            limit = total_rows
            
        success = test_size(data[:limit], f"{limit}")
        
        if not success:
            print("\n💀 DIED at size:", limit)
            print("   Conclusion: The issue is DATA CORRUPTION inside the file (or Memory Limit).")
            print("   Action: We need to inspect rows around this limit.")
            return

    print("\n🎉 ALL PASSED? Then the issue is definitely Memory Alignment or weird JIT interaction in main script.")

if __name__ == "__main__":
    run()