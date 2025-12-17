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

    async def fetch_instrument_info(self, symbol: str):
        """
        Запрашивает у биржи tick_size и lot_size для монеты.
        Возвращает кортеж (tick_size, lot_size, min_order_qty).
        """
        if self.read_only and not self.client:
            # Фейковые данные для симулятора (чтобы не падало без интернета)
            logger.warning("🕶️ [SIM] Using mock instrument info")
            return 0.01, 0.1, 0.1

        try:
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(None, lambda: self.client.get_instruments_info(
                category=self.category,
                symbol=symbol
            ))
            
            if resp['retCode'] != 0:
                raise ValueError(f"Bybit API Error: {resp['retMsg']}")
                
            item = resp['result']['list'][0]
            
            # Парсим спецификацию
            tick_size = float(item['priceFilter']['tickSize'])
            qty_step = float(item['lotSizeFilter']['qtyStep'])
            min_qty = float(item['lotSizeFilter']['minOrderQty'])
            
            logger.info(f"📏 Instrument Specs for {symbol}: Tick={tick_size}, Lot={qty_step}, MinQty={min_qty}")
            return tick_size, qty_step, min_qty
            
        except Exception as e:
            logger.error(f"❌ Failed to fetch instrument info: {e}")
            raise # Это критично, без этого нельзя запускаться

        
    async def place_market_order(self, side: str, qty: float) -> Optional[str]:
        """
        Отправляет рыночный ордер (Taker).
        Используется для Stop Loss или Panic Exit.
        """
        if self.read_only:
            logger.info(f"🕶️ [SIM] MARKET {side} {qty} (Panic Exit)")
            return f"sim_market_{int(asyncio.get_event_loop().time())}"

        try:
            loop = asyncio.get_running_loop()
            # В Bybit V5 для Market ордера цена не нужна
            result = await loop.run_in_executor(None, lambda: self.client.place_order(
                category=self.category,
                symbol=self.symbol,
                side=side.capitalize(),
                orderType="Market",  # <--- Ключевое отличие
                qty=str(qty),
                # Market ордер не требует timeInForce="PostOnly", он IOC по природе
                orderLinkId=f"panic_{int(loop.time()*1000)}"
            ))
            oid = result['result']['orderId']
            logger.warning(f"🚨 MARKET {side} {qty} EXECUTED | ID: {oid}")
            return oid
        except Exception as e:
            logger.error(f"❌ Market Order Failed: {e}")
            return None

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