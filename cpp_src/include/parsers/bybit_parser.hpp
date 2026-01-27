#pragma once
#include "imessage_parser.hpp"
#include <simdjson.h>
#include <vector>

class BybitParser : public IMessageParser {
public:
    // Обновляем сигнатуру override метода
    ParseResultType parse(
        const std::string& payload, 
        std::vector<TickData>& out_ticks,
        OrderBookSnapshot& out_depth,
        TickerData& out_ticker,
        ExecutionData& out_exec
    ) override;

private:
    simdjson::ondemand::parser parser_;
};