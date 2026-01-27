#pragma once
#include "imessage_parser.hpp"
#include <simdjson.h>
#include <vector>

class BinanceParser : public IMessageParser {
public:
    // Обновляем сигнатуру метода, чтобы она соответствовала интерфейсу IMessageParser
    ParseResultType parse(
        const std::string& payload, 
        std::vector<TickData>& out_ticks,
        OrderBookSnapshot& out_depth,
        TickerData& out_ticker,
        ExecutionData& out_exec
    ) override;

private:
    simdjson::ondemand::parser parser_instance;
};