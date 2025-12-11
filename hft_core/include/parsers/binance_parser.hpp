#pragma once
#include "imessage_parser.hpp"
#include <simdjson.h>

class BinanceParser : public IMessageParser {
public:
    // Обновляем сигнатуру, добавляем TickerData&
    ParseResultType parse(
        const std::string& payload, 
        TickData& out_tick, 
        OrderBookSnapshot& out_depth,
        TickerData& out_ticker // <--- Добавили, чтобы соответствовать базе
    ) override;

private:
    simdjson::ondemand::parser parser_instance;
};