# hft_strategy/force_genesis_book.py
import numpy as np
import os
import sys

# Импортируем флаги
try:
    from hftbacktest import (
        DEPTH_SNAPSHOT_EVENT, 
        BUY_EVENT, SELL_EVENT, 
        EXCH_EVENT, LOCAL_EVENT
    )
except ImportError:
    # Фолбек на случай проблем с импортом, значения для v2
    DEPTH_SNAPSHOT_EVENT = 4
    BUY_EVENT = 1  # 1 << 0
    SELL_EVENT = 2 # 1 << 1
    # 32-й бит и т.д., но лучше взять из inspect_header
    # В вашем inspect_header было 3221225476 -> это старшие биты
    # Но мы будем использовать библиотечные константы, если они есть
    pass

FILE = "data/parts/part_000.npz"

def force_genesis():
    print(f"☢️ PERFORMING GENESIS TRANSPLANT on {FILE}...")
    
    if not os.path.exists(FILE):
        print("❌ File not found")
        return

    # 1. Загрузка
    data = np.load(FILE)['data']
    data = np.array(data, copy=True)
    
    # 2. Ищем "донора" цены (первую цену > 10)
    target_price = 0.0
    for row in data:
        if row['px'] > 10.0:
            target_price = row['px']
            break
            
    if target_price == 0.0:
        print("❌ Could not find any valid price > 10.0 in the file!")
        return
        
    print(f"   🎯 Target Price found: {target_price}")

    # 3. Формируем Флаги
    # Нам нужен полный набор: Источник + Снапшот + Сторона
    # Берем маску источника из любой "живой" строки (например, 5-й)
    # или собираем вручную, если импорт сработал
    
    try:
        source_flags = EXCH_EVENT | LOCAL_EVENT
    except:
        # Если импорт не сработал, берем маску из 5-й строки файла
        # (предполагая, что fix_flags_critical отработал)
        source_flags = int(data[5]['ev']) & ~(255) # Очищаем младшие 8 бит (типы событий)

    flag_bid = source_flags | DEPTH_SNAPSHOT_EVENT | BUY_EVENT
    flag_ask = source_flags | DEPTH_SNAPSHOT_EVENT | SELL_EVENT
    
    # 4. ПЕРЕЗАПИСЬ (GENESIS)
    # Берем время старта из первой строки
    start_ts = data[0]['local_ts']
    
    print(f"   💉 Injecting BID at {target_price - 0.01}")
    print(f"   💉 Injecting ASK at {target_price + 0.01}")
    
    # Row 0 -> Snapshot BID
    data[0]['local_ts'] = start_ts
    data[0]['exch_ts']  = start_ts
    data[0]['px']       = target_price - 0.01
    data[0]['qty']      = 1.0
    data[0]['ev']       = flag_bid

    # Row 1 -> Snapshot ASK
    data[1]['local_ts'] = start_ts
    data[1]['exch_ts']  = start_ts
    data[1]['px']       = target_price + 0.01
    data[1]['qty']      = 1.0
    data[1]['ev']       = flag_ask

    # 5. Сохранение
    final_data = np.ascontiguousarray(data)
    np.savez_compressed(FILE, data=final_data)
    print("✅ GENESIS COMPLETE. Valid Book is guaranteed at T=0.")

if __name__ == "__main__":
    force_genesis()