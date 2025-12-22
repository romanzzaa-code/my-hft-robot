# hft_strategy/pipelines/export_data.py
import asyncio
import asyncpg
import numpy as np
import logging
import orjson
import os
import argparse
import sys

# Добавляем корень проекта в путь
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hft_strategy.config import DB_CONFIG
from hft_strategy.domain.events import (
    DEPTH_EVENT, TRADE_EVENT, DEPTH_CLEAR_EVENT, DEPTH_SNAPSHOT_EVENT,
    BUY_EVENT, SELL_EVENT, EXCH_EVENT, LOCAL_EVENT
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PIPELINE")

RUST_DTYPE = np.dtype([
    ('ev', 'uint64'),       
    ('exch_ts', 'int64'),   
    ('local_ts', 'int64'),  
    ('px', 'float64'),      
    ('qty', 'float64'),     
    ('order_id', 'uint64'), 
    ('ival', 'int64'),      
    ('fval', 'float64')     
])

MAX_INT64 = np.iinfo(np.int64).max
MIN_TS = 0 

async def export_data(symbol: str, output_file: str, days: int = 30):
    logger.info(f"🚀 Starting EXPORT for {symbol} -> {output_file}")
    
    conn = await asyncpg.connect(**DB_CONFIG.as_dict())
    raw_events = []
    
    try:
        first_snapshot_ts = None
        fixed_timestamps = 0
        
        async with conn.transaction():
            # --- PHASE 1: DEPTH ---
            logger.info("📚 Phase 1: Streaming Order Book Data...")
            
            query_depth = f"""
                SELECT 
                    EXTRACT(EPOCH FROM exch_time) * 1000000000 AS exch_ts, 
                    EXTRACT(EPOCH FROM time) * 1000000000 AS local_ts,
                    bids,
                    asks,
                    is_snapshot
                FROM market_depth_snapshots
                WHERE symbol = '{symbol}' 
                  AND time > NOW() - INTERVAL '{days} days'
                ORDER BY time ASC
            """
            
            async for row in conn.cursor(query_depth):
                try:
                    ts_exch = int(row['exch_ts'])
                    ts_local = int(row['local_ts'])
                    
                    # [SMART FIX] Если время биржи улетело в будущее (баг /100), возвращаем его назад
                    if ts_exch > MAX_INT64:
                        ts_exch = ts_exch // 10
                        fixed_timestamps += 1

                    # Финальная проверка
                    if not (MIN_TS < ts_exch < MAX_INT64 and MIN_TS < ts_local < MAX_INT64):
                        continue

                    is_snapshot = row['is_snapshot']

                    if first_snapshot_ts is None:
                        if not is_snapshot: continue 
                        first_snapshot_ts = ts_local
                        logger.info(f"✨ Anchor SNAPSHOT found at {first_snapshot_ts}")

                    bids = orjson.loads(row['bids']) if isinstance(row['bids'], (str, bytes)) else row['bids']
                    asks = orjson.loads(row['asks']) if isinstance(row['asks'], (str, bytes)) else row['asks']
                    
                    base_flags = EXCH_EVENT | LOCAL_EVENT
                    type_flag = DEPTH_SNAPSHOT_EVENT if is_snapshot else DEPTH_EVENT

                    if is_snapshot:
                        raw_events.append((base_flags | DEPTH_CLEAR_EVENT, ts_exch, ts_local, 0.0, 0.0, 0, 0, 0.0))

                    if bids:
                        for p, q in bids:
                            raw_events.append((base_flags | type_flag | BUY_EVENT, ts_exch, ts_local, float(p), float(q), 0, 0, 0.0))
                    
                    if asks:
                        for p, q in asks:
                            raw_events.append((base_flags | type_flag | SELL_EVENT, ts_exch, ts_local, float(p), -float(q), 0, 0, 0.0))
                            
                except Exception:
                    continue

            if first_snapshot_ts is None:
                logger.error("❌ No snapshot found! Cannot build order book.")
                return

            if fixed_timestamps > 0:
                logger.warning(f"🩹 Auto-healed {fixed_timestamps} corrupted timestamps (Bug /100 fixed)")

            # --- PHASE 2: TRADES ---
            logger.info("📊 Phase 2: Streaming Trades...")
            start_time_sql = first_snapshot_ts / 1_000_000_000.0
            
            query_trades = f"""
                SELECT 
                    EXTRACT(EPOCH FROM exch_time) * 1000000000 AS exch_ts, 
                    EXTRACT(EPOCH FROM time) * 1000000000 AS local_ts,
                    price,
                    volume,
                    is_buyer_maker
                FROM market_ticks
                WHERE symbol = '{symbol}' 
                  AND time >= to_timestamp({start_time_sql})
            """
            
            async for row in conn.cursor(query_trades):
                try:
                    ts_exch = int(row['exch_ts'])
                    ts_local = int(row['local_ts'])

                    # [SMART FIX] Тот же патч для сделок
                    if ts_exch > MAX_INT64:
                        ts_exch = ts_exch // 10
                    
                    if not (MIN_TS < ts_exch < MAX_INT64 and MIN_TS < ts_local < MAX_INT64):
                        continue

                    is_sell = row['is_buyer_maker']
                    base_flags = EXCH_EVENT | LOCAL_EVENT | TRADE_EVENT
                    flag = base_flags | (SELL_EVENT if is_sell else BUY_EVENT)
                    qty = -float(row['volume']) if is_sell else float(row['volume'])
                    
                    raw_events.append((flag, ts_exch, ts_local, float(row['price']), qty, 0, 0, 0.0))
                except Exception:
                    continue

        # --- PHASE 3: SAVE ---
        if not raw_events:
            logger.warning(f"⚠️ No valid events found for {symbol}")
            return

        logger.info(f"🔨 Merging {len(raw_events)} events...")
        data_np = np.array(raw_events, dtype=RUST_DTYPE)
        
        logger.info("Sorting by local_ts...")
        data_np.sort(order=['local_ts'], kind='stable')
        data_np = np.ascontiguousarray(data_np)

        # Fix Negative Latency
        mask = data_np['local_ts'] < data_np['exch_ts']
        if np.any(mask):
            count = np.count_nonzero(mask)
            # logger.warning(f"🩹 Fixing {count} negative latency timestamps...")
            data_np['local_ts'][mask] = data_np['exch_ts'][mask]

        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        logger.info(f"💾 Saving compressed NPZ to {output_file}...")
        np.savez_compressed(output_file, data=data_np)
        logger.info("✅ EXPORT COMPLETE.")

    except Exception as e:
        logger.error(f"❌ Export Failed: {e}", exc_info=True)
    finally:
        await conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, required=True)
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    
    if args.output is None:
        args.output = f"data/{args.symbol}_v2.npz"
        
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    asyncio.run(export_data(args.symbol, args.output, args.days))