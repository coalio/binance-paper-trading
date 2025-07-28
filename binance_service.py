import asyncio
from binance.um_futures import UMFutures

class BinanceService:
    """
    service class responsible for fetching Binance futures prices
    """
    def __init__(self):
        self.client = UMFutures()
        # Cache for commission lookups to avoid repeated network calls
        self._commission_cache: dict[str, tuple[float, float]] = {}

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

    async def get_symbol_commission_rates(self, symbol: str) -> tuple[float, float]:
        """Return (makerCommission, takerCommission) **as decimal rates** for the given symbol.

        Binance REST responses sometimes express commissions as integer basis points
        (e.g. 2 -> 0.02%).  This helper normalises the values to fractions: 0.0002 -> 0.02%.

        If the exchange-info payload does not include commission fields, or the API call
        fails, we fall back to the common default 0.02% maker / 0.04% taker that is
        applied to regular USDT-M perpetual accounts.
        """

        # Serve from cache first
        cached = self._commission_cache.get(symbol)
        if cached:
            return cached

        maker: float | None = None
        taker: float | None = None

        try:
            exchange_info = await asyncio.to_thread(self._get_exchange_info)
            for s in exchange_info.get("symbols", []):
                if s.get("symbol") == symbol:
                    # Spot API returns integers like 15 ( =0.15% ). Futures has similar.
                    maker_raw = s.get("makerCommission")
                    taker_raw = s.get("takerCommission")

                    if maker_raw is not None:
                        maker = float(maker_raw)
                    if taker_raw is not None:
                        taker = float(taker_raw)
                    break
        except Exception:
            # Ignore network / parsing errors – will fall back to defaults
            pass

        # Fallback defaults if missing or zero
        if not maker:
            maker = 0.0002  # 0.02%
        if not taker:
            taker = 0.0004  # 0.04%

        # Convert integer basis-point style ( >1 ) to decimal fraction if needed
        if maker > 1:
            maker = maker / 10000  # e.g. 2  -> 0.0002
        if taker > 1:
            taker = taker / 10000

        self._commission_cache[symbol] = (maker, taker)
        return maker, taker

