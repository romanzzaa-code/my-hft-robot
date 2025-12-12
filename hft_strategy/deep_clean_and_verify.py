# hft_strategy/deep_clean_and_verify.py
import numpy as np
import os
import sys

FILE = "data/parts/part_000.npz"

# Маски флагов (для проверки)
BUY_BIT = 1
SELL_BIT = 2

def run_deep_clean():
    print(f"🧹 DEEP CLEANING {FILE}...")
    
    if not os.path.exists(FILE):
        print("❌ File not found")
        return

    # 1. Загрузка
    data = np.load(FILE)['data']
    data = np.array(data, copy=True)
    total_rows = len(data)
    print(f"   Total rows to scan: {total_rows}")

    # --- ЭТАП 1: Проверка Genesis (Строки 0 и 1) ---
    print("\n🔍 PHASE 1: Verifying Genesis Sides...")
    ev0 = int(data[0]['ev'])
    ev1 = int(data[1]['ev'])
    
    # Проверяем наличие битов стороны
    has_buy = (ev0 & BUY_BIT)
    has_sell = (ev1 & SELL_BIT)
    
    if not has_buy:
        print("   ⚠️ Row 0 missing BUY flag. Fixing...")
        data[0]['ev'] = ev0 | BUY_BIT
    else:
        print("   ✅ Row 0 has BUY flag.")
        
    if not has_sell:
        print("   ⚠️ Row 1 missing SELL flag. Fixing...")
        data[1]['ev'] = ev1 | SELL_BIT
    else:
        print("   ✅ Row 1 has SELL flag.")

    # --- ЭТАП 2: Поиск Донора ---
    # Нам нужна нормальная цена, чтобы заменять ею нули
    donor_px = 0.0
    donor_ev = 0
    
    for i in range(total_rows):
        if data[i]['px'] > 10.0:
            donor_px = data[i]['px']
            donor_ev = data[i]['ev']
            print(f"   🧬 Donor found at row {i}: {donor_px}")
            break
            
    if donor_px == 0.0:
        print("❌ FATAL: No valid prices in entire file!")
        return

    # --- ЭТАП 3: Глубокая зачистка (Deep Clean) ---
    print("\n☢️ PHASE 2: Nuking ALL zero prices...")
    
    # Находим индексы всех строк с ценой < 0.01 (нули)
    # Используем numpy маски для скорости (это в 100 раз быстрее цикла)
    zero_mask = data['px'] < 0.01
    zero_count = np.count_nonzero(zero_mask)
    
    if zero_count > 0:
        print(f"   ⚠️ Found {zero_count} rows with Zero Price! Destroying them...")
        
        # Перезаписываем их данными донора
        # Мы сохраняем время (local_ts, exch_ts), но меняем цену и тип события
        # Это безопасно превращает "плохую" строку в "повторение нормальной цены"
        data['px'][zero_mask] = donor_px
        data['ev'][zero_mask] = donor_ev 
        # (Оставляем Qty как есть или меняем на 0, но донор безопаснее)
        
        print(f"   ✅ {zero_count} ghosts eliminated.")
    else:
        print("   ✅ No zero prices found (Clean).")

    # 4. Сохранение
    print(f"\n💾 Saving sanitized file...")
    final_data = np.ascontiguousarray(data)
    np.savez_compressed(FILE, data=final_data)
    print("🎉 DONE. File is clean.")

if __name__ == "__main__":
    run_deep_clean()