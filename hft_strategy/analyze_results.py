# hft_strategy/analyze_results.py
import numpy as np
import sys
import os
import matplotlib.pyplot as plt
import pandas as pd
import argparse

# Патч путей
sys.path.append(os.getcwd())

# Импорт аналитики из hftbacktest
# Примечание: убедитесь, что hftbacktest обновлен
from hftbacktest.stats import LinearAssetRecord

def analyze(stats_file: str):
    print(f"🧐 Analyzing {stats_file}...")
    
    if not os.path.exists(stats_file):
        print(f"❌ File not found: {stats_file}")
        return

    try:
        # Загружаем данные. Ключ '0' соответствует нулевому активу
        data = np.load(stats_file)['0']
    except KeyError:
        print("❌ Error: Key '0' not found. Stats file might be empty or corrupted.")
        return
    except Exception as e:
        print(f"❌ Error loading NPZ: {e}")
        return

    if len(data) == 0:
        print("⚠️ Warning: No records found. Strategy did not trade or record anything.")
        return

    print(f"✅ Loaded {len(data)} records.")

    # Создаем объект статистики
    # LinearAssetRecord ожидает numpy structured array
    rec = LinearAssetRecord(data)
    
    # Строим статистику
    print("🔄 Resampling and calculating stats (1-minute candles)...")
    try:
        stats = rec.resample('1m').stats()
    except Exception as e:
        print(f"❌ Analysis error: {e}")
        # Иногда помогает вывод сырых данных для отладки
        print("Raw data sample:", data[:5])
        return

    print("\n" + "="*50)
    print("📊 STRATEGY PERFORMANCE REPORT")
    print("="*50)
    stats.summary()
    print("="*50 + "\n")

    # Графики
    print("📉 Generating plots...")
    try:
        stats.plot()
        plt.show()
    except Exception as e:
        print(f"❌ Plotting error: {e}")
        # Фолбек: просто нарисовать эквити
        try:
            plt.plot(stats.equity)
            plt.title("Equity Curve")
            plt.show()
        except:
            pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze Backtest Results")
    parser.add_argument("file", type=str, nargs='?', default="stats_sol.npz", help="Path to stats .npz file")
    
    args = parser.parse_args()
    
    analyze(args.file)