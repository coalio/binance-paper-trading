from .data_grid import DataGrid

class PriceDisplay(DataGrid):
    """Specialised grid for last-price / mark-price."""
    def update_prices(self, last: str, mark: str) -> None:
        try:
            lp, mp = float(last), float(mark)
            colour = "green" if mp >= lp else "red"
            last_display = f"[green]{last}[/green]"
            mark_display = f"[{colour}]{mark}[/{colour}]"
        except ValueError:          # one of the values is not a number
            colour = "red"
            last_display = f"[{colour}]{last}[/{colour}]"
            mark_display = f"[{colour}]{mark}[/{colour}]"

        self.update_data(
            {
                "Last traded price": {
                    "value": last_display,
                    "color": "green" if colour == "green" else "red"
                },
                "Mark price": {
                    "value": mark_display,
                    "color": colour
                }
            }
        )
