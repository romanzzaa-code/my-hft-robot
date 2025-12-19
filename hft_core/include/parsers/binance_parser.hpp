#pragma once
#include "imessage_parser.hpp"
#include <simdjson.h>

class BinanceParser : public IMessageParser {
public:
    // Обновляем сигнатуру метода, чтобы она соответствовала интерфейсу IMessageParser
    ParseResultType parse(
        const std::string& payload, 
        TickData& out_tick, 
        OrderBookSnapshot& out_depth,
        TickerData& out_ticker,
        ExecutionData& out_exec // <--- Добавили обязательный аргумент
    ) override;

private:
    simdjson::ondemand::parser parser_instance;
};