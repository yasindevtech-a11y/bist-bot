"""
BIST Telegram Botu (GitHub Actions Sürümü)
--------------------------------------------
Hem komutlara cevap verir (/start, /yardim, /durum, /analiz SEMBOL, /tara)
hem de otomatik piyasa taraması yapıp AL/SAT sinyali bildirir.

GitHub Actions her ~5 dakikada bir bu scripti çalıştırır. Her çalıştığında:
1. Telegram'da bekleyen yeni komut var mı diye bakar, varsa cevaplar
2. Piyasayı tarar, yeni sinyal varsa bildirir

Bu bot EMİR GÖNDERMEZ, sadece bilgi/bildirim üretir. Yatırım tavsiyesi değildir.
"""

import os
import json
from datetime import datetime, timezone
import requests
import pandas as pd
import borsapy as bp

# ---------------------------------------------------------------
# AYARLAR
# ---------------------------------------------------------------

UNIVERSE = "XUTUM"  # BIST'te işlem gören tüm hisseler

TIERS = [
    {"name": "Güçlü", "emoji": "🔥", "buy_rsi": 20, "sell_rsi": 80},
    {"name": "Orta", "emoji": "🟡", "buy_rsi": 30, "sell_rsi": 70},
    {"name": "Zayıf", "emoji": "⚪", "buy_rsi": 40, "sell_rsi": 60},
]
BUY_CONDITION = f"rsi < {TIERS[-1]['buy_rsi']}"
SELL_CONDITION = f"rsi > {TIERS[-1]['sell_rsi']}"
MIN_VOLUME = 500_000

BUY_EMOJI = "🟢"
SELL_EMOJI = "🔴"

_MDV2_SPECIAL = r"_*[]()~`>#+-=|{}.!"


def escape_mdv2(text: str) -> str:
    """Telegram MarkdownV2 için özel karakterleri kaçış (escape) karakteriyle işaretler."""
    result = []
    for ch in text:
        if ch in _MDV2_SPECIAL:
            result.append("\\" + ch)
        else:
            result.append(ch)
    return "".join(result)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

STATE_FILE = "last_signals.json"

HELP_TEXT = (
    "🤖 BIST SİNYAL BOTU\n\n"
    "Komutlar:\n\n"
    "/start - Botu başlat\n"
    "/yardim - Komutları göster\n"
    "/durum - Bot durumunu göster\n"
    "/analiz THYAO - Detaylı teknik analiz\n"
    "/tara - BIST sinyal taraması\n\n"
    "Örnek:\n"
    "/analiz ASELS\n"
    "/analiz TUPRS\n"
    "/analiz THYAO\n\n"
    "ℹ️ Şirket adı değil, borsa kodu yazın (örn. ASELSAN değil ASELS)."
)


# ---------------------------------------------------------------
# DURUM (STATE) YÖNETİMİ
# ---------------------------------------------------------------

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


# ---------------------------------------------------------------
# TELEGRAM YARDIMCI FONKSİYONLARI
# ---------------------------------------------------------------

