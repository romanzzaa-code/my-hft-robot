# hft_strategy/infrastructure/execution.py
import logging
import asyncio
from typing import Optional, List, Dict
from pybit.unified_trading import HTTP 

logger = logging.getLogger("EXECUTION")

class BybitExecutionHandler:
    def __init__(self, api_key: str = None, api_secret: str = None, sandbox=False):
        self.read_only = not (api_key and api_secret)
        self.client = None
        if not self.read_only:
            self.client = HTTP(
                testnet=sandbox,
                api_key=api_key,
                api_secret=api_secret,
                recv_window=5000 
            )
            logger.info("🔧 Execution: REAL TRADING MODE")
        else:
            logger.warning("⚠️ Execution: READ-ONLY (No Keys provided)")

        self.category = "linear"

    def _fmt(self, val: float) -> str:
        return "{:.8f}".format(val).rstrip('0').rstrip('.')

    async def fetch_instrument_info(self, symbol: str) -> tuple[float, float, float]:
        if self.read_only and not self.client:
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
            tick_size = float(item['priceFilter']['tickSize'])
            qty_step = float(item['lotSizeFilter']['qtyStep'])
            min_qty = float(item['lotSizeFilter']['minOrderQty'])
            logger.info(f"📏 Specs for {symbol}: Tick={tick_size}, Lot={qty_step}, MinQty={min_qty}")
            return tick_size, qty_step, min_qty
        except Exception as e:
            logger.error(f"❌ Failed to fetch instrument info: {e}")
            raise 

    async def fetch_ohlc(self, symbol: str, interval: str = "5", limit: int = 20) -> List[Dict]:
        if self.read_only: 
            return []
        max_retries = 3
        for attempt in range(max_retries):
            try:
                loop = asyncio.get_running_loop()
                resp = await loop.run_in_executor(None, lambda: self.client.get_kline(
                    category=self.category,
                    symbol=symbol,
                    interval=interval,
                    limit=limit
                ))
                if resp['retCode'] != 0:
                    logger.warning(f"⚠️ OHLC Error {symbol}: {resp.get('retMsg')}")
                    return []
                klines = []
                for k in resp['result']['list']:
                    klines.append({"h": float(k[2]), "l": float(k[3]), "c": float(k[4])})
                return klines
            except Exception as e:
                err_msg = str(e)
                if ("Connection" in err_msg or "Disconnected" in err_msg) and attempt < max_retries - 1:
                    await asyncio.sleep(0.2 * (attempt + 1))
                    continue
                if attempt == max_retries - 1:
                    logger.error(f"❌ Failed to fetch OHLC: {e}")
        return []

    # [UPDATE] Добавлен аргумент reduce_only
    async def place_market_order(
        self, 
        symbol: str, 
        side: str, 
        qty: float, 
        reduce_only: bool = False,
        order_link_id: Optional[str] = None # <--- NEW
    ) -> Optional[str]:
        
        # Генерация дефолтного ID, если не передан
        link_id = order_link_id or f"panic_{int(asyncio.get_running_loop().time()*1000)}"

        if self.read_only:
            logger.info(f"🕶️ [SIM] MARKET {side} {qty} (RO={reduce_only}, ID={link_id}) on {symbol}")
            return f"sim_market_{link_id}"

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: self.client.place_order(
                category=self.category,
                symbol=symbol,
                side=side.capitalize(),
                orderType="Market",
                qty=self._fmt(qty),
                reduceOnly=reduce_only,
                positionIdx=0,
                orderLinkId=link_id  # <--- ПЕРЕДАЕМ В API
            ))
            oid = result['result']['orderId']
            logger.warning(f"🚨 MARKET {side} {qty} EXECUTED on {symbol} | ID: {oid}")
            return oid
        except Exception as e:
            logger.error(f"❌ Market Order Failed: {e}")
            return None

    # [UPDATE] Добавлен аргумент reduce_only
    async def place_limit_maker(
        self, 
        symbol: str, 
        side: str, 
        price: float, 
        qty: float, 
        reduce_only: bool = False,
        order_link_id: Optional[str] = None,
        stop_loss: Optional[float] = None, # <---
        take_profit: Optional[float] = None # <---
    ) -> Optional[str]:
        
        link_id = order_link_id or f"hft_{int(asyncio.get_running_loop().time()*1000)}"

        if self.read_only:
            logger.info(f"🕶️ [SIM] LIMIT {side} {qty} @ {price} (TP={take_profit}, SL={stop_loss})")
            return f"sim_oid_{link_id}"

        try:
            params = {
                "category": self.category,
                "symbol": symbol,
                "side": side.capitalize(),
                "orderType": "Limit",
                "qty": self._fmt(qty),
                "price": self._fmt(price),
                "timeInForce": "PostOnly",
                "reduceOnly": reduce_only,
                "orderLinkId": link_id,
                "positionIdx": 0, # Обязательно 0 для One-Way
                
                # [КРИТИЧНО] Partial режим нужен для Лимитных Тейков
                "tpslMode": "Partial"
            }
            
            if stop_loss:
                params["stopLoss"] = self._fmt(stop_loss)
                params["slOrderType"] = "Market" # Стоп всегда рыночный для надежности

            if take_profit:
                params["takeProfit"] = self._fmt(take_profit)
                params["tpOrderType"] = "Limit" # Тейк лимитный (Maker)
                params["tpLimitPrice"] = self._fmt(take_profit)

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: self.client.place_order(**params))
            oid = result['result']['orderId']
            logger.info(f"✅ ORDER PLACED: {symbol} {side} {qty} @ {price} | ID: {oid}")
            return oid
        except Exception as e:
            logger.error(f"❌ Order Failed: {e}")
            return None

    # [NEW] Реализация метода amend_order
    async def amend_order(self, symbol: str, order_id: str, qty: float) -> bool:
        """
        Изменяет параметры существующего ордера.
        Используется для подгонки объема Тейк-Профита под реальную позицию.
        """
        if self.read_only:
            logger.info(f"🕶️ [SIM] AMEND {order_id} on {symbol} -> New Qty: {qty}")
            return True

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: self.client.amend_order(
                category=self.category,
                symbol=symbol,
                orderId=order_id,
                qty=self._fmt(qty)
            ))
            logger.info(f"📝 AMENDED: {order_id} ({symbol}) new Qty: {qty}")
            return True
        except Exception as e:
            # Ошибка 10001/110001 (Order not exists/Modified) допустима, если ордер уже исполнился
            logger.warning(f"⚠️ Amend failed: {e}")
            return False

    async def cancel_order(self, symbol: str, order_id: str):
        if self.read_only:
            logger.info(f"🕶️ [SIM] CANCEL {order_id} on {symbol}")
            return

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: self.client.cancel_order(
                category=self.category,
                symbol=symbol,
                orderId=order_id
            ))
            logger.info(f"🗑️ CANCELLED: {order_id} on {symbol}")
        except Exception as e:
            str_e = str(e)
            if "110001" in str_e or "Order not exists" in str_e:
                logger.info(f"ℹ️ Cancel skipped (Order gone): {order_id}")
            else:
                logger.error(f"❌ Cancel Failed: {e}")

    async def get_position(self, symbol: str) -> float:
        if self.read_only: return 0.0
        try:
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(None, lambda: self.client.get_positions(
                category=self.category,
                symbol=symbol
            ))
            for pos in resp['result']['list']:
                if pos['symbol'] == symbol:
                    size = float(pos['size'])
                    side = pos['side']
                    if size > 0:
                        return size if side == 'Buy' else -size
            return 0.0
        except Exception as e:
            logger.error(f"❌ Position Check Failed: {e}")
            return 0.0