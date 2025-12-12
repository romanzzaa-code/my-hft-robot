# hft_strategy/sanitize_data.py
import numpy as np
import os

INPUT_FILE = "data/SOLUSDT_v2.npz"
OUTPUT_FILE = "data/SOLUSDT_clean.npz"

def sanitize():
    print(f"📦 Loading {INPUT_FILE}...")
    if not os.path.exists(INPUT_FILE):
        print("❌ File not found!")
        return

    # 1. Загрузка
    raw_data = np.load(INPUT_FILE)['data']
    print(f"   Original shape: {raw_data.shape}")
    print(f"   Original flags: {raw_data.flags}")

    # 2. Лечение памяти (Deep Copy + Contiguous)
    print("🧹 Sanitizing memory layout (creating contiguous copy)...")
    clean_data = np.ascontiguousarray(raw_data).copy()
    
    # 3. Валидация типов (еще раз для уверенности)
    # Rust требует четкого соответствия.
    # Проверим, нет ли мусора в первых рядах
    print(f"   First EV: {clean_data[0]['ev']} (Should be 3 or 4)")
    
    # 4. Сохранение
    print(f"💾 Saving to {OUTPUT_FILE}...")
    np.savez_compressed(OUTPUT_FILE, data=clean_data)
    print("✅ Done! Try running backtest on the CLEAN file.")

if __name__ == "__main__":
    sanitize()