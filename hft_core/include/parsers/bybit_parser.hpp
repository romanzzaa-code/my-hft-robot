#pragma once
#include "imessage_parser.hpp"
#include <simdjson.h>

class BybitParser : public IMessageParser {
public:
    // Implementation of the unified parsing interface
    ParseResultType parse(const std::string& payload, TickData& out_tick, OrderBookSnapshot& out_depth) override;

private:
    simdjson::ondemand::parser parser_;
};