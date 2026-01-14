# hft_strategy/services/notification.py
import aiohttp
import logging
import asyncio
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger("NOTIFIER")

class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.session: Optional[aiohttp.ClientSession] = None
        self.queue = asyncio.Queue()
        self.running = False
        
    async def start(self):
        """Запускает сессию и воркер"""
        self.session = aiohttp.ClientSession()
        self.running = True
        asyncio.create_task(self._worker())
        logger.info("🔔 Telegram Notifier Service Started")
        
    async def stop(self):
        """Корректно закрывает соединения"""
        self.running = False
        if self.session:
            await self.session.close()
            
    def send_trade(self, signal, status="OPEN", pnl: Optional[float] = None):
        """
        Метод 'Fire-and-Forget'. Не блокирует HFT цикл.
        """
        if not self.running: return
        self.queue.put_nowait({
            "type": "trade",
            "signal": signal,
            "status": status,
            "pnl": pnl
        })
        
    async def _worker(self):
        """Фоновый процесс отправки сообщений"""
        while self.running:
            try:
                # Ждем сообщение из очереди
                item = await self.queue.get()
                
                if item["type"] == "trade":
                    await self._send_trade_msg(
                        item["signal"], 
                        item["status"], 
                        item.get("pnl")
                    )
                
                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Notification worker error: {e}")
                
    async def _send_trade_msg(self, signal, status, pnl):
        if not self.session: return
        
        # Выбираем эмодзи
        emoji = "🚀"
        if status == "CANCEL": emoji = "🚫"
        elif status == "PROFIT": emoji = "✅"
        elif status == "LOSS": emoji = "❌"
        elif status == "OPEN": emoji = "🔵"
        
        # Формируем сообщение
        lines = [
            f"{emoji} <b>{status}</b> {signal.symbol}",
            f"Side: {signal.side}",
            f"Price: {signal.price}",
            f"Qty: {signal.qty}",
        ]
        
        if pnl is not None:
            pnl_emoji = "🤑" if pnl > 0 else "🩸"
            lines.append(f"{pnl_emoji} PnL: <b>{pnl:.4f} USDT</b>")
            
        if signal.reason and signal.reason != "Unknown":
            lines.append(f"Reason: {signal.reason}")
            
        msg = "\n".join(lines)
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": msg,
            "parse_mode": "HTML"
        }
        
        try:
            async with self.session.post(url, json=payload) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    logger.error(f"Failed to send TG: {err_text}")
        except Exception as e:
            logger.error(f"Network error sending TG: {e}")