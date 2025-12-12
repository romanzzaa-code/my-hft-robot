# hft_strategy/backtest_main.py
import sys
import os
import argparse
import numpy as np
import logging
import glob
from numba import njit, objmode
from hftbacktest import (
    HashMapMarketDepthBacktest, 
    BacktestAsset, 
    GTX, LIMIT, 
    Recorder,
    # ИМПОРТИРУЕМ ВСЕ ФЛАГИ
    event_dtype, 
    DEPTH_EVENT, DEPTH_SNAPSHOT_EVENT, DEPTH_CLEAR_EVENT,
    BUY_EVENT, SELL_EVENT,
    EXCH_EVENT, LOCAL_EVENT
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("BACKTEST")

def load_data_smart(files):
    """
    Загружает данные. 
    Если данные уже размечены (ev > 0), просто добавляет системные флаги.
    Если данные сырые, пытается восстановить структуру (fallback).
    """
    logger.info("🔧 Smart Loading Data...")
    
    cleaned_arrays = []
    
    for fpath in files:
        try:
            # 1. Загружаем исходник
            raw = np.load(fpath)['data']
            
            # 2. Создаем структуру с жестким выравниванием
            structured_data = np.empty(len(raw), dtype=event_dtype)
            
            # Копируем поля
            for name in event_dtype.names:
                src_name = name
                if name == 'order_id' and 'oid' in raw.dtype.names: src_name = 'oid'
                if name == 'local_ts' and 'loc_ts' in raw.dtype.names: src_name = 'loc_ts'
                
                if src_name in raw.dtype.names:
                    structured_data[name] = raw[src_name]
                else:
                    structured_data[name] = 0

            # 3. Фильтруем явный мусор по цене
            mask = structured_data['px'] > 0.0000001
            data = structured_data[mask]
            
            if len(data) == 0: continue

            # === ЛОГИКА ОПРЕДЕЛЕНИЯ ТИПА ДАННЫХ ===
            # Проверяем, есть ли уже флаги в поле 'ev'.
            # Если export_data.py отработал, там будут значения типа 1, 2, 3 + флаги сторон.
            # Если это сырой дамп, там скорее всего 0.
            has_precomputed_flags = np.any(data['ev'] > 0)

            if has_precomputed_flags:
                # ВАРИАНТ А: Доверяем данным (export_data.py)
                # Нам нужно только добавить EXCH_EVENT и LOCAL_EVENT, так как библиотека v2.4+ их требует
                # Но мы не должны трогать типы событий (DEPTH/TRADE/CLEAR).
                
                # Добавляем маску системных флагов ко всем событиям
                system_mask = (EXCH_EVENT | LOCAL_EVENT)
                
                # Побитовое ИЛИ: сохраняем то, что было (BUY/SELL/DEPTH...), добавляем системные
                data['ev'] = data['ev'] | system_mask
                
                # Убеждаемся, что qty положительный (библиотека любит abs, хотя export мог ставить минус)
                data['qty'] = np.abs(data['qty'])

            else:
                # ВАРИАНТ Б: Сырые данные (Fallback) - как было раньше
                logger.warning(f"⚠️ File {fpath} has no flags. Reconstructing...")
                
                median = np.median(data['px'])
                is_bid = data['px'] < median
                is_ask = data['px'] >= median
                
                base_flags = DEPTH_EVENT | EXCH_EVENT | LOCAL_EVENT
                new_ev = np.full(len(data), base_flags, dtype=np.uint64)
                
                new_ev[is_bid] |= BUY_EVENT
                new_ev[is_ask] |= SELL_EVENT
                
                data['ev'] = new_ev
                data['qty'] = np.abs(data['qty'])

                # Genesis Patch только для сырых данных
                if len(cleaned_arrays) == 0:
                    data[0]['ev'] = DEPTH_SNAPSHOT_EVENT | BUY_EVENT | EXCH_EVENT | LOCAL_EVENT
                    data[0]['px'] = median - 0.01
                    data[0]['qty'] = 1.0
                    data[1]['ev'] = DEPTH_SNAPSHOT_EVENT | SELL_EVENT | EXCH_EVENT | LOCAL_EVENT
                    data[1]['px'] = median + 0.01
                    data[1]['qty'] = 1.0

            # === ВАЖНО: Память ===
            data = np.ascontiguousarray(data)
            
            # Проверка для первого файла (DEBUG)
            if len(cleaned_arrays) == 0:
                logger.info(f"🔎 First 3 events in {fpath}:")
                for i in range(min(3, len(data))):
                    ev = data[i]['ev']
                    ts = data[i]['local_ts']
                    px = data[i]['px']
                    logger.info(f"   [{i}] TS={ts} EV={ev} PX={px}")

            cleaned_arrays.append(data)
            
        except Exception as e:
            logger.error(f"❌ Error loading {fpath}: {e}")

    logger.info(f"✅ Prepared {len(cleaned_arrays)} chunks.")
    return cleaned_arrays

@njit
def strategy(hbt, recorder):
    asset_no = 0
    tick_size = 0.01
    
    # Состояние стратегии
    # 0 = Ждем входа (Cash), 1 = В позиции (Long)
    state = 0 
    order_id = 1
    
    # Переменные для отслеживания активного ордера
    active_oid = 0
    
    with objmode():
        print("   [STRATEGY] Ping-Pong Logic Started...")

    while hbt.elapse(100_000_000) == 0:
        # 1. Получаем данные
        depth = hbt.depth(asset_no)
        position = hbt.position(asset_no)
        
        # Если стакан пуст, пропускаем шаг
        if depth.best_bid <= 0:
            continue
            
        # 2. Очищаем исполненные или отмененные ордера из списка "активных"
        # (в реальной стратегии нужна более сложная проверка статусов, но для теста пойдет)
        if active_oid > 0:
            # Если ордера нет в списке открытых - значит он исполнился или отменился
            # Простейшая проверка для Numba
            is_open = False
            # hbt.orders(asset_no) возвращает dict-like объект, итерация в numba специфична
            # Проще проверить: если позиция изменилась, значит исполнились
            pass

        # === ЛОГИКА ТОРГОВЛИ ===
        
        # Сценарий 1: Мы в КЭШЕ (поз = 0), хотим КУПИТЬ
        if position == 0:
            # Если нет активного ордера - ставим
            if active_oid == 0:
                price = round(depth.best_bid - tick_size, 2)
                hbt.submit_buy_order(asset_no, order_id, price, 0.1, GTX, LIMIT, False)
                active_oid = order_id
                order_id += 1
            else:
                # Если ордер стоит, но цена ушла - можно было бы переставить,
                # но пока просто ждем (или проверяем, исполнился ли он).
                # Для теста упростим: если позиция стала > 0, сбрасываем active_oid
                pass

        # Сценарий 2: Мы в ЛОНГЕ (поз > 0), хотим ПРОДАТЬ
        elif position > 0.001: # Учитываем погрешность float
            # Сбрасываем флаг ордера на покупку, так как мы уже купили
            if active_oid != 0 and active_oid < order_id: 
                active_oid = 0
                
            if active_oid == 0:
                price = round(depth.best_ask + tick_size, 2)
                hbt.submit_sell_order(asset_no, order_id, price, 0.1, GTX, LIMIT, False)
                active_oid = order_id
                order_id += 1

        # Запись статистики и очистка
        recorder.record(hbt)
        hbt.clear_inactive_orders(asset_no)
    
    return order_id  # Вернем кол-во ордеров

# ... (весь код load_data_smart и strategy остается прежним) ...

def run():
    files = sorted(glob.glob("data/parts/*.npz"))
    if not files:
        # Fallback если нет частей
        files = sorted(glob.glob("data/*_v2.npz"))
        
    if not files:
        logger.error("No files found!")
        return

    # 1. Загружаем данные
    data = load_data_smart(files)
    
    if not data:
        logger.error("No valid data loaded.")
        return

    logger.info("🛠 Initializing Asset...")
    
    # === ГЛАВНОЕ ИСПРАВЛЕНИЕ ===
    # Добавляем tick_size и lot_size.
    # Для SOLUSDT (судя по цене 132.31) tick_size обычно 0.01, lot_size 0.01 или 0.1
    # Без этого HashMap движок не может построить стакан!
    asset = (
        BacktestAsset()
        .data(data)
        .linear_asset(1.0)                 # contract_size (обычно 1.0 для линейных контрактов)
        .tick_size(0.01)                   # <--- ОБЯЗАТЕЛЬНО
        .lot_size(0.01)                    # <--- ОБЯЗАТЕЛЬНО
        .constant_order_latency(10_000_000, 10_000_000)
    )
    
    hbt = HashMapMarketDepthBacktest([asset])
    
    # Рекордер можно настроить пореже, чтобы не забивать память (тут 20мс)
    recorder = Recorder(1, 20_000_000)
    
    logger.info("▶️ Running Engine...")
    try:
        steps = strategy(hbt, recorder.recorder)
        logger.info(f"🏁 Done. Steps: {steps}")
        recorder.to_npz("stats_sol.npz")
    except Exception as e:
        logger.error(f"Crash: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run()