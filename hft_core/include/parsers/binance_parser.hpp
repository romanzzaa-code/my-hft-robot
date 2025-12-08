#pragma once

#include "entities/tick_data.hpp"  // Подключаем структуру TickData
#include "imessage_parser.hpp"  // Подключаем интерфейс
#include <simdjson.h>  // Для парсинга JSON

class BinanceParser : public IMessageParser {
public:
    bool parse(const std::string& payload, TickData& out_tick) override;

private:
    simdjson::ondemand::parser parser_instance;  // Экземпляр парсера
};