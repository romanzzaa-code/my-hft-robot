# hft_strategy/fix_price_artifact.py
import numpy as np
import os

FILE = "data/parts/part_000.npz"

def fix_header():
    print(f"🩹 Healing Price Artifact in {FILE}...")
    
    if not os.path.exists(FILE):
        print("❌ File not found")
        return

    # 1. Загружаем (делаем копию, чтобы можно было менять)
    data = np.load(FILE)['data']
    data = np.array(data, copy=True)
    
    # 2. Диагностика ДО
    print(f"   [BEFORE] Row 0: Price={data[0]['px']} | Flags={bin(data[0]['ev'])}")
    print(f"   [BEFORE] Row 1: Price={data[1]['px']} | Flags={bin(data[1]['ev'])}")
    
    # 3. ХИРУРГИЯ: Копируем данные из Row 1 в Row 0
    # Мы оставляем таймстемп Row 0 (на всякий случай), но берем цену, объем и флаги из Row 1
    # Это гарантирует, что старт будет с валидной ценой.
    
    if data[0]['px'] == 0.0:
        print("   ⚠️ Found Zero Price at start. Overwriting with Row 1 data...")
        data[0]['px']  = data[1]['px']
        data[0]['qty'] = data[1]['qty']
        data[0]['ev']  = data[1]['ev'] # Копируем флаги (там есть сторона Buy/Sell)
    else:
        print("   ✅ Row 0 price is already non-zero. No action needed.")

    # 4. Диагностика ПОСЛЕ
    print(f"   [AFTER]  Row 0: Price={data[0]['px']} | Flags={bin(data[0]['ev'])}")

    # 5. Сохранение (обязательно contiguous)
    final_data = np.ascontiguousarray(data)
    np.savez_compressed(FILE, data=final_data)
    print("✅ FILE SAVED. The ghost is gone.")

if __name__ == "__main__":
    fix_header()