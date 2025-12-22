import numpy as np
from numba import njit
from hftbacktest import GTX, GTC, LIMIT

STATE_IDLE = 0
STATE_ORDER_PLACED = 1
STATE_IN_POSITION = 2

@njit
def adaptive_strategy_backtest(
    hbt, 
    recorder, 
    # Оптимизируемые параметры
    wall_ratio_threshold=3.0,
    min_wall_value_usdt=10000.0,
    vol_ema_alpha=0.01,
    # Конфигурация
    min_tp_percent=0.2,
    stop_loss_ticks=30,
    order_amount_usdt=100.0  # [FIX] Теперь торгуем на сумму в $, а не кол-во штук
):
    asset_no = 0
    tick_size = 0.0 
    lot_size = 0.0 # [FIX] Размер лота
    
    state = STATE_IDLE
    
    active_order_id = -1
    active_tp_id = -1
    entry_price = 0.0
    wall_price = 0.0
    side = 0 
    order_counter = 1
    
    avg_qty = 0.0
    initialized = False
    data_ready = False

    while hbt.elapse(100_000_000) == 0: 
        hbt.clear_inactive_orders(asset_no)
        depth = hbt.depth(asset_no)
        
        best_bid = depth.best_bid
        best_ask = depth.best_ask
        if best_bid <= 1e-9: continue
            
        if not data_ready:
            tick_size = depth.tick_size
            lot_size = depth.lot_size # Получаем шаг лота
            if tick_size <= 0: tick_size = 0.01
            if lot_size <= 0: lot_size = 1.0 # Fallback
            data_ready = True
            
        position = hbt.position(asset_no)

        bb_qty = depth.best_bid_qty
        ba_qty = depth.best_ask_qty
        current_mid_vol = (bb_qty + ba_qty) / 2.0
        
        if not initialized:
            avg_qty = current_mid_vol
            initialized = True
        else:
            avg_qty = vol_ema_alpha * current_mid_vol + (1.0 - vol_ema_alpha) * avg_qty

        dynamic_qty_threshold = avg_qty * wall_ratio_threshold
        
        # FSM
        if state == STATE_IDLE:
            # [FIX] РАСЧЕТ ОБЪЕМА ОРДЕРА
            # Qty = $$$ / Price
            raw_qty = order_amount_usdt / best_bid
            # Округляем до lot_size (например, до целых или до 0.1)
            order_qty = round(raw_qty / lot_size) * lot_size
            
            if order_qty < lot_size: continue # Слишком мало денег для входа

            bid_val_usdt = best_bid * bb_qty
            is_bid_wall = (bb_qty > dynamic_qty_threshold) and (bid_val_usdt > min_wall_value_usdt)
            
            ask_val_usdt = best_ask * ba_qty
            is_ask_wall = (ba_qty > dynamic_qty_threshold) and (ask_val_usdt > min_wall_value_usdt)
            
            if is_bid_wall:
                price = best_bid + tick_size
                hbt.submit_buy_order(asset_no, order_counter, price, order_qty, GTX, LIMIT, False)
                active_order_id = order_counter
                order_counter += 1
                side = 1
                wall_price = best_bid
                entry_price = price
                state = STATE_ORDER_PLACED
                
            elif is_ask_wall:
                price = best_ask - tick_size
                hbt.submit_sell_order(asset_no, order_counter, price, order_qty, GTX, LIMIT, False)
                active_order_id = order_counter
                order_counter += 1
                side = -1
                wall_price = best_ask
                entry_price = price
                state = STATE_ORDER_PLACED

        elif state == STATE_ORDER_PLACED:
            # Check Fill (теперь сравниваем с реальным order_qty)
            is_filled = False
            # order_qty сохранен в замыкании FSM (Numba handle this correctly only if defined locally)
            # В данном простом FSM order_qty пересчитывается в IDLE, но здесь мы должны знать его.
            # Для простоты считаем: если позиция изменилась значительно.
            if side == 1 and position >= order_qty * 0.99: is_filled = True
            if side == -1 and position <= -order_qty * 0.99: is_filled = True
            
            if is_filled:
                state = STATE_IN_POSITION
                
                # Dynamic TP
                tp_dist = entry_price * (min_tp_percent / 100.0)
                tp_dist = round(tp_dist / tick_size) * tick_size
                if tp_dist < 5 * tick_size: tp_dist = 5 * tick_size
                
                if side == 1:
                    tp_price = entry_price + tp_dist
                    hbt.submit_sell_order(asset_no, order_counter, tp_price, order_qty, GTX, LIMIT, False)
                else:
                    tp_price = entry_price - tp_dist
                    hbt.submit_buy_order(asset_no, order_counter, tp_price, order_qty, GTX, LIMIT, False)
                
                active_tp_id = order_counter
                order_counter += 1
                
            else:
                # Wall Gone Check
                wall_gone = False
                if side == 1:
                    if best_bid < wall_price: wall_gone = True
                    elif best_bid == wall_price and bb_qty < (dynamic_qty_threshold * 0.5): wall_gone = True
                else:
                    if best_ask > wall_price: wall_gone = True
                    elif best_ask == wall_price and ba_qty < (dynamic_qty_threshold * 0.5): wall_gone = True
                
                if wall_gone:
                    hbt.cancel(asset_no, active_order_id, False)
                    state = STATE_IDLE

        elif state == STATE_IN_POSITION:
            if abs(position) < lot_size: # Позиция закрыта
                state = STATE_IDLE
                active_tp_id = -1
                continue

            panic = False
            if side == 1:
                if best_bid < wall_price: panic = True
                if best_bid <= entry_price - (stop_loss_ticks * tick_size): panic = True
            else:
                if best_ask > wall_price: panic = True
                if best_ask >= entry_price + (stop_loss_ticks * tick_size): panic = True
            
            if panic:
                if active_tp_id != -1:
                    hbt.cancel(asset_no, active_tp_id, False)
                
                if side == 1:
                    hbt.submit_sell_order(asset_no, order_counter, best_bid * 0.9, position, GTC, LIMIT, False)
                else:
                    hbt.submit_buy_order(asset_no, order_counter, best_ask * 1.1, abs(position), GTC, LIMIT, False)
                
                order_counter += 1
                state = STATE_IDLE

        recorder.record(hbt)
        
    return True