# hft_strategy/pipelines/export_data.py
import asyncio
import asyncpg
import numpy as np
import logging
import orjson
import os
import argparse
import sys

# Добавляем корень проекта в путь, чтобы видеть соседние модули
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DB_CONFIG
# Импортируем наш SSOT
from domain.events import (
    DEPTH_EVENT, TRADE_EVENT, DEPTH_CLEAR_EVENT, DEPTH_SNAPSHOT_EVENT,
    BUY_EVENT, SELL_EVENT, EXCH_EVENT, LOCAL_EVENT
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PIPELINE")

# Структура данных, жестко требуемая hftbacktest (Rust)
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

async def export_data(symbol: str, output_file: str, days: int = 30):
    logger.info(f"🚀 Starting EXPORT for {symbol} -> {output_file}")
    
    conn = await asyncpg.connect(**DB_CONFIG.as_dict())
    
    # Список для накопления событий (list of tuples быстрее, чем append в numpy)
    raw_events = []
    
    try:
        first_snapshot_ts = None
        
        async with conn.transaction():
            # ==================================================================
            # ЭТАП 1: СТАКАНЫ (SNAPSHOTS & DELTAS)
            # ==================================================================
            logger.info("📚 Phase 1: Streaming Order Book Data...")
            
            # Используем серверный курсор для экономии памяти
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
                # Приводим к int
                ts_exch = int(row['exch_ts'])
                ts_local = int(row['local_ts'])
                is_snapshot = row['is_snapshot']

                # Ищем "якорь" - первый снэпшот, с которого начнем историю
                if first_snapshot_ts is None:
                    if not is_snapshot:
                        continue # Пропускаем дельты до первого снимка
                    first_snapshot_ts = ts_local
                    logger.info(f"✨ Anchor SNAPSHOT found at {first_snapshot_ts}")

                # Десериализация JSONB (orjson быстрее стандартного json)
                # asyncpg может возвращать str или уже bytes
                bids = orjson.loads(row['bids']) if isinstance(row['bids'], (str, bytes)) else row['bids']
                asks = orjson.loads(row['asks']) if isinstance(row['asks'], (str, bytes)) else row['asks']
                
                # Базовые флаги для этого пакета данных
                # Добавляем EXCH и LOCAL, чтобы движок Rust не отбросил их
                base_flags = EXCH_EVENT | LOCAL_EVENT

                if is_snapshot:
                    # Событие очистки стакана перед накаткой снапшота
                    # Некоторые версии движка требуют SNAPSHOT флаг вместо CLEAR, 
                    # но классический подход: Clear -> Add Orders
                    raw_events.append((
                        base_flags | DEPTH_CLEAR_EVENT, 
                        ts_exch, ts_local, 0.0, 0.0, 0, 0, 0.0
                    ))
                    # Для событий внутри снапшота используем DEPTH_SNAPSHOT_EVENT
                    type_flag = DEPTH_SNAPSHOT_EVENT
                else:
                    # Для дельт
                    type_flag = DEPTH_EVENT

                # Обработка Bids
                if bids:
                    for p, q in bids:
                        # Флаг = Base | Type | Side
                        flag = base_flags | type_flag | BUY_EVENT
                        raw_events.append((
                            flag, ts_exch, ts_local, float(p), float(q), 0, 0, 0.0
                        ))
                
                # Обработка Asks
                if asks:
                    for p, q in asks:
                        # В HftBacktest Side часто кодируется флагом, но иногда требуют отрицательный объем
                        # Для надежности делаем и флаг, и знак (если версия движка поддерживает знак)
                        flag = base_flags | type_flag | SELL_EVENT
                        # qty берем отрицательным на всякий случай (legacy support), 
                        # хотя флаг SELL_EVENT главнее.
                        raw_events.append((
                            flag, ts_exch, ts_local, float(p), -float(q), 0, 0, 0.0
                        ))

            if first_snapshot_ts is None:
                logger.error("❌ No snapshot found! Cannot build order book.")
                return

            # ==================================================================
            # ЭТАП 2: СДЕЛКИ (TRADES)
            # ==================================================================
            logger.info("📊 Phase 2: Streaming Trades...")
            
            # Конвертируем start_time обратно в timestamp для SQL
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
                # is_buyer_maker=True -> Продавец был инициатором (Sell Aggressor)
                is_sell = row['is_buyer_maker']
                
                base_flags = EXCH_EVENT | LOCAL_EVENT | TRADE_EVENT
                
                if is_sell:
                    flag = base_flags | SELL_EVENT
                    qty = -float(row['volume'])
                else:
                    flag = base_flags | BUY_EVENT
                    qty = float(row['volume'])
                
                raw_events.append((
                    flag,
                    int(row['exch_ts']),
                    int(row['local_ts']),
                    float(row['price']),
                    qty,
                    0, 0, 0.0
                ))

        # ==================================================================
        # ЭТАП 3: СБОРКА И СОХРАНЕНИЕ
        # ==================================================================
        logger.info(f"🔨 Merging {len(raw_events)} events...")
        
        # Создаем numpy array с жестким dtype
        data_np = np.array(raw_events, dtype=RUST_DTYPE)
        
        # Сортировка по локальному времени (критично для движка)
        logger.info("Sorting by local_ts...")
        data_np.sort(order=['local_ts'], kind='stable')
        
        # Memory Alignment (Критично для Rust FFI)
        data_np = np.ascontiguousarray(data_np)

        # Валидация времени (Negative Latency Patch)
        # Если local < exch, двигаем local вперед
        mask = data_np['local_ts'] < data_np['exch_ts']
        if np.any(mask):
            count = np.count_nonzero(mask)
            logger.warning(f"🩹 Fixing {count} negative latency timestamps...")
            data_np['local_ts'][mask] = data_np['exch_ts'][mask]

        # Создаем директорию, если нет
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        logger.info(f"💾 Saving compressed NPZ to {output_file}...")
        np.savez_compressed(output_file, data=data_np)
        
        logger.info("✅ EXPORT COMPLETE.")

    except Exception as e:
        logger.error(f"❌ Export Failed: {e}", exc_info=True)
    finally:
        await conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export HFT Data from TimescaleDB")
    parser.add_argument("--symbol", type=str, required=True, help="Trading Pair (e.g. SOLUSDT)")
    parser.add_argument("--output", type=str, default=None, help="Output path")
    parser.add_argument("--days", type=int, default=30, help="Days to export")
    
    args = parser.parse_args()
    
    if args.output is None:
        args.output = f"data/{args.symbol}_v2.npz"
        
    # Windows Patch
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    asyncio.run(export_data(args.symbol, args.output, args.days))