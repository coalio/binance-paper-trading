from .data_grid import DataGrid

class PriceDisplay(DataGrid):
    """Specialised grid for last-price / mark-price."""
    def update_prices(self, last: str, mark: str) -> None:
        try:
            lp, mp = float(last), float(mark)
            colour  = "green" if mp >= lp else "red"
        except ValueError:          # one of the values = "n/a"
            colour = "white"

        self.update_data(
            {
                "Last traded price": {
                    "value": f"[green]{last}[/green]",
                    "color": "green"
                },
                "Mark price": {
                    "value": f"[{colour}]{mark}[/{colour}]",
                    "color": colour
                }
            }
        )
