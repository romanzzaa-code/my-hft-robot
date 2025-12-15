# hft_strategy/visualize.py
import sys
import os
import numpy as np
import matplotlib.pyplot as plt
import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("VIZ")

def get_col_name(names, candidates):
    """Ищет первое совпадение из candidates в names"""
    for c in candidates:
        if c in names:
            return c
    return None

def visualize(symbol="SOLUSDT"):
    stats_file = f"data/stats_{symbol}.npz"
    
    if not os.path.exists(stats_file):
        logger.error(f"❌ File not found: {stats_file}")
        return

    logger.info(f"🎨 Visualizing {stats_file}...")
    
    try:
        data = np.load(stats_file)
        # Рекордер сохраняет данные по ключу '0' (ID ассета)
        if '0' not in data:
            logger.error(f"❌ Key '0' not found in NPZ. Keys: {list(data.keys())}")
            return
            
        asset_data = data['0']
        
        # === [FIX] ДИНАМИЧЕСКИЙ ПОИСК КОЛОНОК ===
        if not asset_data.dtype.names:
            logger.error("❌ Data is not structured (raw array). Cannot visualize safely.")
            return
            
        names = asset_data.dtype.names
        logger.info(f"📋 Found columns: {names}")
        
        # Ищем колонки по возможным именам
        col_ts = get_col_name(names, ['timestamp', 'ts', 'time'])
        col_mid = get_col_name(names, ['mid', 'price', 'px', 'last'])
        col_bal = get_col_name(names, ['balance', 'equity', 'bal'])
        col_pos = get_col_name(names, ['position', 'pos'])
        col_fee = get_col_name(names, ['fee', 'cost'])

        if not (col_ts and col_mid and col_bal and col_pos):
            logger.error(f"❌ Critical columns missing! We need TS, Price, Balance, Position.")
            return

        # Извлекаем данные
        ts = asset_data[col_ts]
        mid = asset_data[col_mid]
        balance = asset_data[col_bal]
        position = asset_data[col_pos]
        fee = asset_data[col_fee] if col_fee else np.zeros_like(balance)

        # Приводим время к часам
        t_start = ts[0]
        time_hours = (ts - t_start) / 1_000_000_000 / 3600
        
        # Equity Curve
        equity = balance + (position * mid) - fee
        
        # Поиск сделок (изменения позиции)
        trades_mask = np.diff(position, prepend=0) != 0
        trade_idxs = np.where(trades_mask)[0]
        
        logger.info(f"📊 Plotting {len(trade_idxs)} trades...")

        # --- PLOTTING ---
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
        
        # График 1: Цена и Сделки
        ax1.plot(time_hours, mid, label='Price', color='gray', alpha=0.5, linewidth=1)
        
        # Рисуем покупки и продажи
        for idx in trade_idxs:
            delta = position[idx] - position[idx-1]
            price = mid[idx]
            if delta > 0: # Buy
                ax1.scatter(time_hours[idx], price, c='g', marker='^', s=30, zorder=5)
            else: # Sell
                ax1.scatter(time_hours[idx], price, c='r', marker='v', s=30, zorder=5)

        ax1.set_title(f"{symbol} - Price & Trades")
        ax1.set_ylabel("Price")
        ax1.grid(True, alpha=0.3)

        # График 2: Эквити и Позиция
        color = 'tab:blue'
        ax2.set_xlabel('Time (Hours)')
        ax2.set_ylabel('Equity', color=color)
        ax2.plot(time_hours, equity, color=color, linewidth=2, label='Equity')
        ax2.tick_params(axis='y', labelcolor=color)
        ax2.grid(True, alpha=0.3)

        # Вторая ось для позиции
        ax3 = ax2.twinx()  
        color = 'tab:orange'
        ax3.set_ylabel('Position', color=color)
        ax3.plot(time_hours, position, color=color, alpha=0.3, linestyle='--', label='Position')
        ax3.tick_params(axis='y', labelcolor=color)

        plt.suptitle(f"Backtest Analysis: {symbol}", fontsize=14)
        plt.tight_layout()
        
        output_img = f"data/chart_{symbol}.png"
        plt.savefig(output_img)
        logger.info(f"✅ Chart saved to {output_img}")
        
        # Показываем график (если есть GUI)
        try:
            plt.show()
        except:
            pass

    except Exception as e:
        logger.error(f"💥 Visualization crashed: {e}", exc_info=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="SOLUSDT")
    args = parser.parse_args()
    visualize(args.symbol)