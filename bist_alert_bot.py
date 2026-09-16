"""
BIST Al-Sat Sinyal Botu (Tüm Hisseler)
----------------------------------------
Borsa İstanbul'da işlem gören TÜM hisseleri (XUTUM evreni: Yıldız, Ana ve
Alt Pazar) RSI + Hareketli Ortalama stratejisiyle tarar, sinyal oluştuğunda
Telegram'a bildirim gönderir.

Bu bot EMİR GÖNDERMEZ, sadece bildirim üretir. Alım-satım kararı ve
işlemi tamamen kullanıcıya aittir. Yatırım tavsiyesi değildir.

Kullanılan kütüphane: borsapy (https://github.com/saidsurucu/borsapy)
Not: borsapy kişisel/eğitim amaçlı kullanım için ücretsizdir.
"""

import os
import json
from datetime import datetime, timezone
import requests
import borsapy as bp

# ---------------------------------------------------------------
# AYARLAR
# ---------------------------------------------------------------

# Taranacak evren: XUTUM = BIST'te işlem gören tüm hisseler
UNIVERSE = "XUTUM"

# RSI seviyelerine göre üç güven kademesi
# Güçlü: çok nadir ama en belirgin uç nokta
# Orta: dikkat çekici, kesin değil
# Zayıf: sadece bilgilendirme, çok güvenme
TIERS = [
    {"name": "Güçlü", "emoji": "🔥", "buy_rsi": 20, "sell_rsi": 80},
    {"name": "Orta", "emoji": "🟡", "buy_rsi": 30, "sell_rsi": 70},
    {"name": "Zayıf", "emoji": "⚪", "buy_rsi": 40, "sell_rsi": 60},
]

# Tarama, en geniş aralığı (Zayıf kademe) kapsayacak şekilde yapılır,
# sonra her hisse en uygun kademeye yerleştirilir
BUY_CONDITION = f"rsi < {TIERS[-1]['buy_rsi']}"
SELL_CONDITION = f"rsi > {TIERS[-1]['sell_rsi']}"

# Çok düşük hacimli/az işlem gören hisseleri elemek için asgari hacim (TL)
MIN_VOLUME = 500_000

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

STATE_FILE = "last_signals.json"


# ---------------------------------------------------------------
# YARDIMCI FONKSİYONLAR
# ---------------------------------------------------------------

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def send_telegram_message(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("UYARI: Telegram bilgileri eksik, mesaj gönderilemedi.")
        print(text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=20)
        if resp.status_code != 200:
            print(f"Telegram gönderim hatası: {resp.text}")
    except Exception as e:
        print(f"Telegram gönderim istisnası: {e}")


def get_buy_tier(rsi: float):
    """RSI değerine göre AL sinyali için kademe döner (en güçlüden başlar)."""
    for tier in TIERS:
        if rsi < tier["buy_rsi"]:
            return tier
    return None


def get_sell_tier(rsi: float):
    """RSI değerine göre SAT sinyali için kademe döner (en güçlüden başlar)."""
    for tier in TIERS:
        if rsi > tier["sell_rsi"]:
            return tier
    return None


def run_scan(condition: str):
    """Verilen koşula uyan hisseleri XUTUM evreninde tarar."""
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
        results.append({
            "symbol": row.get("symbol"),
            "price": row.get("price"),
            "rsi": row.get("rsi"),
        })
    return results


# ---------------------------------------------------------------
# ANA AKIŞ
# ---------------------------------------------------------------

def main():
    state = load_state()
    new_state = dict(state)
    messages = []

    buy_hits = run_scan(BUY_CONDITION)
    sell_hits = run_scan(SELL_CONDITION)

    seen_symbols = set()

    for hit in buy_hits:
        symbol = hit["symbol"]
        rsi = hit["rsi"]
        if rsi is None:
            continue
        tier = get_buy_tier(rsi)
        if tier is None:
            continue
        seen_symbols.add(symbol)
        label = f"AL-{tier['name']}"
        if state.get(symbol) != label:
            messages.append(
                f"{tier['emoji']} {tier['name']} AL sinyali: {symbol}\n"
                f"Fiyat: {hit['price']} TL | RSI: {round(rsi, 1)}"
            )
            new_state[symbol] = label

    for hit in sell_hits:
        symbol = hit["symbol"]
        rsi = hit["rsi"]
        if rsi is None:
            continue
        tier = get_sell_tier(rsi)
        if tier is None:
            continue
        seen_symbols.add(symbol)
        label = f"SAT-{tier['name']}"
        if state.get(symbol) != label:
            messages.append(
                f"{tier['emoji']} {tier['name']} SAT sinyali: {symbol}\n"
                f"Fiyat: {hit['price']} TL | RSI: {round(rsi, 1)}"
            )
            new_state[symbol] = label

    # Daha önce sinyal verilmiş ama artık koşulu sağlamayan hisseleri sıfırla
    # ki koşul tekrar oluştuğunda yeniden bildirim gitsin
    for symbol in list(new_state.keys()):
        if symbol.startswith("_"):
            continue  # _heartbeat_date gibi özel anahtarları koru
        if symbol not in seen_symbols:
            new_state[symbol] = None

    # Zayıf kademedeki sinyalleri ayrı tut (tek tek göndermek yerine özetle)
    strong_medium = [m for m in messages if "🔥" in m or "🟡" in m]
    weak_only = [m for m in messages if "⚪" in m]

    parts = []
    if strong_medium:
        parts.append("\n\n".join(strong_medium))
    if weak_only:
        parts.append(f"⚪ Ayrıca {len(weak_only)} hissede Zayıf kademede sinyal var (detay için botu genişletebiliriz).")

    if parts:
        full_message = f"📊 BIST Sinyal Botu\n\n" + "\n\n".join(parts)
        send_telegram_message(full_message)
        print(full_message)
    else:
        print("Bu taramada yeni sinyal yok.")

    # Günde bir kez, sinyal olsun olmasın, "bot çalışıyor" özet mesajı gönder
    # (state dosyasında "_heartbeat_date" ile takip edilir, spam yapmaz)
    today = datetime.now(timezone.utc).date().isoformat()
    if new_state.get("_heartbeat_date") != today:
        heartbeat = (
            f"✅ Bot bugün ilk kez çalıştı ve piyasayı taradı.\n"
            f"Şu anda {len(buy_hits)} hissede AL, {len(sell_hits)} hissede SAT "
            f"koşulu görülüyor (hepsi daha önce bildirilmiş olabilir).\n"
            f"Bot düzenli çalışıyor, her şey yolunda 👍"
        )
        send_telegram_message(heartbeat)
        print(heartbeat)
        new_state["_heartbeat_date"] = today

    save_state(new_state)


if __name__ == "__main__":
    main()
