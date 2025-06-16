from textual.widgets import DataTable

class HistoryTable(DataTable):
    """Table for displaying closed positions (history)."""

    def __init__(self) -> None:
        super().__init__(zebra_stripes=True)
        self.add_columns(
            "Symbol",
            "Side",
            "Size",
            "Entry",
            "Close",
            "Net PnL",
        )

    def update_history(self, history: list[dict]) -> None:
        """Update table rows based on *history* list.

        Each dict in *history* should contain keys:
        symbol, side, size, entry, close, net_pnl
        """
        existing_keys = {row.key for row in self.rows.values()}

        # TODO: refactor this
        def fmt(x):
            return f"{x:,.2f}" if isinstance(x, (int, float)) else x

        for idx, h in enumerate(history):
            row_key = f"hist-{idx}"  # stable key per history order
            pnl_colour = "green" if h["net_pnl"] >= 0 else "red"
            row_values = [
                h["symbol"],
                h["side"],
                fmt(h["size"]),
                fmt(h["entry"]),
                fmt(h["close"]),
                f"[{pnl_colour}]{fmt(h['net_pnl'])}[/{pnl_colour}]",
            ]

            if row_key in existing_keys:
                for col_key, value in zip(self.columns.keys(), row_values):
                    self.update_cell(row_key, col_key, value)
            else:
                self.add_row(*row_values, key=row_key)

        # Remove rows that are no longer in history (after, e.g., clearing)
        for key in list(existing_keys):
            if key not in {f"hist-{idx}" for idx in range(len(history))}:
                self.remove_row(key) 
