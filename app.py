from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
from collections import defaultdict
import MetaTrader5 as mt5
from enum import Enum
import asyncio
import json
import os

# MT5 Connection configuration
MT5_ACCOUNT = os.environ.get("MT5_ACCOUNT")
MT5_PASSWORD = os.environ.get("MT5_PASSWORD")
MT5_SERVER = os.environ.get("MT5_SERVER")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TimeFrame(str, Enum):
    """MT5 Timeframe enumeration"""
    S1 = "S1"
    M1 = "M1"
    M2 = "M2"
    M3 = "M3"
    M4 = "M4"
    M5 = "M5"
    M6 = "M6"
    M10 = "M10"
    M12 = "M12"
    M15 = "M15"
    M20 = "M20"
    M30 = "M30"
    H1 = "H1"
    H2 = "H2"
    H3 = "H3"
    H4 = "H4"
    H6 = "H6"
    H8 = "H8"
    H12 = "H12"
    D1 = "D1"
    W1 = "W1"
    MN1 = "MN1"


# Map string timeframes to MT5 constants
TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M2": mt5.TIMEFRAME_M2,
    "M3": mt5.TIMEFRAME_M3,
    "M4": mt5.TIMEFRAME_M4,
    "M5": mt5.TIMEFRAME_M5,
    "M6": mt5.TIMEFRAME_M6,
    "M10": mt5.TIMEFRAME_M10,
    "M12": mt5.TIMEFRAME_M12,
    "M15": mt5.TIMEFRAME_M15,
    "M20": mt5.TIMEFRAME_M20,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H2": mt5.TIMEFRAME_H2,
    "H3": mt5.TIMEFRAME_H3,
    "H4": mt5.TIMEFRAME_H4,
    "H6": mt5.TIMEFRAME_H6,
    "H8": mt5.TIMEFRAME_H8,
    "H12": mt5.TIMEFRAME_H12,
    "D1": mt5.TIMEFRAME_D1,
    "W1": mt5.TIMEFRAME_W1,
    "MN1": mt5.TIMEFRAME_MN1,
}


class OHLCBar(BaseModel):
    """Single OHLC bar data"""
    time: str
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    spread: int
    real_volume: int


class OHLCResponse(BaseModel):
    """Response model for OHLC data"""
    symbol: str
    timeframe: str
    bars_count: int
    data: List[OHLCBar]


def _build_s1_bars(symbol: str, bars: int) -> List[OHLCBar]:
    """Build 1-second OHLC bars by aggregating raw tick data from MT5."""
    date_from = datetime.now() - timedelta(seconds=bars + 120)
    ticks = mt5.copy_ticks_from(symbol, date_from, 500000, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) == 0:
        return []

    symbol_info = mt5.symbol_info(symbol)
    point = symbol_info.point if symbol_info and symbol_info.point > 0 else 0.00001

    buckets: dict = defaultdict(list)
    for tick in ticks:
        second_ts = int(tick['time_msc']) // 1000
        buckets[second_ts].append(tick)

    result: List[OHLCBar] = []
    for second_ts in sorted(buckets.keys()):
        bucket = buckets[second_ts]
        prices = []
        spreads = []
        total_volume = 0

        for t in bucket:
            bid, ask = float(t['bid']), float(t['ask'])
            if bid > 0:
                prices.append(bid)
            elif ask > 0:
                prices.append(ask)
            if bid > 0 and ask > 0:
                spreads.append(ask - bid)
            total_volume += int(t['volume'])

        if not prices:
            continue

        avg_spread = sum(spreads) / len(spreads) if spreads else 0.0
        result.append(OHLCBar(
            time=datetime.fromtimestamp(second_ts).isoformat(),
            open=prices[0],
            high=max(prices),
            low=min(prices),
            close=prices[-1],
            tick_volume=len(bucket),
            spread=int(round(avg_spread / point)),
            real_volume=total_volume
        ))

    return result[-bars:] if len(result) > bars else result


@app.on_event("startup")
async def startup_event():
    if not mt5.initialize():
        print(f"MT5 initialize() failed, error code = {mt5.last_error()}")
        return

    authorized = mt5.login(MT5_ACCOUNT, password=MT5_PASSWORD, server=MT5_SERVER)

    if authorized:
        account_info = mt5.account_info()
        print(f"Connected to MT5 account: {account_info.login}")
    else:
        print(f"Failed to connect to MT5 account, error code: {mt5.last_error()}")


@app.on_event("shutdown")
async def shutdown_event():
    mt5.shutdown()
    print("MT5 connection closed")


@app.get("/")
async def root():
    return { "status": "Running", }
    

