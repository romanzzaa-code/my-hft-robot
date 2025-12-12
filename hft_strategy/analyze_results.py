import numpy as np
import pandas as pd
from hftbacktest.stats import LinearAssetRecord

def show_stats(file_path):
    print(f"📊 Analyzing {file_path}...")
    
    try:
        # 1. Загружаем npz файл
        # Recorder сохраняет данные по ключам-номерам ассетов ('0', '1' и т.д.)
        data = np.load(file_path)
        
        # Проверяем ключи (обычно это '0')
        if '0' not in data:
            print("❌ Error: Key '0' not found in NPZ. Keys:", list(data.keys()))
            return

        # Берём данные по нулевому ассету
        asset_data = data['0']
        
        # 2. Генерируем статистику
        # LinearAssetRecord автоматически считает шарп, просадку и т.д.
        stats = LinearAssetRecord(asset_data).stats()
        
        # 3. Выводим красивый отчет
        stats.summary()
        
        # 4. Простая диагностика (если сделок нет)
        print("\n--- Quick Diagnostics ---")
        num_records = len(asset_data)
        print(f"Total Records: {num_records}")
        if num_records > 0:
            print(f"First Record: {asset_data[0]}")
            print(f"Last Record:  {asset_data[-1]}")
            
    except Exception as e:
        print(f"❌ Crash during analysis: {e}")

if __name__ == "__main__":
    # Укажи имя файла, который создал backtest_main.py
    show_stats("stats_sol.npz")