def send_telegram_message(text: str, chat_id: str = None, parse_mode: str = None) -> None:
    target = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target:
        print("UYARI: Telegram bilgileri eksik, mesaj gönderilemedi.")
        print(text)
        return
    payload = {"chat_id": target, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        resp = requests.post(
            f"{API_URL}/sendMessage",
            data=payload,
            timeout=20,
        )
        if resp.status_code != 200:
            print(f"Telegram gönderim hatası: {resp.text}")
    except Exception as e:
        print(f"Telegram gönderim istisnası: {e}")


def get_telegram_updates(offset: int):
    try:
        resp = requests.get(
            f"{API_URL}/getUpdates",
            params={"offset": offset, "timeout": 0},
            timeout=20,
        )
        data = resp.json()
        if not data.get("ok"):
            print(f"getUpdates hatası: {data}")
            return []
        return data.get("result", [])
    except Exception as e:
        print(f"getUpdates istisnası: {e}")
        return []


# ---------------------------------------------------------------
# TEKNİK ANALİZ FONKSİYONLARI
# ---------------------------------------------------------------

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def detect_divergence(close: pd.Series, indicator: pd.Series, lookback: int = 30) -> str:
    """Son `lookback` bar içinde fiyat ile göstergenin en düşük/en yüksek
    noktalarını karşılaştırarak basit bir uyumsuzluk tespiti yapar."""
    if len(close) < lookback or len(indicator) < lookback:
        return "YOK"

    recent_close = close.tail(lookback)
    recent_ind = indicator.tail(lookback)

    # Fiyatın en düşük 2 kapanışının indekslerini bul (pozitif uyumsuzluk için)
    lows = recent_close.nsmallest(2)
    if len(lows) == 2:
        idx1, idx2 = lows.index[0], lows.index[1]
        # Kronolojik sıraya koy
        if idx1 > idx2:
            idx1, idx2 = idx2, idx1
        price_lower_low = recent_close[idx2] < recent_close[idx1]
        ind_higher_low = recent_ind[idx2] > recent_ind[idx1]
        if price_lower_low and ind_higher_low:
            return "VAR (Pozitif)"

    # Fiyatın en yüksek 2 kapanışının indekslerini bul (negatif uyumsuzluk için)
    highs = recent_close.nlargest(2)
    if len(highs) == 2:
        idx1, idx2 = highs.index[0], highs.index[1]
        if idx1 > idx2:
            idx1, idx2 = idx2, idx1
        price_higher_high = recent_close[idx2] > recent_close[idx1]
        ind_lower_high = recent_ind[idx2] < recent_ind[idx1]
        if price_higher_high and ind_lower_high:
            return "VAR (Negatif)"

    return "YOK"


def technical_score(rsi, macd_hist, price, mas: dict, vol_ratio) -> tuple:
    """0-100 arası basit teknik skor + durum etiketi üretir."""
    score = 50

    # RSI katkısı: 30 altı düşük skor (aşırı satım, teorik toparlanma potansiyeli
    # ama kısa vadede negatif momentum), 70 üstü yüksek risk
    if rsi is not None:
        if rsi < 30:
            score -= (30 - rsi) * 1.2
        elif rsi > 70:
            score -= (rsi - 70) * 1.2
        else:
            score += (rsi - 50) * 0.3

    # MACD histogram katkısı
    if macd_hist is not None:
        score += 15 if macd_hist > 0 else -15

    # Fiyatın hareketli ortalamalara göre konumu
    above_count = sum(1 for ma in mas.values() if ma and price > ma)
    total_mas = sum(1 for ma in mas.values() if ma)
    if total_mas:
        score += ((above_count / total_mas) - 0.5) * 40

    # Hacim katkısı (ortalamanın çok üzerinde hacim = ilgi artışı)
    if vol_ratio is not None and vol_ratio > 1.5:
        score += 5

    score = max(0, min(100, round(score)))

    # Kademeler: 70+ Güçlü Pozitif, 58-69 Pozitif, 43-57 Nötr/İzle,
    # 31-42 Negatif, 30 ve altı Güçlü Negatif
    if score >= 70:
        status = "GÜÇLÜ POZİTİF"
    elif score >= 58:
        status = "POZİTİF"
    elif score >= 43:
        status = "NÖTR/İZLE"
    elif score >= 31:
        status = "NEGATİF"
    else:
        status = "GÜÇLÜ NEGATİF"

    return score, status


def analyze_symbol(symbol: str) -> str:
    """Bir hisse için detaylı teknik analiz raporu üretir (metin olarak)."""
    symbol = symbol.upper().strip()
    try:
        ticker = bp.Ticker(symbol)
        df = ticker.history(period="1y", interval="1d")
    except Exception as e:
        return (
            f"❌ {symbol} için veri alınamadı.\n"
            f"Sembolün doğru olduğundan emin olun (örn. ASELSAN değil ASELS).\n"
            f"Hata: {e}"
        )

    if df is None or df.empty or len(df) < 60:
        return f"❌ {symbol} için yeterli veri bulunamadı."

    close = df["Close"]
    price = float(close.iloc[-1])

    rsi_series = calc_rsi(close)
    rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else None

    macd_line, signal_line, hist = calc_macd(close)
    macd_val = float(macd_line.iloc[-1])
    signal_val = float(signal_line.iloc[-1])
    hist_val = float(hist.iloc[-1])

    def ma(n):
        if len(close) < n:
            return None
        return float(close.rolling(n).mean().iloc[-1])

    mas = {
        "MA5": ma(5), "MA9": ma(9), "MA21": ma(21),
        "MA50": ma(50), "MA100": ma(100), "MA200": ma(200),
    }
    ema12 = float(close.ewm(span=12, adjust=False).mean().iloc[-1])
    ema26 = float(close.ewm(span=26, adjust=False).mean().iloc[-1])

    # Basit VWAP yaklaşımı (typical price ağırlıklı, son 20 gün)
    if "Volume" in df.columns:
        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        vwap = float((typical.tail(20) * df["Volume"].tail(20)).sum() / df["Volume"].tail(20).sum())
        vol_ratio = float(df["Volume"].iloc[-1] / df["Volume"].tail(20).mean())
    else:
        vwap, vol_ratio = None, None

    atr_series = calc_atr(df)
    atr = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else None

    support = float(df["Low"].tail(20).min())
    resistance = float(df["High"].tail(20).max())

    rsi_divergence = detect_divergence(close, rsi_series)
    macd_divergence = detect_divergence(close, hist)

    score, status = technical_score(rsi, hist_val, price, mas, vol_ratio)

    def fmt(v, digits=2):
        return f"{v:.{digits}f}" if v is not None else "-"

    report = (
        f"📊 {symbol} TEKNİK ANALİZ\n\n"
        f"💰 Fiyat: {fmt(price)} TL\n"
        f"RSI(14): {fmt(rsi, 1)}\n"
        f"MACD: {fmt(macd_val, 3)}\n"
        f"Sinyal: {fmt(signal_val, 3)}\n"
        f"Histogram: {fmt(hist_val, 3)}\n\n"
        f"📈 HAREKETLİ ORTALAMALAR\n"
        f"MA5: {fmt(mas['MA5'])}\n"
        f"MA9: {fmt(mas['MA9'])}\n"
        f"MA21: {fmt(mas['MA21'])}\n"
        f"MA50: {fmt(mas['MA50'])}\n"
        f"MA100: {fmt(mas['MA100'])}\n"
        f"MA200: {fmt(mas['MA200'])}\n\n"
        f"EMA12: {fmt(ema12)}\n"
        f"EMA26: {fmt(ema26)}\n\n"
        f"VWAP: {fmt(vwap)}\n"
        f"ATR: {fmt(atr)}\n"
        f"Hacim / 20 Ort.: {fmt(vol_ratio)}x\n\n"
        f"🔵 Destek: {fmt(support)}\n"
        f"🔴 Direnç: {fmt(resistance)}\n\n"
        f"🔀 RSI Uyumsuzluğu: {rsi_divergence}\n"
        f"🔀 MACD Uyumsuzluğu: {macd_divergence}\n\n"
        f"🎯 TEKNİK SKOR: {score}/100\n"
        f"📌 Durum: {status}\n\n"
        f"ℹ️ Bu skor teknik göstergelerin birleşimidir; kesin getiri garantisi değildir."
    )
    return report


# ---------------------------------------------------------------
# PİYASA TARAMASI
# ---------------------------------------------------------------

def get_buy_tier(rsi):
    for tier in TIERS:
        if rsi < tier["buy_rsi"]:
            return tier
    return None


def get_sell_tier(rsi):
    for tier in TIERS:
        if rsi > tier["sell_rsi"]:
            return tier
    return None


def run_scan(condition: str):
    try:
        df = bp.scan(UNIVERSE, condition, interval="15m")
    except Exception as e:
        print(f"Tarama hatası ({condition}): {e}")
        return []
    if df is None or len(df) == 0:
        return []
    results = []
    for _, row in df.iterrows():
        volume = row.get("volume", 0) or 0
        if volume < MIN_VOLUME:
            continue
        # Fiyat alanı borsapy sürümüne göre farklı adlarda gelebilir
        price = row.get("price")
        if price is None:
            price = row.get("close")
        if price is None:
            price = row.get("last")
        if price is None:
            price = row.get("close_price")
        results.append({
            "symbol": row.get("symbol"),
            "price": price,
            "rsi": row.get("rsi"),
        })
    return results


def build_scan_report() -> str:
    buy_hits = run_scan(BUY_CONDITION)
    sell_hits = run_scan(SELL_CONDITION)

    lines_by_tier = {t["name"]: [] for t in TIERS}

    for hit in buy_hits:
        rsi = hit["rsi"]
        if rsi is None:
            continue
        tier = get_buy_tier(rsi)
        if tier:
            lines_by_tier[tier["name"]].append(
                f"{tier['emoji']}{BUY_EMOJI} {escape_mdv2(str(hit['symbol']))} \\({escape_mdv2(str(round(rsi, 1)))}\\)"
            )

    for hit in sell_hits:
        rsi = hit["rsi"]
        if rsi is None:
            continue
        tier = get_sell_tier(rsi)
        if tier:
            lines_by_tier[tier["name"]].append(
                f"{tier['emoji']}{SELL_EMOJI} {escape_mdv2(str(hit['symbol']))} \\({escape_mdv2(str(round(rsi, 1)))}\\)"
            )

    parts = ["📡 *BIST TARAMA*"]
    any_found = False

    for tier in TIERS:
        if tier["name"] == "Zayıf":
            continue
        items = lines_by_tier[tier["name"]]
        if items:
            any_found = True
            shown = items[:20]
            extra = len(items) - len(shown)
            block = " · ".join(shown)
            if extra > 0:
                block += f" \\(\\+{extra}\\)"
            parts.append(block)

    weak_items = lines_by_tier["Zayıf"]
    if weak_items:
        any_found = True
        weak_text = " · ".join(weak_items[:40])
        extra = len(weak_items) - min(len(weak_items), 40)
        if extra > 0:
            weak_text += f" \\(\\+{extra}\\)"
        parts.append(f"⚪ {len(weak_items)} zayıf sinyal \\(görmek için dokun\\): ||{weak_text}||")

    if not any_found:
        parts.append("Şu anda sinyal yok\\.")

    parts.append(f"\n{BUY_EMOJI} AL  {SELL_EMOJI} SAT  🔥 Güçlü  🟡 Orta  ⚪ Zayıf")

    return "\n\n".join(parts)


def run_background_scan(state: dict, new_state: dict) -> list:
    """Otomatik taramada yeni sinyal oluşan hisseler için kısa bildirim mesajları üretir."""
    buy_hits = run_scan(BUY_CONDITION)
    sell_hits = run_scan(SELL_CONDITION)
    messages = []
    seen_symbols = set()

    for hit in buy_hits:
        symbol, rsi = hit["symbol"], hit["rsi"]
        if rsi is None:
            continue
        tier = get_buy_tier(rsi)
        if tier is None:
            continue
        seen_symbols.add(symbol)
        label = f"AL-{tier['name']}"
        if state.get(symbol) != label:
            line = f"{tier['emoji']}{BUY_EMOJI} {escape_mdv2(str(symbol))} \\({escape_mdv2(str(round(rsi,1)))}\\)"
            messages.append((tier["name"], line))
            new_state[symbol] = label

    for hit in sell_hits:
        symbol, rsi = hit["symbol"], hit["rsi"]
        if rsi is None:
            continue
        tier = get_sell_tier(rsi)
        if tier is None:
            continue
        seen_symbols.add(symbol)
        label = f"SAT-{tier['name']}"
        if state.get(symbol) != label:
            line = f"{tier['emoji']}{SELL_EMOJI} {escape_mdv2(str(symbol))} \\({escape_mdv2(str(round(rsi,1)))}\\)"
            messages.append((tier["name"], line))
            new_state[symbol] = label

    for symbol in list(new_state.keys()):
        if symbol.startswith("_"):
            continue
        if symbol not in seen_symbols:
            new_state[symbol] = None

    return messages


# ---------------------------------------------------------------
# KOMUT İŞLEME
# ---------------------------------------------------------------

def handle_command(text: str, chat_id: str, state: dict) -> None:
    text = text.strip()
    parts = text.split(maxsplit=1)
    command = parts[0].lower().split("@")[0]  # /analiz@botadi -> /analiz
    arg = parts[1] if len(parts) > 1 else ""

    if command == "/start":
        send_telegram_message("👋 Bot başlatıldı!\n\n" + HELP_TEXT, chat_id)
    elif command == "/yardim":
        send_telegram_message(HELP_TEXT, chat_id)
    elif command == "/durum":
        today = datetime.now(timezone.utc).date().isoformat()
        last_scan = state.get("_heartbeat_date", "henüz yok")
        send_telegram_message(
            f"✅ Bot çalışıyor.\n"
            f"Son otomatik tarama günü: {last_scan}\n"
            f"Şu anki UTC tarih: {today}\n"
            f"Tarama sıklığı: GitHub Actions ile ~5 dakikada bir",
            chat_id,
        )
    elif command == "/analiz":
        if not arg:
            send_telegram_message("Kullanım: /analiz THYAO", chat_id)
        else:
            send_telegram_message(analyze_symbol(arg), chat_id)
    elif command == "/tara":
        send_telegram_message(build_scan_report(), chat_id, parse_mode="MarkdownV2")
    else:
        send_telegram_message("❓ Tanınmayan komut.\n\n" + HELP_TEXT, chat_id)


def process_pending_commands(state: dict) -> None:
    offset = state.get("_update_offset", 0)
    updates = get_telegram_updates(offset)
    for update in updates:
        state["_update_offset"] = update["update_id"] + 1
        message = update.get("message")
        if not message:
            continue
        text = message.get("text", "")
        chat_id = str(message.get("chat", {}).get("id", ""))
        if text.startswith("/"):
            print(f"Telegram komutu: {text}")
            try:
                handle_command(text, chat_id, state)
            except Exception as e:
                print(f"Komut işleme hatası: {e}")
                send_telegram_message(f"⚠️ Bir hata oluştu: {e}", chat_id)


# ---------------------------------------------------------------
# ANA AKIŞ
# ---------------------------------------------------------------

def main():
    state = load_state()
    new_state = dict(state)

    # 1) Bekleyen komutları işle
    process_pending_commands(new_state)

    # 2) Otomatik piyasa taraması (Güçlü/Orta tek satırda, Zayıf dokunarak açılır)
    messages = run_background_scan(state, new_state)
    strong_medium = [m for name, m in messages if name in ("Güçlü", "Orta")]
    weak_lines = [m for name, m in messages if name == "Zayıf"]

    parts = []
    if strong_medium:
        parts.append(" · ".join(strong_medium))
    if weak_lines:
        weak_text = " · ".join(weak_lines)
        parts.append(f"⚪ {len(weak_lines)} zayıf sinyal \\(görmek için dokun\\): ||{weak_text}||")

    if parts:
        send_telegram_message(
            "📊 " + "\n\n".join(parts) + f"\n\n{BUY_EMOJI} AL  {SELL_EMOJI} SAT  🔥 Güçlü  🟡 Orta  ⚪ Zayıf",
            parse_mode="MarkdownV2",
        )
        print("Otomatik tarama: yeni sinyal bulundu, mesaj gönderildi.")
    else:
        print("Otomatik tarama: yeni sinyal yok.")

    # 3) Günlük "bot çalışıyor" özet mesajı
    today = datetime.now(timezone.utc).date().isoformat()
    if new_state.get("_heartbeat_date") != today:
        send_telegram_message(
            "✅ Bot bugün ilk kez çalıştı, sistem aktif ve piyasayı takip ediyor 👍"
        )
        new_state["_heartbeat_date"] = today

    save_state(new_state)


if __name__ == "__main__":
    main()
    
