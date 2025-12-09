#pragma once

#include "entities/tick_data.hpp"
#include "entities/market_depth.hpp" // <-- Добавляем
#include "imessage_parser.hpp"
#include <simdjson.h>

class BinanceParser : public IMessageParser {
public:
    // Обновленная сигнатура (override)
    ParseResultType parse(const std::string& payload, TickData& out_tick, OrderBookSnapshot& out_depth) override;

private:
    simdjson::ondemand::parser parser_instance;
};