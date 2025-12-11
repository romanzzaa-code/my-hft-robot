# hft_strategy/services/instrument_provider.py
import aiohttp
import logging
from typing import List, Set

logger = logging.getLogger("INSTRUMENTS")

class BybitInstrumentProvider:
    """
    Служба разведки (Intelligence Service).
    Отвечает за получение списка инструментов, доступных для CopyTrading.
    """
    # Эндпоинт для получения инфо по инструментам
    BASE_URL = "https://api.bybit.com/v5/market/instruments-info"

    def __init__(self, exclude_symbols: Set[str] = None):
        # Черный список: Биткоин и Эфир (там нас съедят)
        self.exclude_symbols = exclude_symbols or {
            "BTCUSDT", "ETHUSDT", "BTC-PERP", "ETH-PERP"
        }

    async def get_active_copytrading_symbols(self) -> List[str]:
        """
        Делает запрос к Bybit и возвращает список тикеров (например, ['SOLUSDT', 'DOGEUSDT', ...]).
        """
        # Параметры запроса: категория linear (USDT фьючерсы) и статус Trading (активные)
        params = {
            "category": "linear",
            "limit": 1000, 
            "status": "Trading"
        }
        
        timeout = aiohttp.ClientTimeout(total=10)
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.BASE_URL, params=params) as resp:
                    if resp.status != 200:
                        logger.error(f"Bybit API Error: {resp.status}")
                        return []
                    
                    data = await resp.json()
                    
                    if data["retCode"] != 0:
                        logger.error(f"Bybit Logic Error: {data['retMsg']}")
                        return []
                    
                    # --- ЛОГИКА ФИЛЬТРАЦИИ ---
                    valid_symbols = []
                    
                    for item in data["result"]["list"]:
                        symbol = item["symbol"]
                        base_coin = item["baseCoin"]
                        quote_coin = item["quoteCoin"]
                        
                        # 1. Торгуем только к USDT
                        if quote_coin != "USDT":
                            continue
                            
                        # 2. Исключаем BTC и ETH (они в черном списке)
                        if base_coin in ["BTC", "ETH"] or symbol in self.exclude_symbols:
                            continue
                            
                        # 3. ПРОВЕРКА КОПИТРЕЙДИНГА
                        # Поле 'copyTrading' может принимать значения: 'none', 'both', 'uta_only', 'normal_only'
                        # Нам подходят все, кроме 'none' и пустых.
                        ct_flag = str(item.get("copyTrading", "none")).lower()
                        
                        if ct_flag not in ["both", "uta_only", "true", "1"]:
                            # Если монета не доступна для копитрейдинга — пропускаем
                            continue
                        
                        valid_symbols.append(symbol)
            
            logger.info(f"✅ Found {len(valid_symbols)} CopyTrading pairs (excluding BTC/ETH)")
            return valid_symbols

        except Exception as e:
            logger.error(f"Failed to fetch instruments: {e}")
            return []