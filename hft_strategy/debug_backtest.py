# hft_strategy/debug_backtest.py
import sys
import os
import argparse
import numpy as np
import logging
import time
from numba import njit, objmode
from hftbacktest import HashMapMarketDepthBacktest, BacktestAsset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DEBUGGER")

@njit
def simple_strategy(hbt):
    # Чтобы увидеть, что мы вошли в функцию
    with objmode():
        print("   [JIT] Strategy execution started!", flush=True)

    steps = 0
    # Делаем шаг в 1 микросекунду (очень маленький), чтобы проверить старт
    while hbt.elapse(1_000) == 0: 
        steps += 1
        
        # Логируем каждый 1000-й шаг (это быстро)
        if steps % 1000 == 0:
            ts = hbt.current_timestamp
            with objmode():
                print("   [SIM] Running... Step:", steps, "TS:", ts, flush=True)
                
        # Если прошли 5000 шагов - выходим (тест успешен)
        if steps >= 5000:
            with objmode():
                print("   [SIM] Limit reached. Exiting loop.", flush=True)
            break
            
    return True

def run_debug(symbol: str, input_file: str):
    logger.info(f"🕵️ DEBUGGING {symbol}...")
    
    if not os.path.exists(input_file):
        logger.error(f"❌ File not found: {input_file}")
        sys.exit(1)

    # 1. ЯВНАЯ ЗАГРУЗКА
    logger.info("📦 Loading .npz manually...")
    try:
        t0 = time.time()
        # Загружаем
        full_data = np.load(input_file)['data']
        logger.info(f"✅ Loaded {len(full_data)} rows in {time.time()-t0:.2f}s")
    except Exception as e:
        logger.error(f"❌ Load Failed: {e}")
        sys.exit(1)

    # 2. СРЕЗ ДАННЫХ (SLICE)
    # Берем только первые 100,000 строк. Этого достаточно для проверки движка.
    SLICE_SIZE = 100_000
    if len(full_data) > SLICE_SIZE:
        logger.warning(f"✂️ SLICING data: using first {SLICE_SIZE} rows out of {len(full_data)} for speed test.")
        data_chunk = full_data[:SLICE_SIZE]
    else:
        data_chunk = full_data
        
    logger.info(f"📊 Chunk shape: {data_chunk.shape}")

    # 3. ИНИЦИАЛИЗАЦИЯ АССЕТА (Передаем массив, а не файл)
    # В v2 .data() принимает список массивов
    asset = (
        BacktestAsset()
        .data([data_chunk]) 
        .linear_asset(1.0)
        .constant_order_latency(10_000_000, 10_000_000)
    )
    
    try:
        logger.info("🔧 Initializing HashMapMarketDepthBacktest...")
        hbt = HashMapMarketDepthBacktest([asset])
        
        logger.info("🚀 Starting Strategy (Calling JIT)...")
        t0 = time.time()
        
        success = simple_strategy(hbt)
        
        if success:
            logger.info(f"🎉 SUCCESS! Engine ran for 5000 steps. Time taken: {time.time()-t0:.2f}s")
        else:
            logger.error("❌ FAILED. Engine returned False.")
            
    except Exception as e:
        logger.error(f"🛑 ENGINE CRASH: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, required=True)
    parser.add_argument("--input", type=str, default=None)
    args = parser.parse_args()

    if args.input is None:
        args.input = f"data/{args.symbol}_v2.npz"

    run_debug(args.symbol, args.input)

if __name__ == "__main__":
    main()