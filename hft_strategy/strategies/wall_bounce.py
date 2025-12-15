# hft_strategy/strategies/wall_bounce.py
from numba import njit
from hftbacktest import GTX, GTC, LIMIT # <--- Добавили GTC

@njit
def wall_bounce_strategy(
    hbt, 
    recorder, 
    wall_threshold=1000.0,
    tp_ticks=10,   
    sl_ticks=5     
):
    asset_no = 0
    tick_size = hbt.depth(asset_no).tick_size
    
    order_id = 1
    active_buy_id = -1
    active_sell_id = -1
    
    entry_price = 0.0
    steps = 0
    
    while hbt.elapse(100_000_000) == 0: 
        steps += 1
        hbt.clear_inactive_orders(asset_no)
        
        depth = hbt.depth(asset_no)
        position = hbt.position(asset_no)
        best_bid = depth.best_bid
        best_ask = depth.best_ask
        
        if best_bid <= 1.0: continue

        # Сброс флагов, если ордера исчезли
        # (Простейшая проверка: если мы хотели продать, но ордера нет в системе)
        # В Numba/Hftbacktest v2 это сложнее, полагаемся на логику ниже
        
        is_bid_wall = depth.best_bid_qty >= wall_threshold
        
        # -----------------------------------------------------------
        # 1. ВХОД (Long) - Только Maker (GTX)
        # -----------------------------------------------------------
        if position == 0 and active_buy_id == -1:
            if is_bid_wall:
                price = best_bid + tick_size
                hbt.submit_buy_order(asset_no, order_id, price, 0.1, GTX, LIMIT, False)
                active_buy_id = order_id
                order_id += 1
        
        # Отмена входа
        if position == 0 and active_buy_id != -1 and not is_bid_wall:
             hbt.cancel(asset_no, active_buy_id, False)
             active_buy_id = -1

        # -----------------------------------------------------------
        # 2. ВЫХОД (Exit)
        # -----------------------------------------------------------
        if position > 0.00001: 
            if entry_price == 0.0:
                entry_price = best_bid 

            tp_price = entry_price + (tp_ticks * tick_size)
            sl_price = entry_price - (sl_ticks * tick_size)
            
            # --- STOP LOSS (CRITICAL FIX: GTC) ---
            if best_bid <= sl_price:
                # Если висит TP (GTX), снимаем его
                if active_sell_id != -1:
                    hbt.cancel(asset_no, active_sell_id, False)
                    active_sell_id = -1 
                
                # Шлем Panic Sell как GTC (Taker allowed!)
                if active_sell_id == -1:
                    panic_price = best_bid - (50 * tick_size) 
                    # [FIX] Используем GTC вместо GTX, чтобы пробить стакан
                    hbt.submit_sell_order(asset_no, order_id, panic_price, position, GTC, LIMIT, False)
                    active_sell_id = order_id
                    order_id += 1
            
            # --- TAKE PROFIT (Maker preferred) ---
            elif active_sell_id == -1:
                tp_price_rounded = round(tp_price / tick_size) * tick_size
                hbt.submit_sell_order(asset_no, order_id, tp_price_rounded, position, GTX, LIMIT, False)
                active_sell_id = order_id
                order_id += 1
                
        else:
            # Позиция закрыта
            entry_price = 0.0
            active_sell_id = -1
            
            # Аварийное закрытие шорта (если случайно перевернулись)
            if position < -0.00001:
                hbt.submit_buy_order(asset_no, order_id, best_ask + 1.0, -position, GTC, LIMIT, False)
                order_id += 1

        recorder.record(hbt)
        
    return steps