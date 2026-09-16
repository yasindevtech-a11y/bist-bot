from __future__ import annotations

import numpy as np
import pandas as pd
import borsapy as bp


PERIODS = (5, 9, 21, 50, 100, 200)


def _col(df, name):
    for c in df.columns:
        if str(c).lower() == name.lower():
            return pd.to_numeric(df[c], errors="coerce")
    raise KeyError(f"{name} kolonu bulunamadı")


def rsi(close, period=14):
    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    return (100 - (100 / (1 + rs))).fillna(50)


def macd(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()

    line = ema12 - ema26
    signal = line.ewm(span=9, adjust=False).mean()
    histogram = line - signal

    return line, signal, histogram


def atr(df, period=14):
    high = _col(df, "high")
    low = _col(df, "low")
    close = _col(df, "close")

    previous_close = close.shift()

    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs()
        ],
        axis=1
    ).max(axis=1)

    return true_range.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period
    ).mean()


def vwap(df):
    high = _col(df, "high")
    low = _col(df, "low")
    close = _col(df, "close")
    volume = _col(df, "volume")

    typical_price = (high + low + close) / 3

    return (
        (typical_price * volume).cumsum()
        /
        volume.replace(0, np.nan).cumsum()
    )


def divergence(close, indicator, period=30):
    if len(close) < period + 5:
        return "YOK"

    price = close.tail(period)
    ind = indicator.tail(period)

    middle = period // 2

    price_old = price.iloc[:middle]
    price_new = price.iloc[middle:]

    ind_old = ind.iloc[:middle]
    ind_new = ind.iloc[middle:]

    # Pozitif uyumsuzluk
    if (
        price_new.min() < price_old.min()
        and ind_new.min() > ind_old.min()
    ):
        return "POZİTİF"

    # Negatif uyumsuzluk
    if (
        price_new.max() > price_old.max()
        and ind_new.max() < ind_old.max()
    ):
        return "NEGATİF"

    return "YOK"


def analyze(symbol, period="1y", interval="1d"):

    symbol = symbol.upper().replace(".E", "")

    ticker = bp.Ticker(symbol)

    df = ticker.history(
        period=period,
        interval=interval
    )

    if df is None or len(df) < 220:
        raise ValueError(
            f"{symbol}: yeterli geçmiş veri yok."
        )

    close = _col(df, "close")
    volume = _col(df, "volume")

    # RSI
    rsi_value = rsi(close)

    # MACD
    macd_line, macd_signal, macd_hist = macd(close)

    # Hareketli ortalamalar
    ma = {}

    for p in PERIODS:
        ma[p] = close.rolling(p).mean()

    # EMA
    ema12 = close.ewm(
        span=12,
        adjust=False
    ).mean()

    ema26 = close.ewm(
        span=26,
        adjust=False
    ).mean()

    # Bollinger Bands
    middle = close.rolling(20).mean()
    std = close.rolling(20).std()

    upper = middle + 2 * std
    lower = middle - 2 * std

    # ATR
    atr_value = atr(df)

    # VWAP
    vwap_value = vwap(df)

    # OBV
    obv = (
        np.sign(close.diff()).fillna(0)
        * volume
    ).cumsum()

    # Hacim oranı
    volume_average = volume.rolling(20).mean()

    if volume_average.iloc[-1] != 0:
        volume_ratio = (
            volume.iloc[-1]
            /
            volume_average.iloc[-1]
        )
    else:
        volume_ratio = 1

    price = float(close.iloc[-1])

    current_rsi = float(rsi_value.iloc[-1])

    current_macd = float(macd_line.iloc[-1])
    current_signal = float(macd_signal.iloc[-1])
    current_hist = float(macd_hist.iloc[-1])

    current_vwap = float(vwap_value.iloc[-1])

    # ==================================================
    # TEKNİK SKOR
    # ==================================================

    score = 50

    # Fiyat - MA21
    if price > ma[21].iloc[-1]:
        score += 4
    else:
        score -= 4

    # Fiyat - MA50
    if price > ma[50].iloc[-1]:
        score += 4
    else:
        score -= 4

    # Fiyat - MA200
    if price > ma[200].iloc[-1]:
        score += 4
    else:
        score -= 4

    # MA21 - MA50
    if ma[21].iloc[-1] > ma[50].iloc[-1]:
        score += 5
    else:
        score -= 5

    # MA50 - MA200
    if ma[50].iloc[-1] > ma[200].iloc[-1]:
        score += 4
    else:
        score -= 4

    # RSI
    if current_rsi >= 50:
        score += min(
            10,
            (current_rsi - 50) / 5
        )
    else:
        score -= min(
            10,
            (50 - current_rsi) / 5
        )

    # MACD
    if current_macd > current_signal:
        score += 8
    else:
        score -= 8

    # MACD histogram
    if current_hist > float(macd_hist.iloc[-2]):
        score += 7
    else:
        score -= 7

    # Hacim
    if volume_ratio >= 1.5:
        score += 7

    elif volume_ratio >= 1.1:
        score += 3

    elif volume_ratio < 0.7:
        score -= 2

    # OBV
    if obv.iloc[-1] > obv.iloc[-10]:
        score += 5
    else:
        score -= 5

    # VWAP
    if price > current_vwap:
        score += 3
    else:
        score -= 3

    # Bollinger
    if price <= upper.iloc[-1] and price <= lower.iloc[-1] * 1.02:
        score += 3

    elif price >= upper.iloc[-1] * 0.98:
        score -= 3

    # RSI uyumsuzluğu
    rsi_div = divergence(
        close,
        rsi_value
    )

    if rsi_div == "POZİTİF":
        score += 8

    elif rsi_div == "NEGATİF":
        score -= 8

    # MACD uyumsuzluğu
    macd_div = divergence(
        close,
        macd_line
    )

    if macd_div == "POZİTİF":
        score += 5

    elif macd_div == "NEGATİF":
        score -= 5

    # Skoru 0-100 arasında tut
    score = max(
        0,
        min(
            100,
            round(score)
        )
    )

    # Durum
    if score >= 70:
        status = "GÜÇLÜ POZİTİF"

    elif score >= 58:
        status = "POZİTİF"

    elif score <= 30:
        status = "GÜÇLÜ NEGATİF"

    elif score <= 42:
        status = "NEGATİF"

    else:
        status = "NÖTR / İZLE"

    # Destek
    support = float(
        _col(df, "low")
        .tail(20)
        .min()
    )

    # Direnç
    resistance = float(
        _col(df, "high")
        .tail(20)
        .max()
    )

    return {
        "symbol": symbol,
        "price": price,

        "rsi": current_rsi,

        "macd": current_macd,
        "signal": current_signal,
        "hist": current_hist,

        "ma": {
            p: float(ma[p].iloc[-1])
            for p in PERIODS
        },

        "ema12": float(ema12.iloc[-1]),
        "ema26": float(ema26.iloc[-1]),

        "bb_upper": float(
            upper.iloc[-1]
        ),

        "bb_lower": float(
            lower.iloc[-1]
        ),

        "atr": float(
            atr_value.iloc[-1]
        ),

        "vwap": current_vwap,

        "volume_ratio": float(
            volume_ratio
        ),

        "support": support,
        "resistance": resistance,

        "rsi_divergence": rsi_div,
        "macd_divergence": macd_div,

        "score": score,
        "status": status
    }


