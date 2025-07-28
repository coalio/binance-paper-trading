# Binance paper trading app so you can trade on paper and not lose real money

import logging
from textual.app import App, ComposeResult
from textual.containers import Vertical, Horizontal, VerticalScroll
from ui import PriceDisplay, OrderForm, PositionTable, HistoryTable, OrderTable
from textual import on
from textual.widgets import DataTable, TabbedContent, TabPane
from textual.widgets import Select, Input
from ui.limit_dialog import LimitDialog
from textual import events
from trades_service import TradesService

class BinancePriceApp(App):
    CSS_PATH = "app.tcss"
    SCREENS = {"limit": LimitDialog}

    def __init__(self, fetch_interval: float = 0.5) -> None:
        super().__init__()
        self.trades = TradesService()
        self.price_widget = PriceDisplay()
        self.order_form = OrderForm()
        self.fetch_interval = fetch_interval

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
        # Update history table with loaded trades
        self.history_table.update_history(self.trades.get_history())
        # Fetch symbols asynchronously
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
            symbols = await self.trades.get_top_symbols(limit=30)
            if not symbols:
                self.log("No symbols fetched", level="error")
                return

            current_symbol = self.trades.get_current_symbol()
            if current_symbol not in symbols:
                self.trades.set_current_symbol(symbols[0])
                current_symbol = symbols[0]

            # Update the symbols in the order form
            self.order_form.update_symbols(symbols, current_symbol)
            self.order_form.set_coin_label_from_symbol(current_symbol)
            self.log(f"Symbol list updated (count={len(symbols)})", level="info")

        except Exception as exc:
            self.log(f"Failed to fetch symbols: {exc}", level="error")

    async def fetch_and_update(self) -> None:
        try:
            last, mark = await self.trades.get_current_prices()
            self.price_widget.update_prices(last, mark)

            try:
                mark_f = float(mark)
                last_f = float(last)
            except ValueError:
                mark_f = None
                last_f = None

            # Check and fill limit orders if we have a valid last price
            if last_f is not None:
                filled_orders = await self.trades.check_and_fill_limit_orders(last_f)
                for order in filled_orders:
                    if "position_id" in order:
                        self.log(f"Position {order['position_id']} closed via limit order")
                    else:
                        self.log(f"Limit order filled -> active position {order['id']}")

            # Update PnL for open positions if we have a valid mark price
            if mark_f is not None:
                await self.trades.update_positions_pnl(mark_f)

            # Update all UI tables
            self.position_table.update_positions(self.trades.get_positions())
            self.order_table.update_orders(self.trades.get_orders())
            self.history_table.update_history(self.trades.get_history())
            self._refresh_orders_tab_label()

        except Exception as exc:
            self.log(f"Error fetching prices: {exc}", level="error")
            self.price_widget.update_prices("n/a", "n/a")

    @on(OrderForm.Submit)
    async def order_submitted(self, message: OrderForm.Submit) -> None:
        """Handle order form submissions."""
        try:
            symbol = message.symbol or self.trades.get_current_symbol()
            price = float(message.price) if message.price is not None else None
            
            # If price is None (market order) and qty_mode is USDT, we need a price to convert
            if price is None and message.qty_mode == "USDT":
                # Fetch current mark price to estimate size
                _, mark = await self.trades.get_current_prices()
                try:
                    price = float(mark)
                except ValueError:
                    self.log("Invalid mark price; cannot determine size for USDT qty", level="error")
                    return
            
            # Convert quantity to size based on qty_mode
            qty_value = float(message.qty)
            if message.qty_mode == "USDT":
                size = qty_value / price if price else 0.0
            else:
                size = qty_value

            if message.price is not None:
                # This is a limit order
                order = self.trades.submit_limit_order(
                    symbol=symbol,
                    side=message.side,
                    size=size,
                    limit_price=price
                )
                self.log(f"New limit order placed: {order['id']}")
                self.order_table.update_orders(self.trades.get_orders())
                self._refresh_orders_tab_label()
            else:
                # This is a market order
                position = await self.trades.submit_market_order(
                    symbol=symbol,
                    side=message.side,
                    size=size,
                    price=price
                )
                self.log(f"New {message.side} position opened: {position['id']}")
                self.position_table.update_positions(self.trades.get_positions())

        except Exception as exc:
            self.log(f"Failed to submit order: {exc}", level="error")

    @on(DataTable.CellSelected)
    async def position_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        """Handle position table cell selection."""
        cell_value = event.value
        if cell_value not in ("Close", "Limit"):
            return

        # Get position details from the table
        row_key = event.cell_key.row_key.value
        pos = next((p for p in self.trades.get_positions() if p["id"] == row_key), None)
        if not pos:
            return

        if cell_value == "Close":
            # Close at market price
            closed = await self.trades.close_position_market(pos["id"])
            if closed:
                self.log(f"Closed position {pos['id']} at market. Net PnL {closed['net_pnl']}")
                # Refresh tables
                self.position_table.update_positions(self.trades.get_positions())
                self.history_table.update_history(self.trades.get_history())
                # Also refresh orders table in case linked exit orders were removed
                self.order_table.update_orders(self.trades.get_orders())
                self._refresh_orders_tab_label()
        else:  # Limit
            # Show limit order dialog
            limit_dialog = LimitDialog(pos["id"])
            async def _limit_callback(result: float | None, position_id: str = pos["id"]) -> None:
                self._process_limit_result(position_id, result)

            # Push screen and wait for it to mount; result will be handled in callback
            await self.push_screen(limit_dialog, callback=_limit_callback)

    @on(Select.Changed)
    def symbol_select_changed(self, event: Select.Changed) -> None:
        """Handle symbol selection changes."""
        # Ignore blank / NoSelection events
        if not isinstance(event.value, str) or event.value == "":
            return

        self.trades.set_current_symbol(event.value)
        self.order_form.set_coin_label_from_symbol(event.value)

    def _refresh_orders_tab_label(self):
        """Update tab labels with counts for Orders and Active (positions)."""
        orders_count = len(self.trades.get_orders())
        positions_count = len(self.trades.get_positions())
        try:
            from textual.widgets._tabbed_content import ContentTabs

            content_tabs = self.positions_tabs.query_one(ContentTabs)
            # Update Orders tab label
            orders_tab = content_tabs.get_content_tab("tab_orders")
            orders_tab.label = (
                f"Orders ({orders_count})" if orders_count else "Orders"
            )
            # Update Active tab label
            active_tab = content_tabs.get_content_tab("tab_active")
            active_tab.label = (
                f"Active ({positions_count})" if positions_count else "Active"
            )
        except Exception as exc:
            self.log(f"Failed to update tab labels: {exc}", level="error")

    @on(DataTable.CellSelected)
    def order_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        """Handle order table cell selection."""
        if event.value == "Cancel":
            # Get order details from the table
            row_key = event.cell_key.row_key.value
            self.trades.cancel_order(row_key)
            self.order_table.update_orders(self.trades.get_orders())
            self._refresh_orders_tab_label()

    def _process_limit_result(self, position_id: str, price: float | None) -> None:
        """Process the result of a limit order dialog."""
        if price is None:
            return

        pos = next((p for p in self.trades.get_positions() if p["id"] == position_id), None)
        if not pos:
            return

        # Create exit limit order
        order = self.trades.submit_limit_order(
            symbol=pos["symbol"],
            side="SELL" if pos["side"] == "BUY" else "BUY",
            size=pos["size"],
            limit_price=price,
            position_id=position_id
        )

        self.order_table.update_orders(self.trades.get_orders())
        self._refresh_orders_tab_label()
        self.log(f"Exit limit order created for position {position_id}")

    @on(events.ScreenResume)
    def _on_screen_resume(self, _: events.ScreenResume) -> None:
        """Handle screen resume events."""
        self.order_form.focus()

if __name__ == "__main__":
    BinancePriceApp().run()
