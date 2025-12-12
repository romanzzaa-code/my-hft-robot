import numpy as np
import pandas as pd
from hftbacktest import (
    DEPTH_EVENT, TRADE_EVENT, 
    EXCH_EVENT, LOCAL_EVENT, 
    BUY_EVENT, SELL_EVENT
)

# Укажите ваши файлы
INPUT_CSV = 'ваш_файл_с_данными.csv' 
OUTPUT_NPZ = 'corrected_data.npz'

def convert():
    print("Читаем CSV...")
    df = pd.read_csv(INPUT_CSV)
    
    # Создаем структуру для hftbacktest v2
    dtype = [
        ('ev', '<u8'),       # Флаги (Самое важное!)
        ('exch_ts', '<i8'),  # Время биржи
        ('local_ts', '<i8'), # Локальное время
        ('px', '<f8'),       # Цена
        ('qty', '<f8'),      # Объем
        ('order_id', '<u8'),
        ('ival', '<i8'),
        ('fval', '<f8')
    ]
    data = np.zeros(len(df), dtype=dtype)
    
    # 1. Время (превращаем в наносекунды)
    # Если в CSV секунды (float), умножаем на 1e9. Если миллисекунды - на 1e6.
    # Проверьте ваши данные! Обычно Bybit дает секунды (например 167888.123) или мс.
    # Здесь пример для секунд:
    data['exch_ts'] = (df['timestamp'] * 1_000_000_000).astype(np.int64) 
    data['local_ts'] = data['exch_ts'] + 1000 # Добавляем 1 мкс задержки

    # 2. Цены и объемы
    data['px'] = df['price'].values
    data['qty'] = df['size'].values 

    # 3. ГЛАВНОЕ: Флаги событий (ev)
    # Чтобы движок "увидел" цену, флаг должен быть комбинацией:
    # EXCH_EVENT + LOCAL_EVENT + (BUY или SELL) + (DEPTH или TRADE)
    
    base_flag = EXCH_EVENT | LOCAL_EVENT
    
    # Определяем, это трейд или стакан? (Зависит от вашего CSV)
    # Если это просто тики цен, считаем их обновлением стакана (DEPTH)
    is_trade = False # Поставьте True, если конвертируете файл сделок
    type_flag = TRADE_EVENT if is_trade else DEPTH_EVENT
    
    # Определяем сторону (Buy/Sell)
    is_buy = df['side'] == 'Buy' # Проверьте регистр: 'Buy' или 'buy'
    
    # Записываем флаги
    data['ev'] = np.where(
        is_buy,
        base_flag | type_flag | BUY_EVENT,  # Флаг для Bid
        base_flag | type_flag | SELL_EVENT  # Флаг для Ask
    ).astype(np.uint64)

    # 4. Сортировка и сохранение
    print("Сортировка...")
    data = data[np.argsort(data['local_ts'])]
    
    print("Сохранение...")
    np.savez_compressed(OUTPUT_NPZ, data=data)
    print(f"Готово! Используйте {OUTPUT_NPZ} в backtest_main.py")

if __name__ == '__main__':
    convert()