#pragma once
#include <string>
#include "../entities/tick_data.hpp"
#include "../entities/market_depth.hpp"
#include "../entities/Ticker_Data.hpp"

// Тип сообщения, который вернул парсер
enum class ParseResultType {
    None,
    Trade,
    Depth,
    Ticker
};

class IMessageParser {
public:
    virtual ~IMessageParser() = default;
    
    virtual ParseResultType parse(
        const std::string& payload, 
        TickData& out_tick, 
        OrderBookSnapshot& out_depth,
        TickerData& out_ticker
    ) = 0;
};