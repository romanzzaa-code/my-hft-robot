# hft_strategy/optimization.py
import sys
import os
import numpy as np
import logging
import optuna
from hftbacktest import (
    HashMapMarketDepthBacktest, 
    BacktestAsset, 
    Recorder
)

# Импортируем стратегию
sys.path.append(os.getcwd())
from hft_strategy.strategies.wall_bounce import wall_bounce_strategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("OPTUNA")
logging.getLogger("hftbacktest").setLevel(logging.ERROR)

DATA_CACHE = None
SYMBOL = "SOLUSDT"

def load_data_once():
    global DATA_CACHE
    if DATA_CACHE is not None:
        return DATA_CACHE
        
    path = f"data/{SYMBOL}_v2.npz"
    if not os.path.exists(path):
        raise FileNotFoundError(f"Data file not found: {path}")
        
    logger.info(f"📦 Loading data from {path}...")
    DATA_CACHE = np.load(path)['data']
    return DATA_CACHE

def get_col_name(names, candidates):
    """Ищет первое совпадение из candidates в names"""
    for c in candidates:
        if c in names:
            return c
    return None

def calculate_metrics_manually(recorder):
    data = recorder.get(0)
    if len(data) < 2:
        return 0.0, 0

    # === [FIX] ДИНАМИЧЕСКИЙ ПОИСК КОЛОНОК ===
    if not data.dtype.names:
        # Если вдруг вернулся сырой массив (но это вряд ли)
        logger.error("Recorder returned non-structured array!")
        return -999.0, 0
        
    names = data.dtype.names
    
    # Ищем колонки по возможным именам
    col_ts = get_col_name(names, ['timestamp', 'ts', 'time'])
    col_mid = get_col_name(names, ['mid', 'price', 'px', 'last'])
    col_bal = get_col_name(names, ['balance', 'equity', 'bal'])
    col_pos = get_col_name(names, ['position', 'pos'])
    col_fee = get_col_name(names, ['fee', 'cost'])

    if not (col_ts and col_mid and col_bal and col_pos):
        # Если не нашли критические колонки — выводим список, чтобы ты мне показал
        logger.error(f"❌ Columns missing! Available: {names}")
        return -999.0, 0

    # Извлекаем данные
    ts = data[col_ts]
    mid = data[col_mid]
    balance = data[col_bal]
    position = data[col_pos]
    fee = data[col_fee] if col_fee else np.zeros_like(balance)
    
    # Расчет Equity
    equity = balance + (position * mid) - fee
    
    trades_count = np.count_nonzero(np.diff(position))
    
    if trades_count < 2:
        return -10.0, trades_count 

    # --- Resampling (1 минута) ---
    t_start = ts[0]
    t_end = ts[-1]
    interval = 60 * 1_000_000_000 
    
    if t_end - t_start < interval:
        return -10.0, trades_count

    target_ts = np.arange(t_start, t_end, interval)
    idxs = np.searchsorted(ts, target_ts) - 1
    idxs[idxs < 0] = 0
    
    eq_resampled = equity[idxs]
    
    with np.errstate(divide='ignore', invalid='ignore'):
        returns = np.diff(eq_resampled) / eq_resampled[:-1]
    
    returns = np.nan_to_num(returns)
    
    if len(returns) == 0 or np.std(returns) == 0:
        return 0.0, trades_count

    # Annualized Sharpe
    sharpe = np.mean(returns) / np.std(returns) * 725.0
    
    return sharpe, trades_count

def objective(trial):
    data = load_data_once()
    
    # Диапазоны
    p_wall = trial.suggest_float("wall_threshold", 5.0, 200.0, step=5.0)
    p_tp = trial.suggest_int("tp_ticks", 5, 50)
    p_sl = trial.suggest_int("sl_ticks", 5, 50)
    
    asset = (
        BacktestAsset()
        .data([data])
        .linear_asset(1.0)
        .tick_size(0.01)
        .lot_size(0.1)
        .constant_order_latency(10_000_000, 10_000_000)
    )
    hbt = HashMapMarketDepthBacktest([asset])
    recorder = Recorder(1, 10_000_000)
    
    try:
        wall_bounce_strategy(
            hbt, 
            recorder.recorder, 
            wall_threshold=p_wall,
            tp_ticks=p_tp,
            sl_ticks=p_sl
        )
    except Exception:
        return -999.0

    sharpe, trades = calculate_metrics_manually(recorder)
    
    # Логируем успешные проходы (опционально)
    # if trades > 10:
    #     logger.info(f"Trial OK: Sharpe={sharpe:.2f}, Trades={trades}")

    if trades < 5:
        return -100.0
        
    score = sharpe + np.log(trades) * 0.2
    return score

if __name__ == "__main__":
    try:
        load_data_once()
        # Выводим инфо о полях один раз для диагностики
        # (в реальном запуске Optuna это будет мешать, но для дебага нужно)
        dummy_rec = Recorder(1, 100)
        # Просто создали, чтобы тип проверить, но данных нет.
        # Ладно, calculate_metrics_manually сама залогирует ошибку, если что.
        
        logger.info("🧠 Starting Optimization (Robust Mode)...")
        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=50, n_jobs=1)
        
        print("\n" + "="*40)
        print("🏆 BEST PARAMETERS")
        print("="*40)
        print(study.best_params)
        print(f"Best Score: {study.best_value}")
        
    except KeyboardInterrupt:
        print("\n🛑 Stopped.")
    except Exception as e:
        logger.error(f"Critical: {e}", exc_info=True)