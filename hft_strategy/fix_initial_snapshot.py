# hft_strategy/fix_initial_snapshot.py
import numpy as np
import os
import sys

# Импортируем флаги из библиотеки, чтобы не гадать
from hftbacktest import (
    DEPTH_SNAPSHOT_EVENT, 
    BUY_EVENT, 
    SELL_EVENT,
    DEPTH_EVENT
)

PART_0 = "data/parts/part_000.npz"

def patch_first_chunk():
    print(f"🚑 PATIENT: {PART_0}")
    
    if not os.path.exists(PART_0):
        print("❌ File not found. Check path.")
        return

    # 1. Загружаем
    try:
        data = np.load(PART_0)['data']
        # Делаем копию, доступную для записи
        data = np.array(data, copy=True)
    except Exception as e:
        print(f"❌ Load failed: {e}")
        return

    print(f"📊 Rows: {len(data)}")
    print(f"   First Event Flag (Before): {bin(data[0]['ev'])}")
    print(f"   First TS: {data[0]['local_ts']}")

    # 2. Ищем границы первого снапшота
    # Обычно снапшот имеет одинаковый local_ts для всех уровней
    start_ts = data[0]['local_ts']
    
    # Счетчик изменений
    patched_count = 0
    
    # Проходим по строкам, пока время совпадает с начальным
    for i in range(len(data)):
        row = data[i]
        
        # Если время ушло вперед более чем на 1мс — снапшот кончился
        if row['local_ts'] > start_ts + 1000: 
            break
            
        # ТЕКУЩИЕ ФЛАГИ
        ev = row['ev']
        
        # Нам нужно превратить DEPTH_EVENT (1) -> DEPTH_SNAPSHOT_EVENT (4)
        # При этом сохранить сторону (BUY/SELL)
        
        is_buy = (ev & BUY_EVENT) == BUY_EVENT
        is_sell = (ev & SELL_EVENT) == SELL_EVENT
        
        new_flag = 0
        if is_buy:
            new_flag = DEPTH_SNAPSHOT_EVENT | BUY_EVENT
        elif is_sell:
            new_flag = DEPTH_SNAPSHOT_EVENT | SELL_EVENT
        else:
            # Если это Clear или что-то еще - оставляем или форсируем
            # Обычно для инициализации нужен просто валидный уровень
            pass 

        if new_flag > 0:
            data[i]['ev'] = new_flag
            patched_count += 1

    print(f"🩹 Patched {patched_count} rows to be SNAPSHOT events.")
    print(f"   First Event Flag (After):  {bin(data[0]['ev'])}")

    # 3. Сохраняем обратно
    # Обязательно ascontiguousarray, раз уж мы боролись с памятью
    final_data = np.ascontiguousarray(data)
    np.savez_compressed(PART_0, data=final_data)
    print("✅ SAVED. Try running backtest now.")

if __name__ == "__main__":
    patch_first_chunk()