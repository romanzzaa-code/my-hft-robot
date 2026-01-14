# hft_strategy/services/notification.py
import aiohttp
import logging
import asyncio
from dataclasses import dataclass

logger = logging.getLogger("NOTIFIER")

@dataclass
class TradeSignal:
    symbol: str
    side: str
    price: float
    qty: float
    pnl: float = 0.0
    reason: str = ""

class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.session = None
        self._queue = asyncio.Queue()
        self._worker_task = None

    async def start(self):
        self.session = aiohttp.ClientSession()
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("🔔 Notification Service started")

    async def stop(self):
        if self._worker_task:
            self._worker_task.cancel()
        if self.session:
            await self.session.close()

    def send_trade(self, signal: TradeSignal, status: str):
        """
        status: 'OPEN', 'CLOSE', 'CANCEL', 'PANIC'
        """
        self._queue.put_nowait((status, signal))

    async def _worker(self):
        while True:
            try:
                status, sig = await self._queue.get()
                
                emoji = "ℹ️"
                if status == "OPEN": emoji = "🔵"
                elif status == "CLOSE": emoji = "🟢" if sig.pnl >= 0 else "🔴"
                elif status == "PANIC": emoji = "🚨"
                
                msg = (
                    f"{emoji} <b>{status} {sig.symbol}</b>\n"
                    f"Side: {sig.side}\n"
                    f"Price: {sig.price}\n"
                    f"Qty: {sig.qty}\n"
                )
                if sig.pnl != 0:
                    msg += f"💰 PnL: {sig.pnl:.4f} USDT\n"
                if sig.reason:
                    msg += f"Comment: {sig.reason}"

                url = f"https://api.telegram.org/bot{self.token}/sendMessage"
                payload = {
                    "chat_id": self.chat_id,
                    "text": msg,
                    "parse_mode": "HTML"
                }
                
                async with self.session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        logger.error(f"Failed to send TG: {await resp.text()}")
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Notification error: {e}")
                await asyncio.sleep(1)