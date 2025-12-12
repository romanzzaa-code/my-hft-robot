# hft_strategy/debug_backtest.py
import sys
import os
import argparse
import numpy as np
import logging
from numba import njit
from hftbacktest import HashMapMarketDepthBacktest, BacktestAsset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DEBUGGER")

def check_data_integrity(file_path: str):
    if not os.path.exists(file_path):
        logger.error(f"❌ File not found: {file_path}")
        sys.exit(1)
    
    try:
        data = np.load(file_path)['data']
        logger.info(f"📦 File inspect: {len(data)} rows loaded.")
        
        # Проверка ключевых полей
        dtype = data.dtype
        names = dtype.names
        logger.info(f"🔍 Fields: {names}")
        
        required_fields = ['ev', 'exch_ts', 'local_ts', 'px', 'qty', 'order_id', 'ival', 'fval']
        for req in required_fields:
            if req not in names:
                logger.error(f"❌ Missing field: {req}")
                sys.exit(1)
                
        # Проверка типов
        if dtype['ev'] != np.uint64:
             logger.error(f"❌ 'ev' must be uint64, got {dtype['ev']}")
             sys.exit(1)
             
        if dtype['fval'] != np.float64:
             logger.error(f"❌ 'fval' must be float64, got {dtype['fval']}")
             sys.exit(1)

        return True
    except Exception as e:
        logger.error(f"❌ Error reading file: {e}")
        sys.exit(1)

@njit
def simple_strategy(hbt):
    # Пытаемся сделать хотя бы один шаг
    if hbt.elapse(100_000_000) != 0:
        return False
    while hbt.elapse(100_000_000) == 0: 
        pass
    return True

def run_debug(symbol: str, input_file: str):
    logger.info(f"🕵️ DEBUGGING {symbol}...")
    
    check_data_integrity(input_file)
    
    asset = (
        BacktestAsset()
        .data([input_file])
        .linear_asset(1.0)
        .constant_order_latency(10_000_000, 10_000_000)
    )
    
    try:
        hbt = HashMapMarketDepthBacktest([asset])
        logger.info("🚀 Starting Engine...")
        
        success = simple_strategy(hbt)
        
        if success or hbt.current_timestamp > 0:
            logger.info(f"✅ SUCCESS! Engine ran until ts={hbt.current_timestamp}")
        else:
            logger.error("❌ FAILED. Engine stopped immediately.")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"🛑 ENGINE CRASH: {e}")
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