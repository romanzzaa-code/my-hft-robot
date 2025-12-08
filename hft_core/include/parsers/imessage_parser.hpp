#pragma once
#include <string_view>
#include <optional>
#include "../entities/tick_data.hpp" // Подключаем наши типы

class IMessageParser {
public:
    virtual ~IMessageParser() = default;
    
    // Возвращает true, если парсинг успешен и это торговый тик
    virtual bool parse(const std::string& payload, TickData& out_tick) = 0;
};