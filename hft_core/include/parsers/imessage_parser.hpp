#pragma once
#include <string>
#include "../entities/tick_data.hpp"
#include "../entities/market_depth.hpp"

// Тип сообщения, который вернул парсер
enum class ParseResultType {
    None,
    Trade,
    Depth
};

class IMessageParser {
public:
    virtual ~IMessageParser() = default;
    
    // Единый метод парсинга. 
    // Возвращает тип найденного сообщения. 
    // Заполняет либо out_tick, либо out_depth.
    virtual ParseResultType parse(
        const std::string& payload, 
        TickData& out_tick, 
        OrderBookSnapshot& out_depth
    ) = 0;
};