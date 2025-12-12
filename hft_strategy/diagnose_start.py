# hft_strategy/diagnose_start.py
import numpy as np
import time
from numba import njit, objmode
from hftbacktest import BacktestAsset, HashMapMarketDepthBacktest

FILE = "data/parts/part_000.npz"

@njit
def try_start(hbt):
    # Попытка 1: Микрошаг
    with objmode():
        print("   👉 Attempting elapse(1)...")
    
    code = hbt.elapse(1)
    
    with objmode():
        print(f"   👉 Result Code: {code}")
        print(f"   👉 Current Time: {hbt.current_timestamp}")
    
    return code

def run():
    print(f"🚑 DIAGNOSING STARTUP on {FILE}")
    data = np.load(FILE)['data']
    
    # Настраиваем ассет
    asset = (
        BacktestAsset()
        .data([data])
        .linear_asset(1.0)
        .constant_order_latency(0, 0) # Нулевая задержка для теста
    )
    
    hbt = HashMapMarketDepthBacktest([asset])
    
    print("🚀 Running JIT Diagnostic...")
    try:
        try_start(hbt)
    except Exception as e:
        print(f"💥 CRASH: {e}")

if __name__ == "__main__":
    run()