# hft_strategy/heal_sides_heuristic.py
import numpy as np
import os

FILE = "data/parts/part_000.npz"

# Константы флагов (V2)
BUY_EVENT = 1
SELL_EVENT = 2

def heal_sides():
    print(f"🧬 HEALING DATA SIDES in {FILE}...")
    
    if not os.path.exists(FILE):
        print("❌ File not found")
        return

    # 1. Загрузка
    data = np.load(FILE)['data']
    data = np.array(data, copy=True)
    
    # 2. Вычисляем Медиану (опорную цену)
    # Игнорируем нули при расчете
    valid_prices = data['px'][data['px'] > 10.0]
    
    if len(valid_prices) == 0:
        print("❌ No valid prices to calculate median!")
        return
        
    median_price = np.median(valid_prices)
    print(f"   🎯 Calculated Median Price: {median_price:.2f}")

    # 3. Эвристическая разметка
    # Если Цена < Медианы -> Считаем это BID (покупатель хочет дешевле)
    # Если Цена >= Медианы -> Считаем это ASK (продавец хочет дороже)
    
    # Создаем маски
    # (Также исключаем явные нули, чтобы не портить флаги мусором)
    is_valid = data['px'] > 10.0
    is_bid = (data['px'] < median_price) & is_valid
    is_ask = (data['px'] >= median_price) & is_valid

    print(f"   📊 Identified {np.count_nonzero(is_bid)} Bids and {np.count_nonzero(is_ask)} Asks.")

    # 4. Применяем флаги
    # Мы добавляем (OR) бит, не стирая остальные (Snapshot, Exch, Local)
    data['ev'][is_bid] |= BUY_EVENT
    data['ev'][is_ask] |= SELL_EVENT
    
    # 5. Спец-обработка для Genesis (первых 2 строк), чтобы наверняка
    # Row 0 -> Bid
    data[0]['px'] = median_price - 0.05
    data[0]['ev'] |= BUY_EVENT
    # Row 1 -> Ask
    data[1]['px'] = median_price + 0.05
    data[1]['ev'] |= SELL_EVENT
    
    print("   💉 Genesis forced: Row 0 is Bid, Row 1 is Ask.")

    # 6. Сохранение
    final_data = np.ascontiguousarray(data)
    np.savez_compressed(FILE, data=final_data)
    print("✅ FILE HEALED. Sides are restored.")

if __name__ == "__main__":
    heal_sides()