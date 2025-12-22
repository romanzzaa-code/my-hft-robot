import sys
import os
import numpy as np
import logging
import argparse

# [FIX] Импортируем ConstantFeeModel (обязательно для v2.x)
from hftbacktest import (
    HashMapMarketDepthBacktest, 
    BacktestAsset, 
    Recorder, 
    ConstantFeeModel,
    LinearAsset
)

# Добавляем путь к проекту
sys.path.append(os.getcwd())

from hft_strategy.strategies.adaptive_backtest import adaptive_strategy_backtest
from hft_strategy.domain.strategy_config import StrategyParameters 

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("BACKTEST")

def estimate_tick_size(data):
    """
    Эвристика для определения шага цены.
    """
    prices = data['px']
    prices = prices[prices > 0]
    if len(prices) < 100: return 0.01
    
    unique_prices = np.unique(prices[:10000])
    if len(unique_prices) < 2: return 0.01
    
    diffs = np.diff(unique_prices)
    tick = np.min(diffs[diffs > 0])
    return float(f"{tick:.8f}")

def run(symbol, params):
    logger.info(f"🚀 Initializing Backtest for {symbol}...")
    
    # 1. Загрузка данных
    data_file = f"data/{symbol}_v2.npz"
    if not os.path.exists(data_file):
        logger.error(f"❌ Data file not found: {data_file}")
        return

    logger.info(f"📂 Loading {data_file}...")
    try:
        data = np.load(data_file)['data']
    except Exception as e:
        logger.error(f"❌ Load failed: {e}")
        return

    # 2. Определение параметров
    tick_size = estimate_tick_size(data)
    logger.info(f"🔧 Tick Size: {tick_size}")

    # 3. Настройка Ассета (Strict v2.x Standard)
    # Комиссии Bybit: Maker 0.02% (0.0002), Taker 0.055% (0.00055)
    
    asset = (
        BacktestAsset()
        .data([data])
        # Указываем тип актива (Linear для USDT фьючерсов)
        .linear_asset(1.0) 
        .tick_size(tick_size)
        .lot_size(0.1) 
        # [CRITICAL FIX] Используем ConstantFeeModel вместо устаревших атрибутов
        .fee_model(ConstantFeeModel(0.0002, 0.00055)) 
        # Латенси 10ms
        .constant_order_latency(10_000_000, 10_000_000)
    )
    
    hbt = HashMapMarketDepthBacktest([asset])
    recorder = Recorder(1, 10_000_000)
    
    amount_usdt = float(params.get('amount', 100.0))
    
    logger.info(f"▶️ Running with Amount: ${amount_usdt}")
    logger.info(f"⚙️ Params: {params}")
    
    try:
        # 4. Запуск стратегии
        adaptive_strategy_backtest(
            hbt, 
            recorder.recorder, 
            wall_ratio_threshold=float(params['ratio']),
            min_wall_value_usdt=float(params['min_val']),
            vol_ema_alpha=float(params['alpha']),
            min_tp_percent=float(params.get('tp_pct', 0.2)),
            stop_loss_ticks=int(params.get('sl_ticks', 30)),
            order_amount_usdt=amount_usdt 
        )
        logger.info(f"🏁 Backtest Finished.")
        
    except Exception as e:
        logger.error(f"💥 Runtime Error: {e}", exc_info=True)
        return

    # 5. Сохранение
    output_stats = f"data/stats_{symbol}.npz"
    recorder.to_npz(output_stats)
    logger.info(f"💾 Stats saved to {output_stats}")

if __name__ == "__main__":
    defaults = StrategyParameters("DEFAULT")
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, required=True)
    parser.add_argument("--amount", type=float, default=100.0)
    
    # Strategy Params
    parser.add_argument("--ratio", type=float, default=defaults.wall_ratio_threshold)
    parser.add_argument("--min_val", type=float, default=defaults.min_wall_value_usdt)
    parser.add_argument("--alpha", type=float, default=defaults.vol_ema_alpha)
    
    # Risk Params
    parser.add_argument("--tp_pct", type=float, default=defaults.min_tp_percent)
    parser.add_argument("--sl_ticks", type=int, default=defaults.stop_loss_ticks)
    
    args = parser.parse_args()
    
    params = {
        "amount": args.amount,
        "ratio": args.ratio,
        "min_val": args.min_val,
        "alpha": args.alpha,
        "tp_pct": args.tp_pct,
        "sl_ticks": args.sl_ticks
    }
    
    run(args.symbol, params)