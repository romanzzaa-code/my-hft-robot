# hft_strategy/analyze.py
import sys
import os
import numpy as np
import argparse
import logging
from hftbacktest.stats import LinearAssetRecord

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ANALYSIS")

def analyze(symbol="SOLUSDT"):
    stats_file = f"data/stats_{symbol}.npz"
    
    if not os.path.exists(stats_file):
        logger.error(f"❌ Stats file not found: {stats_file}")
        return

    logger.info(f"📊 Analyzing {stats_file}...")
    
    try:
        data = np.load(stats_file)
        if '0' not in data:
            logger.error(f"❌ Key '0' not found. Keys: {list(data.keys())}")
            return
            
        # Структура asset_data: [timestamp, mid, balance, position, fee, ...]
        asset_data = data['0']
        
        # --- 1. СЫРАЯ ДИАГНОСТИКА (RAW DIAGNOSTICS) ---
        # Позиция - это обычно 4-й столбец (индекс 3), но лучше по именам если rec array
        # В hftbacktest recorder пишет плоский массив float64, без имен полей по умолчанию в v1,
        # но в v2 Recorder пишет структурированный массив?
        # Давайте проверим тип.
        
        if asset_data.dtype.names:
            # Если это структурированный массив
            positions = asset_data['position']
            equity = asset_data['equity'] if 'equity' in asset_data.dtype.names else asset_data['balance']
        else:
            # Если это сырой массив (v1 style recorder), обычно:
            # 0:timestamp, 1:mid, 2:balance, 3:position, 4:fee, 5:trade_num, 6:trade_price, 7:trade_qty
            positions = asset_data[:, 3]
            equity = asset_data[:, 2] # Balance approx equity if pos=0

        # Считаем количество изменений позиции (сделки)
        pos_changes = np.diff(positions)
        num_trades = np.count_nonzero(pos_changes)
        
        max_pos = np.max(np.abs(positions))
        
        print("\n" + "="*40)
        print(f"🔍 DEBUG REPORT: {symbol}")
        print("="*40)
        print(f"Total Ticks Recorded: {len(asset_data)}")
        print(f"Total Trades Detected: {num_trades}")
        print(f"Max Position Size:     {max_pos}")
        
        if num_trades == 0:
            print("\n❌ CONCLUSION: Strategy NEVER traded.")
            print("   Possible reasons:")
            print("   1. 'wall_threshold' is too high.")
            print("   2. Data has no Bids/Asks (prices=0).")
            print("   3. Logic condition `if is_bid_wall` never met.")
            return

        # --- 2. СТАНДАРТНЫЙ ОТЧЕТ ---
        print("\n" + "="*40)
        print(f"📈 FINANCIAL REPORT")
        print("="*40)
        stats = LinearAssetRecord(asset_data).stats()
        stats.summary()
        
    except Exception as e:
        logger.error(f"💥 Analysis failed: {e}", exc_info=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="SOLUSDT")
    args = parser.parse_args()
    
    analyze(args.symbol)