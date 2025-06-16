from textual.containers import Vertical, Horizontal
from textual.widgets import Input, Button, Label, Select
from textual.message import Message

class OrderForm(Vertical):
    """A simple order entry form for paper trading."""

    class Submit(Message):
        """Posted when the user presses the *Submit* button.

        Contains symbol, side, price, and quantity information for an order.
        """
        def __init__(
            self,
            symbol: str,
            side: str,
            price: str | None,
            qty: str,
            qty_mode: str,
        ) -> None:
            self.symbol = symbol.upper()
            self.side = side.upper()
            self.price = price
            self.qty = qty
            self.qty_mode = qty_mode  # base asset name or "USDT"
            super().__init__()

    def compose(self):
        """Compose the child widgets."""
        yield Label("Symbol")
        self.symbol_select = Select.from_values([], prompt="Loading", compact=True, id="symbol")
        yield self.symbol_select

        yield Label("Price (blank = Market)")
        self.price_input = Input(placeholder="", id="price")
        yield self.price_input

        yield Label("Quantity")
        self.qty_input = Input(placeholder="0.001", id="qty")
        # coin button placeholder label will be updated later
        self.coin_button = Button("COIN", id="mode_coin", variant="primary")
        self.usdt_button = Button("USDT", id="mode_usdt", variant="default")
        yield Horizontal(
            self.qty_input,
            self.coin_button,
            self.usdt_button,
            id="qty_row",
        )

        self.qty_mode = "COIN"  # default (base asset)

        yield Horizontal(
            Button("Buy", id="buy", variant="success"),
            Button("Sell", id="sell", variant="error"),
            id="submit_row",
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle *Submit* button press."""
        button_id = event.button.id
        if button_id in ("mode_coin", "mode_usdt"):
            # Switch qty mode
            self.qty_mode = "COIN" if button_id == "mode_coin" else "USDT"
            # adjust variants
            self.coin_button.variant = "primary" if self.qty_mode == "COIN" else "default"
            self.usdt_button.variant = "primary" if self.qty_mode == "USDT" else "default"
            return

        if button_id in ("buy", "sell"):
            side = "BUY" if button_id == "buy" else "SELL"
            self.post_message(
                self.Submit(
                    str(self.symbol_select.value) if self.symbol_select.value is not Select.BLANK else "",
                    side,
                    self.price_input.value or None,
                    self.qty_input.value or "0",
                    self.qty_mode,
                )
            )

    # Public helper to refresh symbol options
    def update_symbols(self, symbols: list[str], current: str | None = None) -> None:
        self.log.debug(f"Updating symbols list with {len(symbols)} options, current={current}")
        options = [(s, s) for s in symbols]
        self.symbol_select.set_options(options)
        
        if current and current in symbols:
            self.log.debug(f"Setting current symbol to {current}")
            # Force refresh by toggling value
            self.symbol_select.value = Select.BLANK
            self.symbol_select.value = current
            self.symbol_select.prompt = "Symbol"
            # Update coin button label to base asset of current symbol
            if current:
                base = current.replace("USDT", "")
                self.coin_button.label = base
                self.log.debug(f"Updated coin button label to {base}")
        elif symbols:
            self.log.debug(f"No current symbol match, defaulting to {symbols[0]}")
            self.symbol_select.value = symbols[0]
            base = symbols[0].replace("USDT", "")
            self.coin_button.label = base
            self.log.debug(f"Updated coin button label to {base}")
            # Update prompt text now that list is loaded
            self.symbol_select.prompt = "Symbol"
        else:
            self.log.warning("No symbols provided, clearing selection")
            self.symbol_select.value = Select.BLANK

    def set_coin_label_from_symbol(self, symbol: str) -> None:
        """Update coin button label based on symbol like BTCUSDT -> BTC."""
        base = symbol.replace("USDT", "")
        self.coin_button.label = base
        if self.qty_mode == "COIN":
            self.coin_button.variant = "primary"
        else:
            self.coin_button.variant = "default"