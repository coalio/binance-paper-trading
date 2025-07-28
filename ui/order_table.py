from textual.widgets import DataTable

class OrderTable(DataTable):
    """Table showing limit orders waiting to be filled."""

    def __init__(self) -> None:
        super().__init__(zebra_stripes=True)
        self.add_columns("ID", "Symbol", "Side", "Size", "Limit Price", "Cancel")

    def update_orders(self, orders: list[dict]) -> None:
        # Update rows in-place
        existing = {row.key for row in self.rows.values()}
        for o in orders:
            key = o["id"]
            size = f"{o['size']:.2f}"
            row_vals = [o["id"], o["symbol"], o["side"], size, f"{o['limit_price']:.2f}", "Cancel"]
            if key in existing:
                for col, val in zip(self.columns.keys(), row_vals):
                    self.update_cell(key, col, val)
            else:
                self.add_row(*row_vals, key=key)
        # Remove stale rows
        for k in list(existing):
            if k not in {o["id"] for o in orders}:
                self.remove_row(k)
