# hft_strategy/batch_optimizer.py
import asyncio
import os
import sys
import numpy as np
import json
import logging
from datetime import datetime

# Path hack для импорта модулей
sys.path.append(os.getcwd())

from hft_strategy.config import TARGET_COINS
from hft_strategy.pipelines.export_data import export_data
from hft_strategy.optimization import StrategyOptimizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler("optimization_batch.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("BATCH_RUNNER")

RESULTS_FILE = "hft_strategy/domain/optimized_params.json"
DATA_DIR = "data"

async def ensure_data_exists(symbol: str, days: int = 7) -> str:
    """
    Проверяет наличие файла данных. Если его нет или он старый — экспортирует из БД.
    """
    file_path = os.path.join(DATA_DIR, f"{symbol}_v2.npz")
    
    if not os.path.exists(file_path):
        logger.info(f"📉 Data missing for {symbol}. Exporting last {days} days...")
        await export_data(symbol, file_path, days=days)
    else:
        logger.info(f"✅ Data found for {symbol}: {file_path}")
        
    return file_path

def save_results(new_result: dict):
    """
    Атомарное обновление JSON файла с параметрами.
    """
    data = {}
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, 'r') as f:
                data = json.load(f)
        except Exception:
            logger.warning("⚠️ Could not read existing results, creating new.")

    # Обновляем данные по конкретной монете
    symbol = new_result['symbol']
    data[symbol] = {
        "updated_at": datetime.now().isoformat(),
        "params": new_result['params'],
        "score": new_result['score']
    }

    with open(RESULTS_FILE, 'w') as f:
        json.dump(data, f, indent=4)
    logger.info(f"💾 Results saved to {RESULTS_FILE}")

async def process_coin(symbol: str):
    try:
        # 1. Pipeline: Ensure Data
        data_path = await ensure_data_exists(symbol)
        
        # 2. Load Data (Memory Intensive Operation)
        # Используем run_in_executor для блокирующих I/O операций с диском
        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(None, lambda: np.load(data_path)['data'])
        except Exception as e:
            logger.error(f"❌ Failed to load {data_path}: {e}")
            return

        if len(data) == 0:
            logger.warning(f"⚠️ Empty dataset for {symbol}. Skipping.")
            return

        # 3. Optimize (CPU Intensive)
        # Optuna запускаем синхронно в отдельном потоке/процессе, чтобы не блокировать Event Loop
        optimizer = StrategyOptimizer(symbol, data, n_trials=50)
        
        # В идеале здесь использовать ProcessPoolExecutor, так как Optuna грузит CPU
        best_result = await loop.run_in_executor(None, optimizer.run)
        
        # 4. Save
        save_results(best_result)
        
        # Clean up memory
        del data
        import gc
        gc.collect()

    except Exception as e:
        logger.error(f"💥 Failed processing {symbol}: {e}", exc_info=True)

async def main():
    logger.info("🚀 Starting Batch Optimization...")
    logger.info(f"📋 Targets: {TARGET_COINS}")
    
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)

    # Последовательная обработка (для экономии RAM). 
    # Если RAM много, можно использовать asyncio.gather с Semaphore.
    for symbol in TARGET_COINS:
        logger.info(f"\n--- Processing {symbol} ---")
        await process_coin(symbol)

    logger.info("✅ Batch Optimization Complete.")

if __name__ == "__main__":
    # Windows Patch for asyncio
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    asyncio.run(main())