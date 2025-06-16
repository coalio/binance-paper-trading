from textual.widgets import DataTable

class PositionTable(DataTable):
    """Table for displaying current open positions."""

    def __init__(self) -> None:
        super().__init__(zebra_stripes=True)
        self.add_columns(
            "Symbol",
            "Side",
            "Size",
            "Entry",
            "Liq",
            "Break-even",
            "PnL",
            "Net PnL",
            "Close",
        )

    def update_positions(self, positions: list[dict]) -> None:
        """Update table rows based on *positions* list.

        Each dict in *positions* should contain keys:
        symbol, side, size, entry, liquidation, breakeven, pnl, net_pnl
        """
        existing_keys = {row.key for row in self.rows.values()}
        # First add/update rows
        for p in positions:
            row_key = p["id"]
            pnl_colour = "green" if p["pnl"] >= 0 else "red"
            net_colour = "green" if p["net_pnl"] >= 0 else "red"

            # format numbers to 2 decimals
            def fmt(x):
                return f"{x:,.2f}" if isinstance(x, (int, float)) else x

            row_values = [
                p["symbol"],
                p["side"],
                fmt(p["size"]),
                fmt(p["entry"]),
                fmt(p["liquidation"]),
                fmt(p["breakeven"]),
                f"[{pnl_colour}]{fmt(p['pnl'])}[/{pnl_colour}]",
                f"[{net_colour}]{fmt(p['net_pnl'])}[/{net_colour}]",
                "Close",
            ]

            if row_key in existing_keys:
                # update cells
                for col_key, value in zip(self.columns.keys(), row_values):
                    self.update_cell(row_key, col_key, value)
            else:
                self.add_row(*row_values, key=row_key)

        # Remove rows that no longer exist
        for key in list(existing_keys):
            if key not in {p["id"] for p in positions}:
                self.remove_row(key) 