
import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
from hft_strategy.strategies.adaptive_live_strategy import AdaptiveWallStrategy
from hft_strategy.domain.strategy_config import StrategyParameters
from hft_strategy.domain.trade_context import StrategyState, TradeContext

# --- MOCK CLASSES ---
class MockTick:
    def __init__(self, symbol, price, volume=1.0, timestamp=1000):
        self.symbol = symbol
        self.price = price
        self.volume = volume
        self.timestamp = timestamp

class MockPriceLevel:
    def __init__(self, price, qty):
        self.price = price
        self.qty = qty

class MockDepth:
    def __init__(self, bids, asks, is_snapshot=True):
        self.bids = [MockPriceLevel(p, q) for p, q in bids]
        self.asks = [MockPriceLevel(p, q) for p, q in asks]
        self.is_snapshot = is_snapshot
        self.local_timestamp = time.time()

# --- FIXTURES ---
@pytest.fixture
def cfg():
    return StrategyParameters(
        symbol="BTCUSDT",
        tick_size=1.0,
        lot_size=0.001,
        min_qty=0.001,
        wall_ratio_threshold=10.0,
        min_wall_value_usdt=1000.0, # Маленький для теста
        order_amount_usdt=1000.0,
        stop_loss_ticks=5
    )

@pytest.fixture
def executor():
    exec = MagicMock()
    exec.place_limit_maker = AsyncMock(return_value="oid_123")
    exec.cancel_order = AsyncMock(return_value=True)
    exec.place_market_order = AsyncMock(return_value="panic_oid")
    return exec

@pytest.fixture
async def strategy(executor, cfg):
    # Мокаем только MarketAnalytics.start, чтобы избежать запуска фоновой задачи
    # Но оставляем asyncio.create_task рабочим
    with patch("hft_strategy.services.analytics.MarketAnalytics.start", return_value=AsyncMock()):
        # Также нужно замокать calculate_exits, так как это метод экземпляра
        with patch("hft_strategy.services.analytics.MarketAnalytics.calculate_exits", return_value=(50100.0, 49990.0)), \
             patch("hft_strategy.services.analytics.MarketAnalytics.update_background_volume"):
            
            strat = AdaptiveWallStrategy(executor, cfg)
            # Вручную установим avg_background_vol
            strat.analytics.avg_background_vol = 1.0
            yield strat

# --- TESTS ---

@pytest.mark.asyncio
async def test_false_entry_cancel_on_tick_touch(strategy, executor, cfg):
    """
    Проверка: Бот НЕ должен отменять вход, если цена просто коснулась стены (on_tick).
    """
    wall_p = 50000.0
    entry_p = 50001.0

    # 1. Формируем сигнал (3 подтверждения)
    bids = [(wall_p, 20.0)] + [(wall_p - i, 1.0) for i in range(1, 12)]
    depth = MockDepth(bids=bids, asks=[(50010.0, 1.0)])

    for i in range(3):
        await strategy.on_depth(depth)

    assert strategy.trade_manager.state == StrategyState.ORDER_PLACED

    # 2. Прилетает ТИК по цене СТЕНЫ (50000.0)
    tick = MockTick("BTCUSDT", price=wall_p)
    strategy.on_tick(tick)

    # Даем время на выполнение asyncio.create_task(cancel_entry)
    await asyncio.sleep(0.1)

    # ПРОВЕРКА: Бот вызвал отмену ордера?
    if executor.cancel_order.called:
        pytest.fail("Бот ПЫТАЕТСЯ отменить вход при первом касании стены тиком! (Reproduced)")

    assert strategy.trade_manager.state == StrategyState.ORDER_PLACED

async def test_premature_panic_exit_on_micro_dip(strategy, executor, cfg):
    """
    Проверка: Бот НЕ должен выходить по панике при микро-проколе.
    """
    # 1. Заходим в позицию
    strategy.trade_manager.state = StrategyState.IN_POSITION
    strategy.trade_manager.ctx = TradeContext(
        side="Buy",
        wall_price=50000.0,
        entry_price=50001.0,
        quantity=0.02,
        order_id="oid_123",
        filled_qty=0.02,
        placed_ts=time.time()
    )
    
    # 2. Цена проколола стену на 1 тик: Best Bid = 49999.0
    # Но стена передвинулась на 49999.0 или просто Best Bid стал ниже wall_price.
    depth = MockDepth(
        bids=[(49999.0, 19.0), (49998.0, 5.0)], 
        asks=[(50005.0, 1.0)]
    )
    
    await strategy.on_depth(depth)
    
    if strategy.trade_manager.state == StrategyState.IDLE:
         pytest.fail("Бот вышел по панике при микро-проколе стены! (Reproduced)")
