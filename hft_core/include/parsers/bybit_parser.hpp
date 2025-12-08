#pragma once
#include "imessage_parser.hpp"
#include <simdjson.h> // Нужно для объекта парсера

class BybitParser : public IMessageParser {
public:
    // Только объявление функции (в конце точка с запятой)
    bool parse(const std::string& payload, TickData& out_tick) override;

private:
    // Экземпляр парсера храним внутри класса, чтобы не пересоздавать его каждый раз
    simdjson::ondemand::parser parser_; 
};