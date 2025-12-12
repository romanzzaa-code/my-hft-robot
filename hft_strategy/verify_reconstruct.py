# hft_strategy/verify_reconstruct.py
import numpy as np
import logging
from hftbacktest import HashMapMarketDepthBacktest, BacktestAsset

logging.basicConfig(level=logging.INFO, format="%(message)s")

def run():
    f = "data/SOLUSDT_reconstructed.npz"
    print(f"🧪 Verifying {f}...")
    
    try:
        data = np.load(f)['data']
    except Exception as e:
        print(f"❌ Could not load file: {e}")
        return

    # Берем кусочек
    chunk = data[:50000] # 50k rows
    
    asset = (
        BacktestAsset()
        .data([chunk])
        .linear_asset(1.0)
        .constant_order_latency(0, 0)
    )
    
    hbt = HashMapMarketDepthBacktest([asset])
    
    print("▶️ Attempting engine start...")
    if hbt.elapse(1) == 0:
        print("✅ SUCCESS! Engine accepted the reconstructed data.")
        print(f"   Current TS: {hbt.current_timestamp}")
    else:
        print("❌ FAILED. Engine rejected data.")

if __name__ == "__main__":
    run()