import pandas as pd
import numpy as np
import os

# === НАСТРОЙКИ ===
# Имя твоего файла (убедись, что он лежит в папке data)
INPUT_CSV = "data/SOLUSDT2025-12-10.csv"
OUTPUT_NPZ = "data/SOLUSDT_ready.npz"

def convert_csv_to_npz():
    print(f"🔍 Читаем файл: {INPUT_CSV} ...")
    
    if not os.path.exists(INPUT_CSV):
        print(f"❌ ОШИБКА: Файл не найден! Положи его в папку data.")
        return

    # 1. Загружаем CSV
    # Bybit CSV обычно имеет заголовки: timestamp, symbol, side, size, price...
    try:
        df = pd.read_csv(INPUT_CSV)
        print(f"✅ Файл открыт. Строк: {len(df)}")
    except Exception as e:
        print(f"❌ Не удалось прочитать CSV: {e}")
        return

    # 2. Определяем колонки (Bybit иногда меняет названия)
    # Ищем колонку времени
    if 'timestamp' in df.columns:
        col_ts = 'timestamp'
    elif 'execTime' in df.columns:
        col_ts = 'execTime'
    else:
        print("❌ Не найдена колонка времени (timestamp или execTime). Доступные: ", df.columns)
        return
        
    # Ищем цену и объем
    col_price = 'price'
    col_size = 'size' if 'size' in df.columns else 'qty'
    
    # 3. Подготовка данных
    # Сортируем по времени
    df = df.sort_values(by=col_ts).reset_index(drop=True)
    
    # Конвертируем колонки в numpy массивы для скорости
    # Время: секунды -> наносекунды
    ts_values = df[col_ts].values * 1_000_000_000 
    price_values = df[col_price].values
    qty_values = df[col_size].values
    
    # Определяем сторону (1 = Buy, -1 = Sell)
    # Если колонки side нет, ставим всем Buy (1)
    if 'side' in df.columns:
        side_values = np.where(df['side'] == 'Buy', 1.0, -1.0)
    else:
        side_values = np.ones(len(df))

    print("⚙️ Генерируем события для бэктеста...")
    
    # 4. Сборка матрицы
    # Формат HftBacktest (Linear): [Event, ExchTS, LocalTS, Side, Price, Qty]
    # Все данные должны быть float64!
    
    rows = []
    tick_size = 0.01
    
    for i in range(len(df)):
        ts = ts_values[i]
        price = price_values[i]
        qty = qty_values[i]
        side = side_values[i]
        
        # --- Событие 1: Обновляем BID (Покупатель) ---
        # Эмулируем, что Bid стоит чуть ниже цены сделки
        rows.append([
            1.0,            # Event Type (1 = Depth Update)
            ts,             # Время биржи
            ts,             # Локальное время
            1.0,            # Side (1 = Bid)
            price - tick_size, # Цена Bid
            1000.0          # Объем (фейковый)
        ])
        
        # --- Событие 2: Обновляем ASK (Продавец) ---
        # Ask стоит чуть выше цены сделки
        rows.append([
            1.0,            # Event Type
            ts, ts,
            -1.0,           # Side (-1 = Ask)
            price + tick_size,
            1000.0
        ])
        
        # --- Событие 3: Сама СДЕЛКА ---
        rows.append([
            4.0,            # Event Type (4 = Trade)
            ts, ts,
            side,           # Кто купил/продал
            price,
            qty
        ])

    # 5. Сохранение
    print("💾 Сохраняем в .npz ...")
    # Важнейший момент: dtype=np.float64
    final_data = np.array(rows, dtype=np.float64)
    
    np.savez_compressed(OUTPUT_NPZ, data=final_data)
    
    print(f"🎉 Готово! Создан файл: {OUTPUT_NPZ}")
    print(f"🚀 Запускай: python hft_strategy/backtest.py --symbol SOLUSDT --input {OUTPUT_NPZ}")

if __name__ == "__main__":
    convert_csv_to_npz()