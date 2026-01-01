#pragma once
#include <string>
#include "../entities/tick_data.hpp"
#include "../entities/market_depth.hpp"
#include "../entities/ticker_data.hpp"
#include "../entities/execution_data.hpp" 

enum class ParseResultType {
    None,
    Trade,
    Depth,
    Ticker,
    Execution 
};

class IMessageParser {
public:
    virtual ~IMessageParser() = default;
    
    virtual ParseResultType parse(
        const std::string& payload, 
        TickData& out_tick, 
        OrderBookSnapshot& out_depth,
        TickerData& out_ticker,
        ExecutionData& out_exec 
    ) = 0;
};