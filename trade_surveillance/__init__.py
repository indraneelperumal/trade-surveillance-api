from trade_surveillance.config import get_settings

__all__ = ["get_settings", "investigate_trade"]


def __getattr__(name: str):
    if name == "investigate_trade":
        from trade_surveillance.agents import investigate_trade as _fn

        return _fn
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
