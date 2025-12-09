// hft_core/include/entities/market_depth.hpp
#pragma once
#include <string>
#include <vector>

// Легковесная структура для одного уровня цены
struct PriceLevel {
    double price;
    double quantity;
};

// Снимок стакана (Snapshot)
struct OrderBookSnapshot {
    std::string symbol;
    long long timestamp;      // Время биржи (exchange timestamp)
    long long local_timestamp; // Время получения (local timestamp)
    std::vector<PriceLevel> bids;
    std::vector<PriceLevel> asks;
    bool is_snapshot;         // true = полный снимок, false = дельта (на будущее)
};