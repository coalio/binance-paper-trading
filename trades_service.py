import sqlite3
from typing import List, Dict, Tuple, Optional
from binance_service import BinanceService
import secrets

class TradesService:
    def __init__(self) -> None:
        self.binance = BinanceService()
        # State
        self.positions: List[Dict] = []  # open positions
        self.history: List[Dict] = []    # closed positions
        self.orders: List[Dict] = []     # limit orders waiting
        self.current_symbol = "BTCUSDT"  # Default to BTCUSDT
        
        # Default fees (will be overridden per symbol when orders are created)
        self.fee_rate_maker: float = 0.0002  # 0.02%
        self.fee_rate_taker: float = 0.0004  # 0.04%
        
        self._id_counter = 1
        
        # Database setup
        self.db_conn = sqlite3.connect("trades.db")
        self._prepare_database()
        self._load_history_from_db()

    def _prepare_database(self) -> None:
        cur = self.db_conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY,
                symbol TEXT,
                side TEXT,
                size REAL,
                entry REAL,
                close REAL,
                net_pnl REAL,
                ts DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.db_conn.commit()

    def _load_history_from_db(self) -> None:
        cur = self.db_conn.cursor()
        for row in cur.execute("SELECT id,symbol,side,size,entry,close,net_pnl FROM trades ORDER BY ts"):
            self.history.append({
                "id": row[0],
                "symbol": row[1],
                "side": row[2],
                "size": row[3],
                "entry": row[4],
                "close": row[5],
                "net_pnl": row[6],
            })

    def _next_id(self, symbol: str) -> str:
        # Generate a unique 6-digit hexadecimal hash (24-bit randomness)
        # Keep trying until we get an id that isn't already in use
        existing_ids = {
            *(row["id"] for row in self.history),
            *(p["id"] for p in self.positions),
            *(o["id"] for o in self.orders),
        }

        while True:
            rand_hash = secrets.token_hex(3)  # 6 hex chars
            candidate = f"{symbol}-{rand_hash}"
            if candidate not in existing_ids:
                return candidate

    def _insert_trade(self, trade: Dict) -> None:
        cur = self.db_conn.cursor()
        cur.execute(
            """
            INSERT INTO trades (id, symbol, side, size, entry, close, net_pnl)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade["id"],
                trade["symbol"],
                trade["side"],
                trade["size"],
                trade["entry"],
                trade["close"],
                trade["net_pnl"],
            ),
        )
        self.db_conn.commit()

    async def get_top_symbols(self, limit: int = 30) -> List[str]:
        """Retrieve top USDT pairs."""
        return await self.binance.get_top_usdt_pairs(limit=limit)

    async def get_current_prices(self) -> Tuple[str, str]:
        """Get current last and mark prices for the current symbol."""
        return await self.binance.get_symbol_prices(self.current_symbol)

    def set_current_symbol(self, symbol: str) -> None:
        """Update the current trading symbol."""
        self.current_symbol = symbol

    def get_current_symbol(self) -> str:
        """Get the current trading symbol."""
        return self.current_symbol

    def get_positions(self) -> List[Dict]:
        """Get all open positions."""
        return self.positions

    def get_history(self) -> List[Dict]:
        """Get trade history."""
        return self.history

    def get_orders(self) -> List[Dict]:
        """Get all pending limit orders."""
        return self.orders

    async def submit_market_order(self, symbol: str, side: str, size: float, price: Optional[float] = None) -> Dict:
        """Submit a new market order."""
        if price is None:
            # fetch current mark price
            _, mark = await self.binance.get_symbol_prices(symbol)
            try:
                price = float(mark)
            except ValueError:
                raise ValueError("Could not determine entry price")

        # Fetch up-to-date commission rates for this symbol (taker applies to market order)
        maker_fee_rate, taker_fee_rate = await self.binance.get_symbol_commission_rates(symbol)

        pos_id = self._next_id(symbol)
        open_fee = price * size * taker_fee_rate

        position = {
            "id": pos_id,
            "symbol": symbol,
            "side": side,
            "size": size,
            "entry": price,
            "liquidation": "-",
            "breakeven": price * (1 + maker_fee_rate*2) if side == "BUY" else price * (1 - maker_fee_rate*2),
            "open_fee": open_fee,
            "pnl": 0,
            "net_pnl": -open_fee,
            "maker_fee_rate": maker_fee_rate,
            "taker_fee_rate": taker_fee_rate,
        }

        self.positions.append(position)
        return position

    def submit_limit_order(self, symbol: str, side: str, size: float, limit_price: float, position_id: Optional[str] = None) -> Dict:
        """Submit a new limit order."""
        order_id = self._next_id(symbol) if position_id is None else f"{position_id}-exit"
        order = {
            "id": order_id,
            "symbol": symbol,
            "side": side,
            "size": size,
            "limit_price": limit_price,
        }
        if position_id:
            order["position_id"] = position_id

        self.orders.append(order)
        return order

    def cancel_order(self, order_id: str) -> None:
        """Cancel a pending limit order."""
        self.orders = [o for o in self.orders if o["id"] != order_id]

    async def update_positions_pnl(self, mark_price: float) -> None:
        """Update PnL calculations for all open positions."""
        for pos in self.positions:
            side_mult = 1 if pos["side"] == "BUY" else -1
            pos["pnl"] = (mark_price - pos["entry"]) * float(pos["size"]) * side_mult
            # Net PnL after closing fee
            open_fee = pos["open_fee"]
            taker_fee_rate = pos.get("taker_fee_rate", self.fee_rate_taker)
            close_fee = mark_price * float(pos["size"]) * taker_fee_rate
            pos["net_pnl"] = pos["pnl"] - open_fee - close_fee

    async def check_and_fill_limit_orders(self, last_price: float) -> List[Dict]:
        """Check if any limit orders should be filled at the current price."""
        filled: List[Dict] = []
        for o in self.orders:
            trigger = (last_price <= o["limit_price"] if o["side"] == "BUY" else last_price >= o["limit_price"])
            if trigger:
                filled.append(o)

        for o in filled:
            self.orders.remove(o)
            if "position_id" in o:
                # Exit order: close matching position
                pos = next((p for p in self.positions if p["id"] == o["position_id"]), None)
                if not pos:
                    continue
                side_mult = 1 if pos["side"] == "BUY" else -1
                pnl = (o["limit_price"] - pos["entry"]) * pos["size"] * side_mult
                maker_fee_rate = pos.get("maker_fee_rate", self.fee_rate_maker)
                exit_fee = o["limit_price"] * pos["size"] * maker_fee_rate
                net_pnl = pnl - pos["open_fee"] - exit_fee
                closed = {
                    "id": pos["id"],
                    "symbol": pos["symbol"],
                    "side": pos["side"],
                    "size": pos["size"],
                    "entry": pos["entry"],
                    "close": o["limit_price"],
                    "net_pnl": net_pnl,
                }
                self.positions = [p for p in self.positions if p["id"] != pos["id"]]
                self.history.append(closed)
                self._insert_trade(closed)
            else:
                # Regular entry limit order becomes active position
                pos_id = o["id"]
                # Fetch commission rates for this symbol (maker fee applies here)
                maker_fee_rate, taker_fee_rate = await self.binance.get_symbol_commission_rates(o["symbol"])
                open_fee = o["limit_price"] * o["size"] * maker_fee_rate
                pos = {
                    "id": pos_id,
                    "symbol": o["symbol"],
                    "side": o["side"],
                    "size": o["size"],
                    "entry": o["limit_price"],
                    "liquidation": "-",
                    "breakeven": o["limit_price"] * (1 + maker_fee_rate*2) if o["side"] == "BUY" else o["limit_price"] * (1 - maker_fee_rate*2),
                    "open_fee": open_fee,
                    "pnl": 0,
                    "net_pnl": - open_fee,
                    "maker_fee_rate": maker_fee_rate,
                    "taker_fee_rate": taker_fee_rate,
                }
                self.positions.append(pos)

        return filled 

    async def close_position_market(self, position_id: str) -> Optional[Dict]:
        """Close a position at current market price and return the closed trade dict."""
        pos = next((p for p in self.positions if p["id"] == position_id), None)
        if not pos:
            return None

        # Fetch current market price
        _, mark = await self.binance.get_symbol_prices(pos["symbol"])
        try:
            mark_f = float(mark)
        except ValueError:
            # Can't close because price is invalid
            return None

        side_mult = 1 if pos["side"] == "BUY" else -1
        pnl = (mark_f - pos["entry"]) * pos["size"] * side_mult
        open_fee = pos["open_fee"]
        taker_fee_rate = pos.get("taker_fee_rate", self.fee_rate_taker)
        close_fee = mark_f * pos["size"] * taker_fee_rate
        net_pnl = pnl - open_fee - close_fee

        closed = {
            "id": pos["id"],
            "symbol": pos["symbol"],
            "side": pos["side"],
            "size": pos["size"],
            "entry": pos["entry"],
            "close": mark_f,
            "net_pnl": net_pnl,
        }

        # Remove position
        self.positions = [p for p in self.positions if p["id"] != position_id]
        # Add to history
        self.history.append(closed)
        # Persist
        self._insert_trade(closed)

        # Remove any linked exit orders
        self.orders = [o for o in self.orders if o.get("position_id") != position_id]

        return closed 