import asyncio
from binance.um_futures import UMFutures

class BinanceService:
    """
    service class responsible for fetching Binance futures prices
    """
    def __init__(self):
        self.client = UMFutures()

    async def get_symbol_prices(self, symbol: str) -> tuple[str, str]:
        """
        fetch last traded price and mark price for the given symbol
        returns (last_price, mark_price)
        """
        # run blocking calls in threads
        ticker = await asyncio.to_thread(self.client.ticker_price, symbol=symbol)
        mark   = await asyncio.to_thread(self.client.mark_price, symbol=symbol)
        last_price = ticker.get("price", "n/a")
        mark_price = mark.get("markPrice", "n/a")
        return last_price, mark_price

    async def get_top_usdt_pairs(self, limit: int = 20) -> list[str]:
        """Return USDT-margined perpetual futures symbols (up to *limit*)."""
        # Retrieve exchange info which lists all futures symbols
        exchange_info = await asyncio.to_thread(self._get_exchange_info)
        symbols_info: list[dict] = exchange_info.get("symbols", [])
        usdt_pairs = [s["symbol"] for s in symbols_info if s.get("quoteAsset") == "USDT" and s.get("contractType") == "PERPETUAL"]
        # limit result
        return usdt_pairs[:limit]

    def _get_exchange_info(self) -> dict:
        """Blocking helper to get futures exchange info using whatever method is available in the client."""
        # The python-binance futures client may expose .exchange_info() or .futures_exchange_info()
        if hasattr(self.client, "futures_exchange_info"):
            return self.client.futures_exchange_info()
        elif hasattr(self.client, "exchange_info"):
            return self.client.exchange_info()
        else:
            # Fallback: call via generic endpoint path
            return {}

