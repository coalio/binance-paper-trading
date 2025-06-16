# Binance paper trading app so you can trade on paper and not lose real money

import logging

from textual.app import App, ComposeResult
from textual.containers import Vertical, Horizontal, VerticalScroll
from ui import PriceDisplay, OrderForm, PositionTable, HistoryTable
from binance_service import BinanceService
from textual import on
from textual.widgets import DataTable
from textual.widgets import Select

class BinancePriceApp(App):
    CSS_PATH = "app.tcss"

    def __init__(self, fetch_interval: float = 0.5) -> None:
        super().__init__()
        self.service = BinanceService()
        self.price_widget = PriceDisplay()
        self.order_form = OrderForm()
        self.fetch_interval = fetch_interval
        # State
        self.positions: list[dict] = []  # open positions
        self.history: list[dict] = []    # closed positions
        self.fee_rate: float = 0.0002    # maker fee (0.02%)
        self.current_symbol = "BTCUSDT"

    def compose(self) -> ComposeResult:
        # Instantiate tables here so they are created within an active App context
        self.position_table = PositionTable()
        self.history_table = HistoryTable()

        yield Horizontal(
            Vertical(
                VerticalScroll(self.position_table, id="open_positions"),
                VerticalScroll(self.history_table, id="history"),
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
        # Fetch symbols asynchronously (separate method with retries)
        await self.fetch_symbols()
        # refresh symbol list every 10 minutes in background
        self.set_interval(600, self.fetch_symbols, pause=False)
        await self.fetch_and_update()
        self.set_interval(self.fetch_interval, self.fetch_and_update)

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
            self.order_form.update_symbols(symbols, self.current_symbol)
            self.order_form.set_coin_label_from_symbol(self.current_symbol)
            self.log(f"Symbol list updated (count={len(symbols)})", level="info")
        except Exception as exc:
            self.log(f"Failed to fetch symbols: {exc}", level="error")

    async def fetch_and_update(self) -> None:
        try:
            last, mark = await self.service.get_symbol_prices(self.current_symbol)
            self.price_widget.update_prices(last, mark)
            # Update PnL for open positions
            try:
                mark_f = float(mark)
            except ValueError:
                mark_f = None
            if mark_f is not None:
                for pos in self.positions:
                    side_mult = 1 if pos["side"] == "BUY" else -1
                    pos["pnl"] = (mark_f - pos["entry"]) * float(pos["size"]) * side_mult
                    # Net PnL after closing fee
                    open_fee = pos["entry"] * float(pos["size"]) * self.fee_rate
                    close_fee = mark_f * float(pos["size"]) * self.fee_rate
                    pos["net_pnl"] = pos["pnl"] - open_fee - close_fee
                self.position_table.update_positions(self.positions)
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

        position_id = f"{symbol}-{len(self.positions)+len(self.history)+1}"
        qty_value = float(message.qty)
        if message.qty_mode == "USDT":
            size = qty_value / entry if entry != 0 else 0.0
        else:
            size = qty_value
        pos = {
            "id": position_id,
            "symbol": symbol,
            "side": message.side,
            "size": size,
            "entry": entry,
            "liquidation": "-",  # placeholder
            "breakeven": entry * (1 + self.fee_rate*2) if message.side == "BUY" else entry * (1 - self.fee_rate*2),
            "pnl": 0,
            "net_pnl": - entry * size * self.fee_rate * 2,  # initial net pnl is fees paid
        }
        self.positions.append(pos)
        self.position_table.update_positions(self.positions)
        self.log(
            f"Added position {position_id}: {message.side} {size} {symbol} @ {entry} (from {message.qty} {message.qty_mode})"
        )

    @on(DataTable.CellSelected)
    async def position_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        """Handle clicks on the Close cell to close positions."""
        if event.data_table is not self.position_table:
            return
        if str(event.value) != "Close":
            return

        # event.cell_key.row_key is a RowKey instance – get its string value
        row_key_obj = event.cell_key.row_key
        row_key = row_key_obj.value if hasattr(row_key_obj, "value") else str(row_key_obj)
        # find position
        pos = next((p for p in self.positions if p["id"] == row_key), None)
        if not pos:
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
        open_fee = pos["entry"] * pos["size"] * self.fee_rate
        close_fee = mark_f * pos["size"] * self.fee_rate
        net_pnl = pnl - open_fee - close_fee

        closed = {
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
        self.log(f"Closed position {row_key} net PnL {net_pnl}")

    @on(Select.Changed)
    def symbol_select_changed(self, event: Select.Changed) -> None:
        if getattr(self.order_form, "symbol_select", None) is event.select:
            if event.value and event.value is not Select.BLANK:
                self.current_symbol = str(event.value)
                self.order_form.set_coin_label_from_symbol(self.current_symbol)
                self.call_later(self.fetch_and_update)

if __name__ == "__main__":
    BinancePriceApp().run()
