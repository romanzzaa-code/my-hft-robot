# hft_strategy/backtest_bot.py
import sys
import os
import numpy as np
import logging
from hftbacktest import (
    HashMapMarketDepthBacktest, 
    BacktestAsset, 
    Recorder
)

# Импортируем стратегию и конфиги
# (убедись, что папки созданы и __init__.py на месте)
sys.path.append(os.getcwd())
from hft_strategy.strategies.wall_bounce import wall_bounce_strategy
from hft_strategy.domain.strategy_config import get_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("BACKTEST_BOT")

def run(symbol="SOLUSDT"):
    logger.info(f"🚀 Initializing Backtest for {symbol}...")
    
    # 1. Загрузка Данных
    # Файл, который мы только что экспортировали
    data_file = f"data/{symbol}_v2.npz"
    if not os.path.exists(data_file):
        logger.error(f"❌ Data file not found: {data_file}")
        logger.info("💡 Run: python hft_strategy/pipelines/export_data.py first!")
        return

    logger.info(f"📂 Loading {data_file}...")
    try:
        data = np.load(data_file)['data']
        logger.info(f"✅ Loaded {len(data)} events.")
    except Exception as e:
        logger.error(f"❌ Load failed: {e}")
        return

    # 2. Конфигурация
    # Получаем параметры инструмента (тик, лот) из нашего конфига
    try:
        cfg = get_config(symbol)
    except ValueError:
        logger.warning(f"⚠️ Config for {symbol} not found, using defaults.")
        # Фолбек
        class MockCfg: tick_size=0.01; lot_size=0.01; wall_ratio_threshold=100.0
        cfg = MockCfg()

    logger.info(f"🔧 Asset Config: Tick={cfg.tick_size}, Lot={cfg.lot_size}")

    # 3. Инициализация Движка
    asset = (
        BacktestAsset()
        .data([data])                 # Передаем список массивов (chunks)
        .linear_asset(1.0)            # Линейный контракт (USDT)
        .tick_size(cfg.tick_size)     # <--- ВАЖНО для HashMap
        .lot_size(cfg.lot_size)
        .constant_order_latency(10_000_000, 10_000_000) # 10ms задержка (Round-trip 20ms)
    )
    
    hbt = HashMapMarketDepthBacktest([asset])
    
    # Рекордер (пишет статистику в память, потом сохраняет)
    recorder = Recorder(1, 10_000_000) # Буфер на 10 млн записей
    
    # 4. Запуск Стратегии
    logger.info("▶️ Running WallBounce Strategy...")
    try:
        # Передаем параметры стратегии
        steps = wall_bounce_strategy(
            hbt, 
            recorder.recorder, 
            wall_threshold=cfg.wall_vol_threshold,
            tp_ticks=cfg.take_profit_ticks,
            sl_ticks=cfg.stop_loss_ticks
        )
        logger.info(f"🏁 Backtest Finished. Steps processed: {steps}")
        
    except Exception as e:
        logger.error(f"💥 Runtime Error: {e}", exc_info=True)
        return

    # 5. Сохранение результатов
    output_stats = f"data/stats_{symbol}.npz"
    logger.info(f"💾 Saving stats to {output_stats}...")
    recorder.to_npz(output_stats)
    
    # 6. Быстрый анализ (Smoke Test)
    # Если файл создался, можно запустить analyze_results.py
    logger.info("✅ Done. Now run: python hft_strategy/analyze.py")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="SOLUSDT")
    args = parser.parse_args()
    
    run(args.symbol)