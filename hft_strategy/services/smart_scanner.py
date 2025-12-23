# hft_strategy/services/smart_scanner.py
import asyncio
import logging
from typing import List, Dict, Optional
from hft_strategy.services.instrument_provider import BybitInstrumentProvider
from hft_strategy.infrastructure.execution import BybitExecutionHandler

logger = logging.getLogger("SMART_SCANNER")

class SmartMarketSelector:
    def __init__(self, executor: BybitExecutionHandler):
        self.provider = BybitInstrumentProvider()
        self.executor = executor

    async def _fetch_tickers_snapshot(self) -> List[Dict]:
        """
        Получаем "сырой" список тикеров с биржи для фильтрации по обороту.
        Используем прямой доступ к клиенту pybit внутри executor'а.
        """
        try:
            # Выполняем блокирующий запрос в отдельном потоке
            resp = await asyncio.to_thread(
                self.executor.client.get_tickers, 
                category="linear"
            )
            return resp['result']['list']
        except Exception as e:
            logger.error(f"Failed to fetch tickers: {e}")
            return []

    async def scan_and_select(self, top_n=5) -> List[str]:
        """
        Основной метод воронки (Funnel):
        Все монеты -> Фильтр CopyTrading -> Топ по обороту -> Топ по NATR
        """
        logger.info("🔍 Starting Smart Scan Cycle...")
        
        # 1. Получаем список пар, разрешенных для CopyTrading (без BTC/ETH)
        copy_trading_pairs = await self.provider.get_active_copytrading_symbols()
        if not copy_trading_pairs:
            logger.warning("⚠️ No copytrading pairs found.")
            return []
        
        copy_set = set(copy_trading_pairs)

        # 2. Получаем рыночные данные (Оборот 24ч) по ВСЕМ монетам
        tickers = await self._fetch_tickers_snapshot()
        
        candidates = []
        for t in tickers:
            sym = t['symbol']
            # Фильтр 1: Только разрешенные монеты
            if sym not in copy_set: continue
            
            turnover = float(t.get('turnover24h', 0))
            # Фильтр 2: Оборот > 1M USDT (защита от неликвида)
            if turnover < 1_000_000: 
                continue
                
            candidates.append({
                'symbol': sym,
                'turnover': turnover,
                'price': float(t['lastPrice'])
            })

        # 3. Берем Топ-20 самых оборотистых для тяжелого анализа
        # (Запрашивать свечи для 200 монет слишком долго и дорого по лимитам)
        candidates.sort(key=lambda x: x['turnover'], reverse=True)
        top_candidates = candidates[:20]
        
        logger.info(f"📊 Analyzing volatility (NATR) for Top {len(top_candidates)} liquid pairs...")

        sem = asyncio.Semaphore(10)

        async def protected_analyze(c):
            async with sem:
                return await self._analyze_volatility(c)

        # 4. Считаем NATR параллельно
        tasks = [protected_analyze(c) for c in top_candidates]
        results = await asyncio.gather(*tasks)
        
        # Очищаем от неудачных запросов (None)
        scored_candidates = [res for res in results if res is not None]

        # 5. Финальный отбор: сортируем по NATR (волатильности)
        scored_candidates.sort(key=lambda x: x['natr'], reverse=True)
        
        final_list = [x['symbol'] for x in scored_candidates[:top_n]]
        
        logger.info(f"🏆 Selected Top {top_n} Targets:")
        for i, item in enumerate(scored_candidates[:top_n], 1):
            logger.info(f"   {i}. {item['symbol']} | NATR: {item['natr']:.2f}% | Vol: ${item['turnover']/1e6:.1f}M")
            
        return final_list

    async def _analyze_volatility(self, candidate: Dict) -> Optional[Dict]:
        """
        Запрашивает свечи и считает NATR (Normalized ATR).
        NATR показывает волатильность в процентах, что позволяет сравнивать разные монеты.
        """
        try:
            # Запрашиваем 20 свечей таймфрейма 5 минут
            # fetch_ohlc возвращает [ {h, l, c}, ... ] (от новых к старым, или наоборот - зависит от реализации,
            # но для ATR нам важна разница, порядок не так критичен, главное консистентность)
            klines = await self.executor.fetch_ohlc(candidate['symbol'], interval="5", limit=20)
            
            if len(klines) < 10: 
                return None
            
            # Расчет ATR (Average True Range)
            trs = []
            # В Bybit API [0] - это текущая (незакрытая) или последняя свеча.
            # Проходим по списку. klines[i] - текущая, klines[i+1] - предыдущая.
            for i in range(len(klines) - 1):
                high = klines[i]['h']
                low = klines[i]['l']
                prev_close = klines[i+1]['c']
                
                # True Range = Max(H-L, |H-Cp|, |L-Cp|)
                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                trs.append(tr)
            
            if not trs: 
                return None
            
            atr = sum(trs) / len(trs)
            price = candidate['price']
            
            # NATR = (ATR / Price) * 100%
            # Это дает нам понимание, на сколько % ходит цена за 5 минут в среднем
            if price == 0: return None
            
            candidate['natr'] = (atr / price) * 100
            return candidate
            
        except Exception as e:
            # Логируем как warning, чтобы не засорять эфир, если одна монета отвалилась
            logger.warning(f"⚠️ NATR calc failed for {candidate['symbol']}: {e}")
            return None