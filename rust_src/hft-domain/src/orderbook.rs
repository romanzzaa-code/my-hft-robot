use std::collections::BTreeMap;
use rust_decimal::Decimal;
use crate::{Price, Qty, Side};

#[derive(Debug, Clone, Default)]
pub struct LocalOrderBook {
    pub bids: BTreeMap<Price, Qty>, // Sorted descending (highest first) handled by logic
    pub asks: BTreeMap<Price, Qty>, // Sorted ascending (lowest first) handled by logic
}

impl LocalOrderBook {
    pub fn new() -> Self {
        Self {
            bids: BTreeMap::new(),
            asks: BTreeMap::new(),
        }
    }

    pub fn apply_update(&mut self, bids: Vec<(Price, Qty)>, asks: Vec<(Price, Qty)>, is_snapshot: bool) {
        if is_snapshot {
            self.bids.clear();
            self.asks.clear();
        }

        for (p, q) in bids {
            if q.is_zero() {
                self.bids.remove(&p);
            } else {
                self.bids.insert(p, q);
            }
        }

        for (p, q) in asks {
            if q.is_zero() {
                self.asks.remove(&p);
            } else {
                self.asks.insert(p, q);
            }
        }
    }

    pub fn get_best(&self, side: Side) -> Option<Price> {
        match side {
            Side::Buy => self.bids.keys().next_back().cloned(), // BTreeMap is ascending, so next_back is max
            Side::Sell => self.asks.keys().next().cloned(),     // next is min
        }
    }

    pub fn get_volume(&self, side: Side, price: Price) -> Qty {
        match side {
            Side::Buy => self.bids.get(&price).cloned().unwrap_or(Decimal::ZERO),
            Side::Sell => self.asks.get(&price).cloned().unwrap_or(Decimal::ZERO),
        }
    }

    pub fn get_background_volume(&self) -> Decimal {
        if self.bids.is_empty() || self.asks.is_empty() {
            return Decimal::ZERO;
        }

        // Get levels 2-11 (10 levels)
        let bid_volumes: Vec<Qty> = self.bids.values().rev().skip(1).take(10).cloned().collect();
        let ask_volumes: Vec<Qty> = self.asks.values().skip(1).take(10).cloned().collect();

        let mut all_vols = Vec::with_capacity(20);
        all_vols.extend(bid_volumes);
        all_vols.extend(ask_volumes);

        if all_vols.is_empty() {
            return Decimal::ZERO;
        }

        let sum: Decimal = all_vols.iter().sum();
        sum / Decimal::from(all_vols.len())
    }
}
