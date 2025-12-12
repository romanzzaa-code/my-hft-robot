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

# ИМПОРТ ФЛАГОВ ИЗ БИБЛИОТЕКИ
from hftbacktest import (
    EXCH_EVENT, LOCAL_EVENT, 
    DEPTH_EVENT, TRADE_EVENT, DEPTH_CLEAR_EVENT,
    BUY_EVENT, SELL_EVENT
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("EXPORTER")

async def export_data(symbol: str, output_file: str, days: int = 30):
    logger.info(f"🚀 Starting ROBUST export for {symbol}")
    conn = await asyncpg.connect(**DB_CONFIG.as_dict())
    
    try:
        raw_data = []
        first_snapshot_found = False
        time_filter = f"time > NOW() - INTERVAL '{days} days'"
        
        async with conn.transaction():
            # 1. СДЕЛКИ
            logger.info(f"📊 Streaming TRADES...")
            trade_query = f"""
                SELECT 
                    EXTRACT(EPOCH FROM exch_time) * 1000000000 AS exch_ts, 
                    EXTRACT(EPOCH FROM time) * 1000000000 AS local_ts,
                    price,
                    volume
                FROM market_ticks
                WHERE symbol = '{symbol}' AND {time_filter}
            """
            async for row in conn.cursor(trade_query):
                # Trade: Exch + Local + Trade + Buy (по умолчанию)
                flag = EXCH_EVENT | LOCAL_EVENT | TRADE_EVENT | BUY_EVENT
                raw_data.append([
                    flag,
                    int(row['exch_ts']),
                    int(row['local_ts']),
                    float(row['price']),
                    float(row['volume']),
                    0, 0, 0.0
                ])

            # 2. СТАКАН (DEPTH)
            logger.info(f"📚 Streaming DEPTH...")
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

                if not first_snapshot_found:
                    if not is_snapshot: continue
                    else:
                        first_snapshot_found = True
                        logger.info(f"✨ First SNAPSHOT found at {int(row['local_ts'])}")

                ts_exch = int(row['exch_ts'])
                ts_local = int(row['local_ts'])
                
                bids = orjson.loads(row['bids']) if isinstance(row['bids'], (str, bytes)) else row['bids']
                asks = orjson.loads(row['asks']) if isinstance(row['asks'], (str, bytes)) else row['asks']
                
                # --- ЛОГИКА "ЖЕЛЕЗОБЕТОННОГО" СНЭПШОТА ---
                
                # 1. Если это снэпшот -> сначала посылаем CLEAR
                if is_snapshot:
                    clear_flag = EXCH_EVENT | LOCAL_EVENT | DEPTH_CLEAR_EVENT
                    raw_data.append([clear_flag, ts_exch, ts_local, 0, 0, 0, 0, 0.0])

                # 2. Затем посылаем уровни как обычные ОБНОВЛЕНИЯ (DEPTH_EVENT)
                # Это работает всегда: движок очистил стакан и заполнил его заново.
                # Не используем DEPTH_SNAPSHOT_EVENT, так как он капризный.
                
                base_flag = EXCH_EVENT | LOCAL_EVENT | DEPTH_EVENT

                if bids:
                    for p, q in bids:
                        # Bid Update
                        raw_data.append([base_flag | BUY_EVENT, ts_exch, ts_local, float(p), float(q), 0, 0, 0.0])
                
                if asks:
                    for p, q in asks:
                        # Ask Update
                        raw_data.append([base_flag | SELL_EVENT, ts_exch, ts_local, float(p), float(q), 0, 0, 0.0])

        # 3. MERGE & SORT
        logger.info(f"🔨 Merging {len(raw_data)} events...")
        if len(raw_data) == 0:
            logger.error("❌ No data found.")
            return

        dtype = [
            ('ev', 'uint64'),
            ('exch_ts', 'i8'), 
            ('local_ts', 'i8'), 
            ('px', 'f8'), 
            ('qty', 'f8'), 
            ('order_id', 'uint64'),
            ('ival', 'i8'), 
            ('fval', 'f8')
        ]
        
        data_np = np.array([tuple(x) for x in raw_data], dtype=dtype)
        
        # Сначала чиним время
        mask = data_np['local_ts'] < data_np['exch_ts']
        if np.any(mask):
            data_np['local_ts'][mask] = data_np['exch_ts'][mask]

        # Потом сортируем (Stable sort важен для сохранения порядка Clear -> Updates)
        logger.info("Sorting by Local Timestamp (Stable)...")
        data_np.sort(order=['local_ts'], kind='stable')

        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        np.savez_compressed(output_file, data=data_np)
        logger.info(f"🎉 SUCCESS! Saved {output_file}")

    except Exception as e:
        logger.error(f"❌ Error: {e}")
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