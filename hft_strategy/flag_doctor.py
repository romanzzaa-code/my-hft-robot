# hft_strategy/flag_doctor_v2.py
import numpy as np
import logging
from numba import njit
from hftbacktest import (
    BacktestAsset, 
    HashMapMarketDepthBacktest, 
    # Импортируем ВСЁ
    EXCH_EVENT, LOCAL_EVENT, 
    DEPTH_EVENT, TRADE_EVENT, 
    DEPTH_CLEAR_EVENT, DEPTH_SNAPSHOT_EVENT,
    BUY_EVENT, SELL_EVENT
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("DOC_V2")

def print_constants():
    logger.info("🔍 LIBRARY CONSTANTS CHECK:")
    logger.info(f"  DEPTH_EVENT: {DEPTH_EVENT}")
    logger.info(f"  TRADE_EVENT: {TRADE_EVENT}")
    logger.info(f"  DEPTH_CLEAR_EVENT: {DEPTH_CLEAR_EVENT}")
    logger.info(f"  DEPTH_SNAPSHOT_EVENT: {DEPTH_SNAPSHOT_EVENT}")
    logger.info(f"  BUY_EVENT: {BUY_EVENT}")
    logger.info(f"  EXCH_EVENT: {EXCH_EVENT}")
    logger.info("-" * 30)

@njit
def check_alive(hbt):
    if hbt.elapse(1_000_000_000) == 0:
        d = hbt.depth(0)
        # Проверяем, появилась ли цена
        if d.best_bid > 0:
            return 1, d.best_bid
    return 0, 0.0

def test_scenario(name, events):
    dtype = [('ev', 'uint64'), ('exch_ts', 'i8'), ('local_ts', 'i8'), ('px', 'f8'), ('qty', 'f8'), ('order_id', 'u8'), ('ival', 'i8'), ('fval', 'f8')]
    data = np.array(events, dtype=dtype)
    
    asset = BacktestAsset().data(data).linear_asset(1.0).constant_order_latency(0, 0)
    
    try:
        hbt = HashMapMarketDepthBacktest([asset])
        res, price = check_alive(hbt)
        if res == 1:
            logger.info(f"✅ PASS: {name} | Bid: {price}")
            return True
        else:
            logger.info(f"❌ FAIL: {name}")
            return False
    except Exception as e:
        logger.info(f"💥 CRASH: {name} -> {e}")
        return False

def run_doctor():
    print_constants()
    
    start_ts = 100
    
    # Сценарий A: Стандартный (CLEAR + DEPTH_EVENT)
    # Используем EXCH | LOCAL
    flags = EXCH_EVENT | LOCAL_EVENT
    
    rows_a = []
    # 1. Clear
    rows_a.append((flags | DEPTH_CLEAR_EVENT, start_ts, start_ts, 0, 0, 0, 0, 0.0))
    # 2. Bid (Depth Event)
    rows_a.append((flags | DEPTH_EVENT | BUY_EVENT, start_ts, start_ts, 100.0, 1.0, 0, 0, 0.0))
    # 3. Wait
    rows_a.append((flags | TRADE_EVENT, start_ts + 1000, start_ts + 1000, 100.0, 1.0, 0, 0, 0.0))
    
    test_scenario("Scenario A: CLEAR + DEPTH_EVENT", rows_a)

    # Сценарий B: SNAPSHOT EVENT
    # Некоторые версии требуют, чтобы начальный стакан шел с флагом SNAPSHOT
    rows_b = []
    # 1. Clear (на всякий случай)
    rows_b.append((flags | DEPTH_CLEAR_EVENT, start_ts, start_ts, 0, 0, 0, 0, 0.0))
    # 2. Bid (SNAPSHOT Event)
    rows_b.append((flags | DEPTH_SNAPSHOT_EVENT | BUY_EVENT, start_ts, start_ts, 200.0, 1.0, 0, 0, 0.0))
    # 3. Wait
    rows_b.append((flags | TRADE_EVENT, start_ts + 1000, start_ts + 1000, 100.0, 1.0, 0, 0, 0.0))
    
    test_scenario("Scenario B: CLEAR + SNAPSHOT_EVENT", rows_b)

    # Сценарий C: Только SNAPSHOT (без Clear)
    rows_c = []
    rows_c.append((flags | DEPTH_SNAPSHOT_EVENT | BUY_EVENT, start_ts, start_ts, 300.0, 1.0, 0, 0, 0.0))
    rows_c.append((flags | TRADE_EVENT, start_ts + 1000, start_ts + 1000, 100.0, 1.0, 0, 0, 0.0))
    
    test_scenario("Scenario C: SNAPSHOT Only", rows_c)

if __name__ == "__main__":
    run_doctor()