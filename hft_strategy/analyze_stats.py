import numpy as np
import sys
import os
import argparse

def analyze(symbol):
    file_path = f"data/stats_{symbol}.npz"
    if not os.path.exists(file_path):
        print(f"❌ Файл {file_path} не найден. Сначала запустите backtest_bot.py")
        return

    print(f"📂 Анализ: {file_path}")
    data = np.load(file_path)['0'] # Recorder обычно сохраняет под ключом '0'
    
    names = data.dtype.names
    col_equity = 'equity' if 'equity' in names else 'balance'
    col_pos = 'position' if 'position' in names else 'pos'
    
    equity = data[col_equity]
    position = data[col_pos]
    
    # Считаем трейды
    trades_indices = np.where(np.diff(position) != 0)[0]
    num_trades = len(trades_indices)
    
    if num_trades < 2:
        print("⚠️ Нет сделок для анализа.")
        return

    # PnL Analysis
    initial_bal = equity[0]
    final_bal = equity[-1]
    total_pnl = final_bal - initial_bal
    
    # Drawdown
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak
    max_dd = np.min(drawdown) * 100
    
    # Win Rate Approximation (по изменению эквити на сделках)
    # Это упрощенный метод для HFT, так как эквити плавает
    # Для точности берем equity в моменты, когда позиция возвращается в 0 (закрытый цикл)
    
    closed_deals_pnl = []
    entry_equity = initial_bal
    
    # Ищем моменты, когда позиция была !=0, а стала 0 (закрытие)
    was_in_pos = False
    
    for i in range(len(position)):
        if abs(position[i]) > 0.0001:
            if not was_in_pos:
                was_in_pos = True
                entry_equity = equity[i] # Запоминаем эквити при входе
        else:
            if was_in_pos:
                # Позиция закрылась
                was_in_pos = False
                deal_pnl = equity[i] - entry_equity
                closed_deals_pnl.append(deal_pnl)
    
    closed_deals_pnl = np.array(closed_deals_pnl)
    total_deals = len(closed_deals_pnl)
    
    if total_deals > 0:
        wins = closed_deals_pnl[closed_deals_pnl > 0]
        losses = closed_deals_pnl[closed_deals_pnl <= 0]
        
        win_rate = len(wins) / total_deals * 100
        avg_win = np.mean(wins) if len(wins) > 0 else 0
        avg_loss = np.mean(losses) if len(losses) > 0 else 0
        profit_factor = abs(np.sum(wins) / np.sum(losses)) if np.sum(losses) != 0 else 999
        
        print("\n📊 --- ДЕТАЛЬНАЯ СТАТИСТИКА ---")
        print(f"💰 PnL: {total_pnl:.2f} USDT")
        print(f"📉 Max Drawdown: {max_dd:.2f}%")
        print(f"🔄 Всего циклов (Вход-Выход): {total_deals}")
        print(f"🎯 Win Rate: {win_rate:.1f}%")
        print(f"✅ Средний Win: {avg_win:.4f}")
        print(f"❌ Средний Loss: {avg_loss:.4f}")
        print(f"⚖️ Profit Factor: {profit_factor:.2f}")
    else:
        print("⚠️ Не найдено полных циклов (вход-выход).")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, required=True)
    args = parser.parse_args()
    analyze(args.symbol)