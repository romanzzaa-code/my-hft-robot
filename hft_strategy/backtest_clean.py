# hft_strategy/backtest_clean.py
import sys
import os
import argparse
import logging
import numpy as np
from numba import njit
from dataclasses import dataclass

sys.path.append(os.getcwd())

from hftbacktest import (
    BacktestAsset, 
    HashMapMarketDepthBacktest, 
    GTX, LIMIT,
    Recorder
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CLEAN_TEST")

@njit
def wall_bounce_logic(hbt, recorder):
    # --- КОНСТАНТЫ (Вместо конфига, чтобы не ломать JIT) ---
    asset_no = 0
    tick_size = 0.01
    lot_size = 0.1
    order_qty = 1.0 
    
    # Состояние
    order_id_counter = 1
    active_buy_order_id = 0
    steps = 0
    
    # ---------------------------------------------------
    # ГЛАВНЫЙ ЦИКЛ (Как в debug_backtest)
    # ---------------------------------------------------
    while hbt.elapse(100_000_000) == 0:
        steps += 1
        
        # 1. Очистка
        hbt.clear_inactive_orders(asset_no)
        
        # 2. Данные
        depth = hbt.depth(asset_no)
        best_bid = depth.best_bid
        best_ask = depth.best_ask
        position = hbt.position(asset_no)
        
        # Если стакан пуст - пропускаем, но пишем (чтобы видеть пустоту)
        if np.isnan(best_bid) or np.isnan(best_ask):
            recorder.record(hbt)
            continue

        # 3. ЛОГИКА ВХОДА
        if position == 0 and active_buy_order_id == 0:
            # Вход по лучшей цене
            price = round(best_bid, 2)
            
            # Уникальный ID
            new_id = order_id_counter
            order_id_counter += 1
            
            hbt.submit_buy_order(asset_no, new_id, price, order_qty, GTX, LIMIT, False)
            active_buy_order_id = new_id

        # 4. ЛОГИКА ВЫХОДА
        elif position > 0:
            active_buy_order_id = 0
            
            # TP +0.5%
            tp_price = round(best_ask * 1.005, 2)
            
            new_id = order_id_counter
            order_id_counter += 1
            
            hbt.submit_sell_order(asset_no, new_id, tp_price, position, GTX, LIMIT, False)
        
        # Синхронизация
        if active_buy_order_id > 0:
            if active_buy_order_id not in hbt.orders(asset_no):
                active_buy_order_id = 0

        # ЗАПИСЬ
        recorder.record(hbt)

    return steps

def run(symbol: str, input_file: str):
    logger.info(f"🚀 Starting CLEAN backtest for {symbol}")
    
    if not os.path.exists(input_file):
        logger.error(f"❌ Input file not found: {input_file}")
        return

    # --- SETUP КАК В DEBUG_BACKTEST (Ничего лишнего) ---
    asset = (
        BacktestAsset()
        .data([input_file]) 
        .linear_asset(1.0) 
        .constant_order_latency(10_000_000, 10_000_000) 
    )
    
    logger.info("🔧 Engine Init...")
    hbt = HashMapMarketDepthBacktest([asset])
    
    # Буфер побольше
    recorder = Recorder(1, 20_000_000)
    
    logger.info("▶️ Running Loop...")
    try:
        steps = wall_bounce_logic(hbt, recorder.recorder)
        logger.info(f"🛑 Finished. Steps: {steps}")
        logger.info(f"⏱️ Last Timestamp: {hbt.current_timestamp}")
    except Exception as e:
        logger.error(f"❌ Crash: {e}")
        return

    if steps > 0:
        out_file = f"stats_{symbol.lower()}.npz"
        logger.info(f"💾 Saving stats to {out_file}...")
        recorder.to_npz(out_file)
        logger.info("✅ DONE.")
    else:
        logger.error("❌ ZERO STEPS. Engine rejected data again.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, default="SOLUSDT")
    args = parser.parse_args()
    
    # Файл должен быть тот самый v2, который вы экспортировали
    input_f = f"data/{args.symbol}_v2.npz"
    run(args.symbol, input_f)