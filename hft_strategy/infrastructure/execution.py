# hft_strategy/infrastructure/execution.py
import logging
import asyncio
from typing import Optional, List, Dict
from pybit.unified_trading import HTTP 
# from hft_strategy.config import TRADING_CONFIG <-- Больше не нужен здесь для символа

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

        # self.symbol = TRADING_CONFIG.symbol  <-- УДАЛЯЕМ ЭТО ПОЛЕ
        self.category = "linear"

    def _fmt(self, val: float) -> str:
        return "{:.8f}".format(val).rstrip('0').rstrip('.')

    async def fetch_instrument_info(self, symbol: str) -> tuple[float, float, float]:
        # ... (код без изменений, тут symbol и так передавался)
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

    # ... (внутри класса BybitExecutionHandler)

    async def fetch_ohlc(self, symbol: str, interval: str = "5", limit: int = 20) -> List[Dict]:
        if self.read_only: 
            return []
            
        # Попыток запроса (1 основной + 2 ретрая)
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                loop = asyncio.get_running_loop()
                
                # Выполняем блокирующий запрос в отдельном потоке
                resp = await loop.run_in_executor(None, lambda: self.client.get_kline(
                    category=self.category,
                    symbol=symbol,
                    interval=interval,
                    limit=limit
                ))
                
                if resp['retCode'] != 0:
                    # Логическая ошибка API (не сеть) — ретраить нет смысла, если это не Rate Limit
                    # Но для простоты вернем пустоту
                    logger.warning(f"⚠️ OHLC Error {symbol}: {resp.get('retMsg')}")
                    return []

                klines = []
                for k in resp['result']['list']:
                    high = float(k[2])
                    low = float(k[3])
                    close = float(k[4])
                    klines.append({"h": high, "l": low, "c": close})
                
                return klines

            except Exception as e:
                # Проверяем, является ли ошибка сетевой (Connection aborted, RemoteDisconnected, SSL Error)
                err_msg = str(e)
                is_network_error = "Connection" in err_msg or "Disconnected" in err_msg or "Reset" in err_msg
                
                if is_network_error and attempt < max_retries - 1:
                    # Экспоненциальная задержка: 0.2с, 0.4с
                    sleep_time = 0.2 * (attempt + 1)
                    # logger.debug(f"🔄 Retry fetch_ohlc ({attempt+1}/{max_retries}) due to: {e}")
                    await asyncio.sleep(sleep_time)
                    continue
                
                # Если попытки кончились или ошибка критическая — логируем
                if attempt == max_retries - 1:
                    logger.error(f"❌ Failed to fetch OHLC after {max_retries} attempts: {e}")
                    
        return []

    # [FIX] Добавлен аргумент symbol
    async def place_market_order(self, symbol: str, side: str, qty: float) -> Optional[str]:
        if self.read_only:
            logger.info(f"🕶️ [SIM] MARKET {side} {qty} (Panic Exit) on {symbol}")
            return f"sim_market_{int(asyncio.get_running_loop().time())}"

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: self.client.place_order(
                category=self.category,
                symbol=symbol,       # <--- ИСПОЛЬЗУЕМ АРГУМЕНТ
                side=side.capitalize(),
                orderType="Market",
                qty=self._fmt(qty),
                orderLinkId=f"panic_{int(loop.time()*1000)}"
            ))
            oid = result['result']['orderId']
            logger.warning(f"🚨 MARKET {side} {qty} EXECUTED on {symbol} | ID: {oid}")
            return oid
        except Exception as e:
            logger.error(f"❌ Market Order Failed: {e}")
            return None

    # [FIX] Добавлен аргумент symbol
    async def place_limit_maker(self, symbol: str, side: str, price: float, qty: float) -> Optional[str]:
        if self.read_only:
            logger.info(f"🕶️ [SIM] PLACING {side} {qty} @ {price} on {symbol}")
            return f"sim_oid_{int(asyncio.get_running_loop().time())}"

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: self.client.place_order(
                category=self.category,
                symbol=symbol,       # <--- ИСПОЛЬЗУЕМ АРГУМЕНТ
                side=side.capitalize(),
                orderType="Limit",
                qty=self._fmt(qty),
                price=self._fmt(price),
                timeInForce="PostOnly", 
                orderLinkId=f"hft_{int(loop.time()*1000)}"
            ))
            oid = result['result']['orderId']
            logger.info(f"✅ ORDER PLACED: {symbol} {side} {qty} @ {price} | ID: {oid}")
            return oid
        except Exception as e:
            logger.error(f"❌ Order Failed: {e}")
            return None

    # [FIX] Добавлен аргумент symbol
    async def cancel_order(self, symbol: str, order_id: str):
        if self.read_only:
            logger.info(f"🕶️ [SIM] CANCEL {order_id} on {symbol}")
            return

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: self.client.cancel_order(
                category=self.category,
                symbol=symbol,       # <--- ИСПОЛЬЗУЕМ АРГУМЕНТ
                orderId=order_id
            ))
            logger.info(f"🗑️ CANCELLED: {order_id} on {symbol}")
        except Exception as e:
            # [FIX] Если ошибка "Order not exists" (110001) - это не Error, это Info
            str_e = str(e)
            if "110001" in str_e or "Order not exists" in str_e:
                logger.info(f"ℹ️ Cancel skipped (Order gone): {order_id}")
            else:
                logger.error(f"❌ Cancel Failed: {e}")

    # [FIX] Добавлен аргумент symbol
    async def get_position(self, symbol: str) -> float:
        if self.read_only:
            return 0.0

        try:
            loop = asyncio.get_running_loop()
            # Передаем symbol в запрос
            resp = await loop.run_in_executor(None, lambda: self.client.get_positions(
                category=self.category,
                symbol=symbol        # <--- ИСПОЛЬЗУЕМ АРГУМЕНТ
            ))
            # Список может быть пустым или содержать позицию
            for pos in resp['result']['list']:
                # Bybit может вернуть список, фильтруем нужный символ на всякий случай
                if pos['symbol'] == symbol:
                    size = float(pos['size'])
                    side = pos['side']
                    if size > 0:
                        return size if side == 'Buy' else -size
            return 0.0
        except Exception as e:
            logger.error(f"❌ Position Check Failed: {e}")
            return 0.0