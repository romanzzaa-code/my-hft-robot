import numpy as np
import logging
import optuna
import traceback
from hftbacktest import (
    HashMapMarketDepthBacktest, 
    BacktestAsset, 
    Recorder
)
from hft_strategy.strategies.adaptive_backtest import adaptive_strategy_backtest

logging.getLogger("hftbacktest").setLevel(logging.ERROR)
logger = logging.getLogger("OPTIMIZER")

class StrategyOptimizer:
    def __init__(self, symbol: str, data: np.ndarray, n_trials: int = 50):
        self.symbol = symbol
        self.data = data 
        self.n_trials = n_trials

    def _calculate_metrics(self, recorder):
        """
        Robust metric calculation that never returns NaN.
        """
        data = recorder.get(0)
        if len(data) < 2 or not data.dtype.names: 
            return -999.0, 0

        try:
            names = data.dtype.names
            col_equity = 'equity' if 'equity' in names else 'balance'
            col_pos = 'position' if 'position' in names else 'pos'
            
            equity = data[col_equity]
            position = data[col_pos]
        except ValueError: 
            return -999.0, 0
        
        trades_count = np.count_nonzero(np.diff(position))
        
        # 1. Если сделок нет или мало -> Штраф (но не NaN)
        if trades_count < 5: 
            return -10.0, trades_count # Малый штраф, чтобы Optuna понимала направление

        # 2. Расчет доходности с защитой от нулей
        # equity[:-1] может быть 0 (банкротство), добавляем epsilon
        denom = equity[:-1].copy()
        denom[denom == 0] = 1e-9 
        
        returns = np.diff(equity) / denom
        
        # Убираем Inf и NaN из массива доходностей (превращаем в 0)
        returns = np.nan_to_num(returns, nan=0.0, posinf=0.0, neginf=0.0)
        
        std_dev = np.std(returns)
        
        # 3. Защита от деления на ноль в Шарпе
        if std_dev < 1e-9:
            return 0.0, trades_count

        sharpe = np.mean(returns) / std_dev * np.sqrt(len(returns))
        
        # 4. Финальная проверка результата
        if not np.isfinite(sharpe):
            return -1.0, trades_count
            
        return sharpe, trades_count

    def _estimate_tick_size(self):
        prices = self.data['px']
        prices = prices[prices > 0]
        if len(prices) < 100: return 0.01
        unique_prices = np.unique(prices[:10000])
        if len(unique_prices) < 2: return 0.01
        diffs = np.diff(unique_prices)
        tick = np.min(diffs[diffs > 0])
        return float(f"{tick:.8f}")

    def _objective(self, trial):
        # Hyperparameters Space
        p_ratio = trial.suggest_float("wall_ratio_threshold", 2.0, 50.0)
        p_min_usdt = trial.suggest_float("min_wall_value_usdt", 5000.0, 500000.0, log=True)
        p_alpha = trial.suggest_float("vol_ema_alpha", 0.001, 0.1, log=True)

        tick_size = self._estimate_tick_size()
        
        asset = (
            BacktestAsset()
            .data([self.data]) 
            .linear_asset(1.0)
            .tick_size(tick_size)
            .lot_size(0.1) 
            .constant_order_latency(10_000_000, 10_000_000)
        )
        hbt = HashMapMarketDepthBacktest([asset])
        recorder = Recorder(1, 10_000_000)
        
        try:
            adaptive_strategy_backtest(
                hbt, 
                recorder.recorder, 
                wall_ratio_threshold=p_ratio,
                min_wall_value_usdt=p_min_usdt,
                vol_ema_alpha=p_alpha
            )
        except Exception:
            # Логируем ошибку, но возвращаем плохое число, а не крашим процесс
            traceback.print_exc()
            return -999.0

        sharpe, trades = self._calculate_metrics(recorder)
        
        # Если вернулся NaN (чего быть не должно), превращаем в штраф
        if not np.isfinite(sharpe):
            return -999.0
            
        # Бонус за количество сделок (логарифмический), чтобы не сидеть без дела
        safe_trades = max(trades, 1)
        score = sharpe + np.log(safe_trades) * 0.05
        
        return score

    def run(self) -> dict:
        # Уникальное имя study, чтобы не конфликтовать со старыми NaN записями
        study_name = f"study_{self.symbol}_v4_robust" 
        
        # Создаем storage в памяти или SQLite (здесь в памяти для скорости)
        study = optuna.create_study(direction="maximize", study_name=study_name)
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        
        logger.info(f"🧠 Optimizing {self.symbol} [Robust Mode]...")
        study.optimize(self._objective, n_trials=self.n_trials, n_jobs=1)
        
        best_result = {
            "symbol": self.symbol,
            "params": study.best_params,
            "score": study.best_value
        }
        logger.info(f"🏆 {self.symbol} Best: {best_result['params']} (Score: {study.best_value:.2f})")
        return best_result