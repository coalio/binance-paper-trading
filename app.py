# Binance paper trading app so you can trade on paper and not lose real money

import logging
import sqlite3

from textual.app import App, ComposeResult
from textual.containers import Vertical, Horizontal, VerticalScroll
from ui import PriceDisplay, OrderForm, PositionTable, HistoryTable, OrderTable
from binance_service import BinanceService
from textual import on
from textual.widgets import DataTable, TabbedContent, TabPane
from textual.widgets import Select, Input
from ui.limit_dialog import LimitDialog
from textual import events

class BinancePriceApp(App):
    CSS_PATH = "app.tcss"
    SCREENS = {"limit": LimitDialog}

    def __init__(self, fetch_interval: float = 0.5) -> None:
        super().__init__()
        self.service = BinanceService()
        self.price_widget = PriceDisplay()
        self.order_form = OrderForm()
        self.fetch_interval = fetch_interval
        # State
        self.positions: list[dict] = []  # open positions
        self.history: list[dict] = []    # closed positions
        # Fees
        self.fee_rate_maker: float = 0.0002  # 0.02%
        self.fee_rate_taker: float = 0.0004  # 0.04%

        # Default to BTCUSDT because it's the one I mostly work with
        self.current_symbol = "BTCUSDT"

        self.orders: list[dict] = []   # limit orders waiting

        self._id_counter = 1

        # Database setup
        self.db_conn = sqlite3.connect("trades.db")
        self._prepare_database()

    def _prepare_database(self):
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

    def _load_history_from_db(self):
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
        # Find the next id in the history rows
        next_id = max([int(row["id"].split("-")[-1]) for row in self.history]) + 1
        value = f"{symbol}-{next_id}"
        self._id_counter = next_id
        return value

    def compose(self) -> ComposeResult:
        # Instantiate tables here so they are created within an active App context
        self.position_table = PositionTable()
        self.order_table = OrderTable()
        self.history_table = HistoryTable()

        pane_active = TabPane("Active", self.position_table, id="tab_active")
        pane_orders = TabPane("Orders", self.order_table, id="tab_orders")
        positions_tabs = TabbedContent(initial="tab_active", id="positions_tabs")

        # Inject panes before compose renders
        positions_tabs._tab_content = [pane_active, pane_orders]

        # store reference for later
        self.positions_tabs = positions_tabs

        yield Horizontal(
            Vertical(
                VerticalScroll(self.history_table, id="history"),  # history on top
                positions_tabs,  # positions and orders on bottom
                id="left_pane",
            ),
            Vertical(
                self.price_widget,
                self.order_form,
                id="right_pane",
            ),
            id="root",
        )

    async def on_mount(self) -> None:
        # load persisted trades
        self._load_history_from_db()
        self.history_table.update_history(self.history)
        # Fetch symbols asynchronously (separate method with retries)
        await self.fetch_symbols()
        # refresh symbol list every 10 minutes in background
        self.set_interval(600, self.fetch_symbols, pause=False)
        await self.fetch_and_update()
        self.set_interval(self.fetch_interval, self.fetch_and_update)
        # initialize orders tab reference after layout is mounted
        self._refresh_orders_tab_label()

    async def fetch_symbols(self) -> None:
        """Retrieve top USDT pairs and update dropdown. Retry on errors."""
        try:
            symbols = await self.service.get_top_usdt_pairs(limit=30)
            if not symbols:
                self.log("No symbols fetched", level="error")
                return

            previous = self.current_symbol

            if previous not in symbols:
                self.current_symbol = symbols[0]

            # We must update the symbols in the order form so let's do that here
            self.order_form.update_symbols(symbols, self.current_symbol)
            self.order_form.set_coin_label_from_symbol(self.current_symbol)
            self.log(f"Symbol list updated (count={len(symbols)})", level="info")

        except Exception as exc:
            self.log(f"Failed to fetch symbols: {exc}", level="error")

    async def fetch_and_update(self) -> None:
        try:
            last, mark = await self.service.get_symbol_prices(self.current_symbol)
            self.price_widget.update_prices(last, mark)

            # Update PnL for open positions every time we fetch the latest prices
            try:
                mark_f = float(mark)
                last_f = float(last)
            except ValueError:
                mark_f = None
                last_f = None

            # Check limit orders to see if they're fulfilled
            if last_f is not None and self.orders:
                filled: list[dict] = []
                for o in self.orders:
                    trigger = (last_f <= o["limit_price"] if o["side"] == "BUY" else last_f >= o["limit_price"])
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
                        exit_fee = o["limit_price"] * pos["size"] * self.fee_rate_maker
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
                        self.history_table.update_history(self.history)
                        self.log(f"Position {pos['id']} closed via limit order. Net PnL {net_pnl}")
                        # persist
                        self._insert_trade(closed)
                    else:
                        # Regular entry limit order becomes active position
                        pos_id = o["id"]
                        open_fee = o["limit_price"] * o["size"] * self.fee_rate_maker
                        pos = {
                            "id": pos_id,
                            "symbol": o["symbol"],
                            "side": o["side"],
                            "size": o["size"],
                            "entry": o["limit_price"],
                            "liquidation": "-",
                            "breakeven": o["limit_price"] * (1 + self.fee_rate_maker*2) if o["side"] == "BUY" else o["limit_price"] * (1 - self.fee_rate_maker*2),
                            "open_fee": open_fee,
                            "pnl": 0,
                            "net_pnl": - open_fee,
                        }
                        self.positions.append(pos)
                        self.log(f"Limit order filled -> active position {pos_id}")

                # update tables after processing
                self.order_table.update_orders(self.orders)
                self.position_table.update_positions(self.positions)
                self._refresh_orders_tab_label()

            if mark_f is not None:
                for pos in self.positions:
                    side_mult = 1 if pos["side"] == "BUY" else -1
                    pos["pnl"] = (mark_f - pos["entry"]) * float(pos["size"]) * side_mult
                    # Net PnL after closing fee
                    open_fee = pos["open_fee"]
                    close_fee = mark_f * float(pos["size"]) * self.fee_rate_taker
                    pos["net_pnl"] = pos["pnl"] - open_fee - close_fee

                self.position_table.update_positions(self.positions)

            # Always refresh order table
            self.order_table.update_orders(self.orders)
            self._refresh_orders_tab_label()
        except Exception as exc:
            self.log(f"Error fetching prices: {exc}", level="error")
            self.price_widget.update(f"[red]error fetching prices[/red]\n{exc}")

    @on(OrderForm.Submit)
    async def order_submitted(self, message: OrderForm.Submit) -> None:
        """Handle order form submissions."""
        # Determine entry price
        symbol = message.symbol or self.current_symbol
        if message.price is not None:
            entry = float(message.price)
        else:
            # fetch current mark price
            _, mark = await self.service.get_symbol_prices(symbol)
            try:
                entry = float(mark)
            except ValueError:
                self.log("Invalid mark price", level="error")
                return

        position_id = self._next_id(symbol)
        qty_value = float(message.qty)
        if message.qty_mode == "USDT":
            size = qty_value / entry if entry != 0 else 0.0
        else:
            size = qty_value

        if message.price is not None:  # limit order (maker fee when filled)
            order = {
                "id": position_id,
                "symbol": symbol,
                "side": message.side,
                "size": size,
                "limit_price": float(message.price),
            }
            self.orders.append(order)
            self.order_table.update_orders(self.orders)
            self.log(f"Placed limit order {position_id}: {message.side} {size} {symbol} @ {message.price}")
            self._refresh_orders_tab_label()
            return

        open_fee = entry * size * self.fee_rate_taker  # market order pays taker fee immediately

        # Create the position object
        # TODO: refactor this into a class or something
        pos = {
            "id": position_id,
            "symbol": symbol,
            "side": message.side,
            "size": size,
            "entry": entry,
            "liquidation": "-",  # placeholder
            "breakeven": entry * (1 + self.fee_rate_taker*2) if message.side == "BUY" else entry * (1 - self.fee_rate_taker*2),
            "pnl": 0,
            "open_fee": open_fee,
            "net_pnl": - open_fee,  # initial net pnl is negative open fee
        }

        self.positions.append(pos)
        self.position_table.update_positions(self.positions)
        self.log(
            f"Added position {position_id}: {message.side} {size} {symbol} @ {entry} (from {message.qty} {message.qty_mode})"
        )
        self._refresh_orders_tab_label()

    @on(DataTable.CellSelected)
    async def position_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        """Handle clicks on the Close cell to close positions."""
        if event.data_table is not self.position_table:
            return
        # Determine which column
        col_key = list(self.position_table.columns.keys())[event.coordinate.column]
        col_name = self.position_table.columns[col_key].label.plain
        row_key_obj = event.cell_key.row_key
        row_key = row_key_obj.value if hasattr(row_key_obj, "value") else str(row_key_obj)
        pos = next((p for p in self.positions if p["id"] == row_key), None)
        if not pos:
            return

        if col_name == "Limit":
            target = pos.get("target_price")
            if target is None:
                self.push_screen(LimitDialog(row_key), callback=lambda price, pid=row_key: self._process_limit_result(pid, price))
                return

        if col_name != "Close":
            return

        # fetch current mark price for PnL calc
        _, mark = await self.service.get_symbol_prices(symbol=pos["symbol"])
        try:
            mark_f = float(mark)
        except ValueError:
            self.log("Invalid mark price", level="error")
            return

        side_mult = 1 if pos["side"] == "BUY" else -1
        pnl = (mark_f - pos["entry"]) * pos["size"] * side_mult
        open_fee = pos["open_fee"]
        close_fee = mark_f * float(pos["size"]) * self.fee_rate_taker
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
        # remove from positions
        self.positions = [p for p in self.positions if p["id"] != row_key]
        self.position_table.update_positions(self.positions)

        self.history.append(closed)
        self.history_table.update_history(self.history)
        # persist
        self._insert_trade(closed)

        # cancel any pending exit orders linked to this position
        before = len(self.orders)
        self.orders = [o for o in self.orders if o.get("position_id") != pos["id"]]
        if len(self.orders) != before:
            self.order_table.update_orders(self.orders)
            self._refresh_orders_tab_label()
            self.log(f"Cancelled {before-len(self.orders)} linked exit orders for position {pos['id']}")

        self.log(f"Closed position {row_key} net PnL {net_pnl}")

    @on(Select.Changed)
    def symbol_select_changed(self, event: Select.Changed) -> None:
        if getattr(self.order_form, "symbol_select", None) is event.select:
            if event.value and event.value is not Select.BLANK:
                self.current_symbol = str(event.value)
                self.order_form.set_coin_label_from_symbol(self.current_symbol)
                self.call_later(self.fetch_and_update)

    def _refresh_orders_tab_label(self):
        """Update the Orders tab label with current count."""
        if not hasattr(self, "orders_tab"):
            try:
                from textual.widgets._tabbed_content import ContentTab
                self.orders_tab = self.query_one(f"#{ContentTab.add_prefix('tab_orders')}", ContentTab)
            except Exception:
                return
        count = len(self.orders)
        new_label = f"Orders ({count})" if count else "Orders"
        if self.orders_tab.label.plain != new_label:
            self.orders_tab.label = new_label

    @on(DataTable.CellSelected)
    def order_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        """Handle cancel action in orders table."""
        if event.data_table is not self.order_table:
            return
        col_key = list(self.order_table.columns.keys())[event.coordinate.column]
        col_name = self.order_table.columns[col_key].label.plain
        if col_name != "Cancel":
            return

        row_key_obj = event.cell_key.row_key
        row_key = row_key_obj.value if hasattr(row_key_obj, "value") else str(row_key_obj)

        # Remove order with id = row_key
        before = len(self.orders)
        self.orders = [o for o in self.orders if o["id"] != row_key]
        if len(self.orders) != before:
            self.order_table.update_orders(self.orders)
            self._refresh_orders_tab_label()
            self.log(f"Cancelled order {row_key}")

    def _process_limit_result(self, position_id: str, price: float | None) -> None:
        if price is None:
            return  # dialog cancelled
        pos = next((p for p in self.positions if p["id"] == position_id), None)
        if not pos:
            return
        # set target price
        pos["target_price"] = price
        # create linked exit order
        order_id = self._next_id(pos["symbol"])
        side = "SELL" if pos["side"] == "BUY" else "BUY"
        order = {
            "id": order_id,
            "symbol": pos["symbol"],
            "side": side,
            "size": pos["size"],
            "limit_price": price,
            "position_id": position_id,
        }
        self.orders.append(order)
        self.order_table.update_orders(self.orders)
        self.position_table.update_positions(self.positions)
        self._refresh_orders_tab_label()
        self.log(f"Exit limit order {order_id} placed for position {position_id} @ {price}")

    @on(events.ScreenResume)
    def _on_screen_resume(self, _: events.ScreenResume) -> None:
        self.set_focus(self.position_table)

    def _insert_trade(self, trade: dict):
        cur = self.db_conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO trades (id,symbol,side,size,entry,close,net_pnl) VALUES (?,?,?,?,?,?,?)",
            (trade["id"], trade["symbol"], trade["side"], trade["size"], trade["entry"], trade["close"], trade["net_pnl"]),
        )
        self.db_conn.commit()

if __name__ == "__main__":
    BinancePriceApp().run()
