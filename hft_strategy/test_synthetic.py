# hft_strategy/test_synthetic.py
import numpy as np
import logging
from numba import njit
from hftbacktest import (
    BacktestAsset, 
    HashMapMarketDepthBacktest, 
    Recorder,
    # ИМПОРТИРУЕМ ФЛАГИ ИЗ БИБЛИОТЕКИ (V2)
    EXCH_EVENT, LOCAL_EVENT, 
    DEPTH_EVENT, TRADE_EVENT, DEPTH_CLEAR_EVENT, DEPTH_SNAPSHOT_EVENT,
    BUY_EVENT, SELL_EVENT
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("SYNTH")

def run_synthetic_test():
    logger.info("🧪 Generating synthetic data (V2 Correct Flags)...")

    # Золотой стандарт структуры V2
    dtype = [
        ('ev', 'uint64'),
        ('exch_ts', 'i8'),
        ('local_ts', 'i8'),
        ('px', 'f8'),
        ('qty', 'f8'),
        ('order_id', 'uint64'),
        ('ival', 'i8'),
        ('fval', 'f8')
    ]

    start_ts = 1735689600 * 1_000_000_000 # 2025-01-01
    
    rows = []
    
    # --- 1. SNAPSHOT ---
    # Важно: В V2 сторона (Bid/Ask) задается флагом BUY_EVENT/SELL_EVENT, а не знаком qty!
    
    # Event 1: Clear Book
    # Флаги: Это событие биржи + локальное событие + очистка стакана
    ev_clear = EXCH_EVENT | LOCAL_EVENT | DEPTH_CLEAR_EVENT
    rows.append((ev_clear, start_ts, start_ts, 0, 0, 0, 0, 0.0))
    
    # Event 2: Bid @ 100
    # Флаги: Exchange + Local + Depth + BUY (Сторона Бид)
    ev_bid = EXCH_EVENT | LOCAL_EVENT | DEPTH_EVENT | BUY_EVENT
    rows.append((ev_bid, start_ts, start_ts, 100.0, 1.0, 0, 0, 0.0))
    
    # Event 3: Ask @ 101
    # Флаги: Exchange + Local + Depth + SELL (Сторона Аск)
    ev_ask = EXCH_EVENT | LOCAL_EVENT | DEPTH_EVENT | SELL_EVENT
    rows.append((ev_ask, start_ts, start_ts, 101.0, 1.0, 0, 0, 0.0))

    # --- 2. TRADE ---
    # Event 4: Trade Sell (кто-то продал в бид)
    ev_trade = EXCH_EVENT | LOCAL_EVENT | TRADE_EVENT | SELL_EVENT
    rows.append((ev_trade, start_ts + 100_000_000, start_ts + 100_000_000, 100.0, 0.1, 0, 0, 0.0))
    
    data = np.array(rows, dtype=dtype)
    logger.info(f"✅ Generated {len(data)} events.")

    # --- RUN ENGINE ---
    asset = (
        BacktestAsset()
        .data(data)
        .linear_asset(1.0)
        .constant_order_latency(1_000_000, 1_000_000)
    )

    logger.info("🔧 Init Engine...")
    hbt = HashMapMarketDepthBacktest([asset])
    
    logger.info("▶️ Running Loop...")
    steps = run_strategy(hbt)
    
    if steps > 0:
        logger.info(f"🎉 SUCCESS! Synthetic test passed. Steps: {steps}")
    else:
        logger.error("❌ FAIL. Still rejected.")

@njit
def run_strategy(hbt):
    steps = 0
    # Шагаем 10 секунд
    while hbt.elapse(1_000_000_000) == 0:
        steps += 1
        if steps == 1:
            d = hbt.depth(0)
            print("   [JIT] Step 1. Bid:", d.best_bid, "Ask:", d.best_ask)
    return steps

if __name__ == "__main__":
    run_synthetic_test()