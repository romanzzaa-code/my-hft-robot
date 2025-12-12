# hft_strategy/backtest.py
import numpy as np
import sys
import os
import argparse
import logging
from numba import njit, objmode

sys.path.append(os.getcwd())

from hftbacktest import (
    BacktestAsset, 
    HashMapMarketDepthBacktest, 
    GTX, LIMIT,
    Recorder
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("BACKTEST")

@njit
def wall_bounce_strategy(hbt, recorder):
    asset_no = 0
    tick_size = 0.01 
    order_qty = 1.0 
    
    # --- Инициализация переменных (ОБЯЗАТЕЛЬНО для Numba) ---
    steps = 0
    active_buy_order_id = 0
    order_id_counter = 1
    
    skipped_steps = 0
    valid_data_started = False
    
    # Визуальный маркер старта
    # ... (код до цикла без изменений) ...
    # Визуальный маркер старта
    with objmode():
        print("DEBUG: Entering Main Loop...", flush=True)

    # Основной цикл
    while hbt.elapse(100_000_000) == 0:
        steps += 1
        
        # 1. Получаем данные
        depth = hbt.depth(asset_no)
        current_bid = depth.best_bid
        current_ask = depth.best_ask

        # --- ДИАГНОСТИКА: ПЕЧАТАЕМ ВСЁ ПЕРВЫЕ 50 ШАГОВ ---
        # Мы хотим видеть, что происходит, даже если цена 0.0
        if steps <= 50:
            ts = hbt.current_timestamp
            with objmode():
                # Печатаем и Бид, и Аск, чтобы понять, однобокий ли рынок
                print("Step:", steps, "| BID:", current_bid, "| ASK:", current_ask, "| Time:", ts, flush=True)

        # 2. ФИЛЬТР ДАННЫХ (Оставляем как было, но с пониманием проблемы)
        if np.isnan(current_bid) or current_bid < 1.0:
            skipped_steps += 1
            if skipped_steps % 1000 == 0:
                with objmode():
                    print("   ... skipping invalid data. Total skipped:", skipped_steps, flush=True)
            recorder.record(hbt)
            continue
        
        # ... (дальше твой код: if not valid_data_started, и торговля) ...
        if not valid_data_started:
            valid_data_started = True
            with objmode():
                print("🚀 VALID MARKET DATA FOUND! First Bid:", current_bid, "at Step:", steps, flush=True)

        # Рабочий лог (раз в 5000 шагов)
        if steps % 5000 == 0:
            ts = hbt.current_timestamp
            pos = hbt.position(asset_no)
            with objmode():
                print("   -> Working. Step:", steps, "| Bid:", current_bid, "| Pos:", pos, flush=True)

        hbt.clear_inactive_orders(asset_no)
        # ... и так далее
        
        position = hbt.position(asset_no)
        
        # --- ТОРГОВАЯ ЛОГИКА ---
        
        # ВХОД (Покупка)
        if position == 0 and active_buy_order_id == 0:
            # Ставим лимитку чуть ниже рынка (ловля отскока)
            price = round(current_bid - tick_size, 2)
            new_id = order_id_counter
            
            hbt.submit_buy_order(asset_no, new_id, price, order_qty, GTX, LIMIT, False)
            active_buy_order_id = new_id
            order_id_counter += 1

        # ВЫХОД (Продажа)
        elif position > 0:
            # Снимаем активный ордер на покупку, если он остался
            active_buy_order_id = 0
            
            # Тейк-профит +0.5%
            tp_price = round(current_ask * 1.005, 2)
            new_id = order_id_counter
            
            hbt.submit_sell_order(asset_no, new_id, tp_price, position, GTX, LIMIT, False)
            order_id_counter += 1
        
        # Сброс ID ордера, если он исполнился или исчез
        if active_buy_order_id > 0 and active_buy_order_id not in hbt.orders(asset_no):
            active_buy_order_id = 0

        # Пишем состояние в рекордер
        recorder.record(hbt)

    return steps

def run_backtest(symbol: str, input_file: str, output_stats: str):
    logger.info(f"🚀 Preparing DIAGNOSTIC backtest for {symbol}...")
    
    if not os.path.exists(input_file):
        logger.error(f"❌ Input file not found: {input_file}")
        return

    logger.info(f"📂 Loading data: {input_file}")
    
    # Настройка ассета
    asset = (
        BacktestAsset()
        .data([input_file]) 
        .linear_asset(1.0) 
        .constant_order_latency(10_000_000, 10_000_000) # 10ms задержка
    )
    
    logger.info("🔧 Init Engine...")
    hbt = HashMapMarketDepthBacktest([asset])
    
    # Рекордер будет сжимать данные, чтобы не переполнять память (snapshot раз в 20мс)
    recorder = Recorder(1, 20_000_000)
    
    logger.info("▶️ Running Strategy...")
    
    try:
        steps = wall_bounce_strategy(hbt, recorder.recorder)
        logger.info(f"✅ FINISHED. Total steps: {steps}")
    except Exception as e:
        logger.error(f"❌ Crash inside strategy: {e}")
        # Для отладки можно распечатать traceback, но logger.error уже неплохо
        return

    if steps == 0:
        logger.error("❌ ERROR: Steps = 0. Engine rejected data or loop didn't start.")
        return

    logger.info(f"🏁 Saving stats to {output_stats}...")
    recorder.to_npz(output_stats)
    logger.info("✅ Done.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, default="SOLUSDT")
    parser.add_argument("--input", type=str, default=None)
    parser.add_argument("--output", type=str, default="stats_sol.npz")
    args = parser.parse_args()
    
    if args.input is None:
        args.input = f"data/{args.symbol}_v2.npz"
        
    run_backtest(args.symbol, args.input, args.output)