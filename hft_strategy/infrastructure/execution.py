# hft_strategy/infrastructure/execution.py
import logging
import asyncio
from typing import Optional
# pip install pybit
from pybit.unified_trading import HTTP 
from hft_strategy.config import TRADING_CONFIG

logger = logging.getLogger("EXECUTION")

class BybitExecutionHandler:
    def __init__(self, api_key: str = None, api_secret: str = None, sandbox=False):
        self.read_only = not (api_key and api_secret)
        
        if not self.read_only:
            self.client = HTTP(
                testnet=sandbox,
                api_key=api_key,
                api_secret=api_secret
            )
            logger.info("🔧 Execution: REAL TRADING MODE")
        else:
            self.client = None
            logger.warning("⚠️ Execution: READ-ONLY (No Keys provided)")

        self.symbol = TRADING_CONFIG.symbol
        self.category = "linear"

    async def place_limit_maker(self, side: str, price: float, qty: float) -> Optional[str]:
        """Отправляет PostOnly ордер"""
        if self.read_only:
            logger.info(f"🕶️ [SIM] PLACING {side} {qty} @ {price}")
            # Возвращаем фейковый ID
            return f"sim_oid_{int(asyncio.get_event_loop().time())}"

        try:
            # pybit синхронный, запускаем в thread pool
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: self.client.place_order(
                category=self.category,
                symbol=self.symbol,
                side=side.capitalize(),
                orderType="Limit",
                qty=str(qty),
                price=str(price),
                timeInForce="PostOnly", 
                orderLinkId=f"hft_{int(loop.time()*1000)}"
            ))
            oid = result['result']['orderId']
            logger.info(f"✅ ORDER PLACED: {side} {qty} @ {price} | ID: {oid}")
            return oid
        except Exception as e:
            logger.error(f"❌ Order Failed: {e}")
            return None

    async def cancel_order(self, order_id: str):
        if self.read_only:
            logger.info(f"🕶️ [SIM] CANCEL {order_id}")
            return

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: self.client.cancel_order(
                category=self.category,
                symbol=self.symbol,
                orderId=order_id
            ))
            logger.info(f"🗑️ CANCELLED: {order_id}")
        except Exception as e:
            logger.error(f"❌ Cancel Failed: {e}")

    async def get_position(self) -> float:
        if self.read_only:
            return 0.0

        try:
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(None, lambda: self.client.get_positions(
                category=self.category,
                symbol=self.symbol
            ))
            for pos in resp['result']['list']:
                size = float(pos['size'])
                side = pos['side']
                if size > 0:
                    return size if side == 'Buy' else -size
            return 0.0
        except Exception as e:
            logger.error(f"❌ Position Check Failed: {e}")
            return 0.0