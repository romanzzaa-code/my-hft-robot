#pragma once
#include <string>

struct ExecutionData {
    std::string symbol;
    std::string side;
    std::string order_id;
    std::string exec_type;
    
    // Поля, которые заполняет парсер
    double exec_price; 
    double exec_qty;
    bool is_maker;
    long long timestamp;

    // Оставим для совместимости (если main ссылается)
    double price;
    double qty;
};