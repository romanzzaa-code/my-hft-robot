import numpy as np
import sys
import os

# Путь к файлу
file_path = "data/SOLUSDT_v2.npz"

print(f"🔍 Inspecting: {file_path}")

if not os.path.exists(file_path):
    print("❌ File not found!")
    sys.exit(1)

try:
    # Загружаем архив
    data = np.load(file_path)
    print("📂 Files inside .npz:", data.files)
    
    # Обычно данные лежат в ключе 'data'
    if 'data' in data.files:
        arr = data['data']
        print(f"📊 Array Shape: {arr.shape}")
        print(f"running checks...")
        
        # Печатаем первые 10 строк
        print("\n--- FIRST 10 ROWS (Raw Data) ---")
        # Для каждой строки печатаем значения
        for i in range(min(10, len(arr))):
            print(f"Row {i}: {arr[i]}")
            
        print("\n--- STATISTICS ---")
        # Проверяем, есть ли вообще цены > 0
        # Предполагаем, что структура hftbacktest: [ev, ts, local_ts, sid, px, qty, ...]
        # Обычно цена (px) - это 4-й или 5-й элемент, зависит от версии.
        
        # Просто покажи нам структуру, мы разберемся.
    else:
        print("❌ Key 'data' not found in npz.")
        for k in data.files:
            print(f"Key '{k}': {data[k]}")

except Exception as e:
    print(f"❌ Error reading file: {e}")