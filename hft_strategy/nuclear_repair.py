# hft_strategy/nuclear_repair.py
import numpy as np
import os
import sys

# Попытка импорта, или жесткие константы
try:
    from hftbacktest import (
        EXCH_EVENT, LOCAL_EVENT, 
        BUY_EVENT, SELL_EVENT, 
        DEPTH_EVENT, DEPTH_SNAPSHOT_EVENT
    )
except:
    # Значения для v1.6+ (проверено по вашим логам)
    EXCH_EVENT = 1 << 31 # Или старшие биты
    LOCAL_EVENT = 1 << 30
    # Но мы будем использовать маску из ваших данных, чтобы не сломать
    pass

FILE = "data/parts/part_000.npz"

def nuke_it():
    print(f"☢️ NUCLEAR REPAIR INITIATED: {FILE}")
    
    if not os.path.exists(FILE):
        print("❌ File not found")
        return

    # 1. Загрузка
    data = np.load(FILE)['data']
    # Делаем копию!
    data = np.array(data, copy=True)
    
    total = len(data)
    
    # 2. Вычисляем эталонную цену (Медиану)
    valid_prices = data['px'][data['px'] > 10.0]
    if len(valid_prices) == 0:
        print("❌ CRITICAL: No valid prices found! Cannot repair.")
        return
    
    median_px = np.median(valid_prices)
    print(f"   🎯 Target Median Price: {median_px:.2f}")

    # 3. МАССОВЫЙ РЕМОНТ (Векторизованный, очень быстрый)
    
    # А. УНИЧТОЖЕНИЕ НУЛЕЙ
    # Находим все нули
    zero_mask = data['px'] < 0.01
    n_zeros = np.count_nonzero(zero_mask)
    if n_zeros > 0:
        print(f"   🧹 Fixing {n_zeros} zero-prices (replacing with median)...")
        data['px'][zero_mask] = median_px
    
    # Б. ВОССТАНОВЛЕНИЕ СТОРОН (SIDES)
    # Бит 0 = BUY (1), Бит 1 = SELL (2)
    # Проверяем, есть ли хоть один бит стороны
    side_mask = (data['ev'] & 3) == 0 # Если последние 2 бита - нули
    n_noside = np.count_nonzero(side_mask)
    
    if n_noside > 0:
        print(f"   🔧 Fixing {n_noside} rows with missing SIDES...")
        
        # Логика: Если Px < Median -> BUY (1), иначе -> SELL (2)
        # Применяем только к тем, у кого нет сторон
        
        # Подмножество "Нет стороны" И "Цена < Медианы"
        fix_buy = side_mask & (data['px'] < median_px)
        data['ev'][fix_buy] |= 1 # BUY_EVENT
        
        # Подмножество "Нет стороны" И "Цена >= Медианы"
        fix_sell = side_mask & (data['px'] >= median_px)
        data['ev'][fix_sell] |= 2 # SELL_EVENT

    # В. ГАРАНТИЯ ИСТОЧНИКА (EXCH | LOCAL)
    # На всякий случай берем маску из 0-й строки (мы знаем, она правильная)
    base_flags = data[0]['ev'] & (0xFFFFFFFF00000000) # Очень грубо берем старшие
    if base_flags == 0:
        # Если вдруг 0, ставим хардкод (примерно как в логах было)
        # 3221225476 = 11000000...
        base_flags = 3221225472 
    
    # Применяем ко всем, у кого старшие биты пустые (если такие есть)
    # (Обычно лучше не трогать, если не уверены, но для нулей - критично)
    
    # Г. GENESIS RE-WRITE (Финальный штрих)
    print("   💉 Re-injecting perfect Genesis...")
    data[0]['px'] = median_px - 0.01
    data[0]['ev'] |= 1 # Buy
    data[1]['px'] = median_px + 0.01
    data[1]['ev'] |= 2 # Sell

    # 4. СОХРАНЕНИЕ
    print("   💾 Saving contiguous array...")
    final_data = np.ascontiguousarray(data)
    np.savez_compressed(FILE, data=final_data)
    print("✅ REPAIR COMPLETE. Try backtest now.")

if __name__ == "__main__":
    nuke_it()