@app.get("/api/ohlc", response_model=OHLCResponse)
async def get_ohlc(
    symbol: str = Query(..., description="Trading symbol (e.g., EURUSD, GBPUSD)"),
    timeframe: TimeFrame = Query(..., description="Timeframe (M1, M5, H1, D1, etc.)"),
    bars: int = Query(100, ge=1, le=5000, description="Number of bars to retrieve (1-5000)")
):

    if not mt5.terminal_info():
        raise HTTPException(
            status_code=503,
            detail="MT5 terminal not connected. Please check connection."
        )

    if timeframe == TimeFrame.S1:
        ohlc_data = _build_s1_bars(symbol, bars)
        if not ohlc_data:
            raise HTTPException(
                status_code=404,
                detail=f"No tick data available for {symbol} to build S1 bars"
            )
    else:
        mt5_timeframe = TIMEFRAME_MAP.get(timeframe.value)
        if not mt5_timeframe:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid timeframe: {timeframe}"
            )

        rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, bars)
        if rates is None:
            error = mt5.last_error()
            raise HTTPException(
                status_code=404,
                detail=f"Failed to get data for {symbol}. Error: {error}"
            )

        if len(rates) == 0:
            raise HTTPException(
                status_code=404,
                detail=f"No data available for symbol {symbol} on timeframe {timeframe}"
            )

        ohlc_data = []
        for rate in rates:
            ohlc_data.append(OHLCBar(
                time=datetime.fromtimestamp(rate['time']).isoformat(),
                open=float(rate['open']),
                high=float(rate['high']),
                low=float(rate['low']),
                close=float(rate['close']),
                tick_volume=int(rate['tick_volume']),
                spread=int(rate['spread']),
                real_volume=int(rate['real_volume'])
            ))

    return OHLCResponse(
        symbol=symbol,
        timeframe=timeframe.value,
        bars_count=len(ohlc_data),
        data=ohlc_data
    )


@app.get("/api/symbols")
async def get_symbols():
    """Get list of available trading symbols"""
    if not mt5.terminal_info():
        raise HTTPException(
            status_code=503,
            detail="MT5 terminal not connected"
        )

    symbols = mt5.symbols_get()
    if symbols is None:
        raise HTTPException(
            status_code=500,
            detail="Failed to get symbols"
        )

    symbol_list = [
        {
            "name": symbol.name,
            "description": symbol.description,
            "path": symbol.path,
            "visible": symbol.visible
        }
        for symbol in symbols if symbol.visible
    ]

    return {
        "count": len(symbol_list),
        "symbols": symbol_list
    }


@app.get("/api/account")
async def get_account_info():
    """Get MT5 account information"""
    if not mt5.terminal_info():
        raise HTTPException(
            status_code=503,
            detail="MT5 terminal not connected"
        )

    account_info = mt5.account_info()
    if account_info is None:
        raise HTTPException(
            status_code=500,
            detail="Failed to get account information"
        )

    return {
        "login": account_info.login,
        "server": account_info.server,
        "balance": account_info.balance,
        "equity": account_info.equity,
        "margin": account_info.margin,
        "margin_free": account_info.margin_free,
        "margin_level": account_info.margin_level,
        "currency": account_info.currency,
        "leverage": account_info.leverage,
        "profit": account_info.profit
    }


@app.websocket("/ws/{symbol}")
async def websocket_realtime(websocket: WebSocket, symbol: str):

    await websocket.accept()

    try:
        if not mt5.terminal_info():
            await websocket.send_json({
                "error": "MT5 terminal not connected",
                "code": 503
            })
            await websocket.close()
            return

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            await websocket.send_json({
                "error": f"Symbol {symbol} not found",
                "code": 404
            })
            await websocket.close()
            return

        if not symbol_info.visible:
            if not mt5.symbol_select(symbol, True):
                await websocket.send_json({
                    "error": f"Failed to select symbol {symbol}",
                    "code": 500
                })
                await websocket.close()
                return

        await websocket.send_json({
            "type": "connection",
            "status": "connected",
            "symbol": symbol,
            "message": f"Streaming real-time data for {symbol}"
        })

        last_tick_time = 0

        while True:

            tick = mt5.symbol_info_tick(symbol)

            if tick is None:
                await websocket.send_json({
                    "type": "error",
                    "error": f"Failed to get tick for {symbol}",
                    "code": 500
                })
                await asyncio.sleep(0.1)
                continue

            if tick.time > last_tick_time:
                last_tick_time = tick.time

                tick_data = {
                    "type": "tick",
                    "symbol": symbol,
                    "time": datetime.fromtimestamp(tick.time).isoformat(),
                    "time_msc": tick.time_msc,
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "last": tick.last,
                    "volume": tick.volume,
                    "volume_real": tick.volume_real,
                    "flags": tick.flags,
                    "spread": (tick.ask - tick.bid) if tick.ask and tick.bid else 0
                }

                await websocket.send_json(tick_data)

            await asyncio.sleep(0.01)

    except WebSocketDisconnect:
        print(f"WebSocket disconnected for {symbol}")
    except Exception as e:
        print(f"WebSocket error for {symbol}: {str(e)}")
        try:
            await websocket.send_json({
                "type": "error",
                "error": str(e),
                "code": 500
            })
        except:
            pass
    finally:
        try:
            await websocket.close()
        except:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
