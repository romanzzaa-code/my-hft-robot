# hft_strategy/export_data.py
import asyncio
import asyncpg
import numpy as np
import logging
import orjson
import os
import argparse
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hft_strategy.config import DB_CONFIG

# ИМПОРТ ФЛАГОВ
from hftbacktest import (
    DEPTH_EVENT, TRADE_EVENT, DEPTH_CLEAR_EVENT,
    BUY_EVENT, SELL_EVENT
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("EXPORTER")

async def export_data(symbol: str, output_file: str, days: int = 30):
    logger.info(f"🚀 Starting PURE EXPORT for {symbol} (Strictly v2 Flags)")
    conn = await asyncpg.connect(**DB_CONFIG.as_dict())
    
    try:
        raw_data = []
        first_snapshot_ts = None
        
        async with conn.transaction():
            # 1. СТАКАНЫ
            logger.info(f"📚 Phase 1: Streaming DEPTH...")
            time_filter = f"time > NOW() - INTERVAL '{days} days'"
            
            # Читаем стаканы
            depth_query = f"""
                SELECT 
                    EXTRACT(EPOCH FROM exch_time) * 1000000000 AS exch_ts, 
                    EXTRACT(EPOCH FROM time) * 1000000000 AS local_ts,
                    bids,
                    asks,
                    is_snapshot
                FROM market_depth_snapshots
                WHERE symbol = '{symbol}' AND {time_filter}
                ORDER BY time ASC
            """
            
            async for row in conn.cursor(depth_query):
                is_snapshot = row['is_snapshot']

                if first_snapshot_ts is None:
                    if not is_snapshot: continue
                    first_snapshot_ts = int(row['local_ts'])
                    logger.info(f"✨ Anchor SNAPSHOT found at {first_snapshot_ts}")
                
                ts_exch = int(row['exch_ts'])
                ts_local = int(row['local_ts'])
                
                bids = orjson.loads(row['bids']) if isinstance(row['bids'], (str, bytes)) else row['bids']
                asks = orjson.loads(row['asks']) if isinstance(row['asks'], (str, bytes)) else row['asks']
                
                # [FIX] PURE FLAGS ONLY
                # Никаких EXCH_EVENT или LOCAL_EVENT!
                
                if is_snapshot:
                    # Clear Book = 3
                    raw_data.append([DEPTH_CLEAR_EVENT, ts_exch, ts_local, 0, 0, 0, 0, 0.0])

                # Updates = 1
                if bids:
                    for p, q in bids:
                        # Bid = 1 | BUY_EVENT
                        flag = DEPTH_EVENT | BUY_EVENT
                        raw_data.append([flag, ts_exch, ts_local, float(p), float(q), 0, 0, 0.0])
                
                if asks:
                    for p, q in asks:
                        # Ask = 1 | SELL_EVENT (Qty < 0)
                        flag = DEPTH_EVENT | SELL_EVENT
                        raw_data.append([flag, ts_exch, ts_local, float(p), -float(q), 0, 0, 0.0])

            if first_snapshot_ts is None:
                logger.error("❌ No snapshot found!")
                return

            # 2. СДЕЛКИ
            logger.info(f"📊 Phase 2: Streaming TRADES...")
            start_time_sql = first_snapshot_ts / 1_000_000_000.0
            
            trade_query = f"""
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
            
            async for row in conn.cursor(trade_query):
                is_sell = row['is_buyer_maker'] 
                
                # Trade = 2
                if is_sell:
                    flag = TRADE_EVENT | SELL_EVENT
                    qty = -float(row['volume'])
                else:
                    flag = TRADE_EVENT | BUY_EVENT
                    qty = float(row['volume'])
                
                raw_data.append([
                    flag,
                    int(row['exch_ts']),
                    int(row['local_ts']),
                    float(row['price']),
                    qty,
                    0, 0, 0.0
                ])

        # 3. ФИНАЛИЗАЦИЯ
        logger.info(f"🔨 Merging {len(raw_data)} events...")
        
        dtype = [
            ('ev', 'uint64'),       
            ('exch_ts', 'int64'),   
            ('local_ts', 'int64'),  
            ('px', 'float64'),      
            ('qty', 'float64'),     
            ('order_id', 'uint64'), 
            ('ival', 'int64'),      
            ('fval', 'float64')     
        ]
        
        # [CRITICAL] Contiguous Memory Layout
        data_np = np.array([tuple(x) for x in raw_data], dtype=dtype)
        data_np = np.ascontiguousarray(data_np)
        
        mask = data_np['local_ts'] < data_np['exch_ts']
        if np.any(mask):
            data_np['local_ts'][mask] = data_np['exch_ts'][mask]

        logger.info("Sorting...")
        data_np.sort(order=['local_ts'], kind='stable')

        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        np.savez_compressed(output_file, data=data_np)
        logger.info(f"🎉 SUCCESS! Pure data saved to {output_file}")

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await conn.close()

def main():
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

if __name__ == "__main__":
    main()