def format_report(data):

    ma = data["ma"]

    return (
        f"📊 {data['symbol']} TEKNİK ANALİZ\n\n"

        f"💰 Fiyat: "
        f"{data['price']:.2f} TL\n\n"

        f"RSI(14): "
        f"{data['rsi']:.1f}\n"

        f"MACD: "
        f"{data['macd']:.3f}\n"

        f"Sinyal: "
        f"{data['signal']:.3f}\n"

        f"Histogram: "
        f"{data['hist']:.3f}\n\n"

        f"📈 HAREKETLİ ORTALAMALAR\n"

        f"MA5: {ma[5]:.2f}\n"
        f"MA9: {ma[9]:.2f}\n"
        f"MA21: {ma[21]:.2f}\n"
        f"MA50: {ma[50]:.2f}\n"
        f"MA100: {ma[100]:.2f}\n"
        f"MA200: {ma[200]:.2f}\n\n"

        f"EMA12: "
        f"{data['ema12']:.2f}\n"

        f"EMA26: "
        f"{data['ema26']:.2f}\n\n"

        f"VWAP: "
        f"{data['vwap']:.2f}\n"

        f"ATR: "
        f"{data['atr']:.2f}\n"

        f"Hacim / 20 Ort.: "
        f"{data['volume_ratio']:.2f}x\n\n"

        f"🔵 Destek: "
        f"{data['support']:.2f}\n"

        f"🔴 Direnç: "
        f"{data['resistance']:.2f}\n\n"

        f"RSI Uyumsuzluğu: "
        f"{data['rsi_divergence']}\n"

        f"MACD Uyumsuzluğu: "
        f"{data['macd_divergence']}\n\n"

        f"🎯 TEKNİK SKOR: "
        f"{data['score']}/100\n"

        f"📌 Durum: "
        f"{data['status']}\n\n"

        f"ℹ️ Bu skor teknik göstergelerin "
        f"birleşimidir; kesin getiri garantisi değildir."
    )
