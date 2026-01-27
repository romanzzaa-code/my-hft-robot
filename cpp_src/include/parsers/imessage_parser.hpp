// hft_core/include/parsers/imessage_parser.hpp
#pragma once
#include <string>
#include <vector>
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
    
    // CHANGE: TickData& -> std::vector<TickData>&
    virtual ParseResultType parse(
        const std::string& payload, 
        std::vector<TickData>& out_ticks, 
        OrderBookSnapshot& out_depth,
        TickerData& out_ticker,
        ExecutionData& out_exec 
    ) = 0;
};