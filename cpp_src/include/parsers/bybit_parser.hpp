#pragma once
#include "imessage_parser.hpp"
#include <simdjson.h>

class BybitParser : public IMessageParser {
public:
    // Обновляем сигнатуру override метода
    ParseResultType parse(
        const std::string& payload, 
        TickData& out_tick, 
        OrderBookSnapshot& out_depth,
        TickerData& out_ticker,
        ExecutionData& out_exec // <--- Добавили
    ) override;

private:
    simdjson::ondemand::parser parser_;
};