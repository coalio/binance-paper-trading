from textual.widgets import Static

class DataGrid(Static):
    """Generic key-value grid."""
    def __init__(self, **kwargs):
        super().__init__(markup=True, **kwargs)
        self._data: dict[str, dict[str, str]] = {}

    def update_data(self, data: dict[str, dict[str, str]]) -> None:
        self._data = data
        lines = [
            f"[b]{k}[/b]\n{v['value']}\n"
            for k, v in self._data.items()
        ]
        self.update("\n".join(lines))