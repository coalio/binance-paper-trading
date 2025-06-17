from textual.widgets import Static, Input, Button
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen


class LimitDialog(ModalScreen):
    """Modal dialog that asks for limit price and returns it."""

    def __init__(self, position_id: str):
        super().__init__()
        self.position_id = position_id  # kept for debugging / potential display

    def compose(self):
        self.price_input = Input(placeholder="Limit price", id="dialog_price", name="price_input")

        yield Vertical(
            self.price_input,
            Horizontal(
                Button("Place", id="dialog_place", variant="success"),
                Button("Close", id="dialog_cancel"),
                id="dialog_buttons",
            ),
            id="dialog_container",
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "dialog_cancel":
            self.dismiss(None)
        elif event.button.id == "dialog_place":
            price_widget = self.query_one("#dialog_price", Input)
            try:
                price_val = float(price_widget.value)
            except ValueError:
                return

            self.dismiss(price_val)
