"""
BIST TEKNİK ANALİZ + TELEGRAM SİNYAL BOTU

Mevcut özellikler:
- 15 dakikalık RSI AL/SAT taraması
- Yeni sinyal bildirimi
- Günlük çalışma bildirimi
- last_signals.json durum kaydı

Yeni özellikler:
- /start
- /sinyal
- /analiz HİSSE
- /tara
- RSI
- MACD
- MA 5/9/21/50/100/200
- EMA
- Bollinger Bands
- VWAP
- ATR
- OBV
- Hacim analizi
- Destek / direnç
- RSI uyumsuzluğu
- MACD uyumsuzluğu
- Trend
- Momentum
- 0-100 teknik skor

Telegram token ve Chat ID:
GitHub Actions Secrets üzerinden otomatik alınır.
Kod içine token yazılmaz.
"""

import os
import json
import time
from datetime import datetime, timezone

import requests
import borsapy as bp

from technical_analysis import analyze, format_report


# ============================================================
# AYARLAR
# ============================================================

UNIVERSE = "XUTUM"

STATE_FILE = "last_signals.json"

MIN_VOLUME = 500_000

TIERS = [
    {
        "name": "Güçlü",
        "emoji": "🔥",
        "buy_rsi": 20,
        "sell_rsi": 80,
    },
    {
        "name": "Orta",
        "emoji": "🟡",
        "buy_rsi": 30,
        "sell_rsi": 70,
    },
    {
        "name": "Zayıf",
        "emoji": "⚪",
        "buy_rsi": 40,
        "sell_rsi": 60,
    },
]

BUY_CONDITION = f"rsi < {TIERS[-1]['buy_rsi']}"
SELL_CONDITION = f"rsi > {TIERS[-1]['sell_rsi']}"


# ============================================================
# TELEGRAM
# ============================================================

# ÖNEMLİ:
# Bunlar GitHub Actions Secrets'tan gelir.
# Token ve Chat ID'yi buraya yazmana gerek yok.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def telegram_ready():
    return bool(
        TELEGRAM_BOT_TOKEN
        and TELEGRAM_CHAT_ID
    )


def telegram_url(method):
    return (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/"
        f"{method}"
    )


def send_telegram_message(text):
    """
    Telegram mesajını gönderir.

    Telegram yaklaşık 4096 karakterlik mesaj sınırına sahip.
    Uzun mesajları otomatik olarak parçalıyoruz.
    """

    if not telegram_ready():
        print("Telegram bilgileri bulunamadı.")
        print(text)
        return False

    # Güvenli mesaj uzunluğu
    chunks = []

    while len(text) > 3900:
        cut = text.rfind("\n", 0, 3900)

        if cut < 500:
            cut = 3900

        chunks.append(text[:cut])
        text = text[cut:].lstrip()

    if text:
        chunks.append(text)

    success = True

    for chunk in chunks:
        try:
            response = requests.post(
                telegram_url("sendMessage"),
                data={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": chunk,
                },
                timeout=30,
            )

            if response.status_code != 200:
                print(
                    "Telegram gönderim hatası:",
                    response.text
                )
                success = False

        except Exception as exc:
            print(
                "Telegram bağlantı hatası:",
                exc
            )
            success = False

    return success


# ============================================================
# STATE
# ============================================================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            data = json.load(file)

        if isinstance(data, dict):
            return data

    except Exception as exc:
        print(
            "State dosyası okunamadı:",
            exc
        )

    return {}


def save_state(state):
    try:
        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                state,
                file,
                ensure_ascii=False,
                indent=2
            )
    except Exception as exc:
        print(
            "State dosyası kaydedilemedi:",
            exc
        )


# ============================================================
# SAYISAL DEĞER YARDIMCILARI
# ============================================================

def safe_float(value, default=None):
    try:
        if value is None:
            return default

        result = float(value)

        if result != result:
            return default

        return result

    except Exception:
        return default


def safe_int(value, default=0):
    try:
        if value is None:
            return default

        result = int(float(value))

        return result

    except Exception:
        return default


# ============================================================
# RSI SİNYAL KADEMELERİ
# ============================================================

def get_buy_tier(rsi):
    rsi = safe_float(rsi)

    if rsi is None:
        return None

    for tier in TIERS:
        if rsi < tier["buy_rsi"]:
            return tier

    return None


def get_sell_tier(rsi):
    rsi = safe_float(rsi)

    if rsi is None:
        return None

    for tier in TIERS:
        if rsi > tier["sell_rsi"]:
            return tier

    return None


# ============================================================
# MEVCUT 15 DAKİKALIK RSI TARAMASI
# ============================================================

def run_scan(condition):
    """
    XUTUM evrenini 15 dakikalık RSI koşuluna göre tarar.
    """

    try:
        df = bp.scan(
            UNIVERSE,
            condition,
            interval="15m"
        )

    except Exception as exc:
        print(
            f"Tarama hatası ({condition}):",
            exc
        )
        return []

    if df is None or len(df) == 0:
        return []

    results = []

    for _, row in df.iterrows():

        volume = safe_float(
            row.get("volume"),
            0
        )

        if volume < MIN_VOLUME:
            continue

        symbol = row.get("symbol")

        if not symbol:
            continue

        results.append(
            {
                "symbol": str(symbol).upper(),
                "price": safe_float(
                    row.get("price")
                ),
                "rsi": safe_float(
                    row.get("rsi")
                ),
                "volume": volume,
            }
        )

    return results


# ============================================================
# /SİNYAL
# ============================================================

def signal_summary():

    buy_hits = run_scan(
        BUY_CONDITION
    )

    sell_hits = run_scan(
        SELL_CONDITION
    )

    lines = [
        "📡 BIST 15 DK SİNYAL TARAMASI",
        "",
        f"🟢 AL koşulu: {len(buy_hits)} hisse",
        f"🔴 SAT koşulu: {len(sell_hits)} hisse",
        "",
    ]

    if buy_hits:
        lines.append("🟢 AL SİNYALLERİ")

        for hit in buy_hits[:25]:

            rsi = hit["rsi"]

            if rsi is None:
                continue

            tier = get_buy_tier(rsi)

            if tier is None:
                continue

            price = hit["price"]

            price_text = (
                f"{price:.2f}"
                if price is not None
                else "-"
            )

            lines.append(
                f"{tier['emoji']} "
                f"{hit['symbol']} "
                f"| {price_text} TL "
                f"| RSI {rsi:.1f}"
            )

        lines.append("")

    if sell_hits:
        lines.append("🔴 SAT SİNYALLERİ")

        for hit in sell_hits[:25]:

            rsi = hit["rsi"]

            if rsi is None:
                continue

            tier = get_sell_tier(rsi)

            if tier is None:
                continue

            price = hit["price"]

            price_text = (
                f"{price:.2f}"
                if price is not None
                else "-"
            )

            lines.append(
                f"{tier['emoji']} "
                f"{hit['symbol']} "
                f"| {price_text} TL "
                f"| RSI {rsi:.1f}"
            )

        lines.append("")

    if not buy_hits and not sell_hits:
        lines.append(
            "ℹ️ Bu taramada RSI alarmı bulunamadı."
        )

    lines.append(
        "⚠️ RSI tek başına alım/satım kararı değildir."
    )

    return "\n".join(lines)


# ============================================================
# TEK HİSSE TEKNİK ANALİZ
# ============================================================

def analyze_symbol(symbol):

    symbol = (
        str(symbol)
        .strip()
        .upper()
        .replace("$", "")
    )

    if not symbol:
        return (
            "❌ Hisse kodu boş.\n"
            "Örnek: /analiz BSOKE"
        )

    # Kullanıcı BIST kodunu yanlışlıkla .IS yazarsa temizle
    if symbol.endswith(".IS"):
        symbol = symbol[:-3]

    try:

        result = analyze(
            symbol,
            period="1y",
            interval="1d"
        )

        if result is None:
            return (
                f"❌ {symbol} için analiz verisi alınamadı."
            )

        return format_report(result)

    except Exception as exc:

        print(
            f"{symbol} analiz hatası:",
            exc
        )

        return (
            f"❌ {symbol} analiz edilirken hata oluştu.\n\n"
            f"Hata: {exc}"
        )


# ============================================================
# /TARA
# ============================================================

def technical_scan():

    start_time = time.time()

    print("Teknik tarama başlıyor...")

    try:

        # Günlük veri üzerinden teknik tarama için
        # XUTUM evreninden sembolleri alıyoruz.
        df = bp.scan(
            UNIVERSE,
            "rsi >= 0",
            interval="1d"
        )

    except Exception as exc:

        print(
            "Teknik evren tarama hatası:",
            exc
        )

        return (
            "❌ BIST teknik taraması başlatılamadı.\n\n"
            f"Hata: {exc}"
        )

    if df is None or len(df) == 0:

        return (
            "❌ Teknik tarama için hisse bulunamadı."
        )

    symbols = []

    for _, row in df.iterrows():

        symbol = row.get("symbol")

        if not symbol:
            continue

        symbol = str(symbol).upper()

        if symbol not in symbols:
            symbols.append(symbol)

    print(
        f"Toplam {len(symbols)} hisse bulundu."
    )

    results = []

    for index, symbol in enumerate(symbols):

        try:

            print(
                f"[{index + 1}/{len(symbols)}] "
                f"{symbol}"
            )

            result = analyze(
                symbol,
                period="1y",
                interval="1d"
            )

            if result is None:
                continue

            score = safe_float(
                result.get("score"),
                50
            )

            price = safe_float(
                result.get("price")
            )

            rsi = safe_float(
                result.get("rsi")
            )

            results.append(
                {
                    "symbol": symbol,
                    "score": score,
                    "price": price,
                    "rsi": rsi,
                    "status": result.get(
                        "status",
                        "NÖTR / İZLE"
                    ),
                }
            )

        except Exception as exc:

            print(
                f"{symbol} atlandı:",
                exc
            )

            continue

    if not results:

        return (
            "❌ Hisselerin teknik verileri "
            "hesaplanamadı."
        )

    # Skora göre sırala
    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    elapsed = time.time() - start_time

    lines = [
        "📊 BIST TEKNİK TARAMA",
        "",
        f"📈 Analiz edilen: {len(results)} hisse",
        f"⏱ Süre: {elapsed:.1f} sn",
        "",
        "🔥 EN YÜKSEK TEKNİK SKORLAR",
        "",
    ]

    for item in results[:15]:

        score = item["score"]
        price = item["price"]
        rsi = item["rsi"]

        price_text = (
            f"{price:.2f}"
            if price is not None
            else "-"
        )

        rsi_text = (
            f"{rsi:.1f}"
            if rsi is not None
            else "-"
        )

        lines.append(
            f"• {item['symbol']} "
            f"| Skor: {score:.0f}/100 "
            f"| RSI: {rsi_text} "
            f"| {price_text} TL"
        )

    lines.extend(
        [
            "",
            "📉 EN DÜŞÜK TEKNİK SKORLAR",
            "",
        ]
    )

    worst = sorted(
        results,
        key=lambda x: x["score"]
    )

    for item in worst[:10]:

        score = item["score"]
        price = item["price"]
        rsi = item["rsi"]

        price_text = (
            f"{price:.2f}"
            if price is not None
            else "-"
        )

        rsi_text = (
            f"{rsi:.1f}"
            if rsi is not None
            else "-"
        )

        lines.append(
            f"• {item['symbol']} "
            f"| Skor: {score:.0f}/100 "
            f"| RSI: {rsi_text} "
            f"| {price_text} TL"
        )

    lines.extend(
        [
            "",
            "ℹ️ Skor; trend, momentum, RSI, MACD, "
            "hareketli ortalamalar, hacim ve diğer "
            "teknik göstergelerin bileşimidir.",
            "",
            "⚠️ Teknik skor kesin yükseliş/düşüş "
            "garantisi değildir.",
        ]
    )

    return "\n".join(lines)


# ============================================================
# TELEGRAM KOMUTLARI
# ============================================================

def get_updates(offset=None):

    if not telegram_ready():
        return []

    params = {
        "timeout": 1,
        "allowed_updates": json.dumps(
            ["message"]
        ),
    }

    if offset is not None:
        params["offset"] = offset

    try:

        response = requests.get(
            telegram_url("getUpdates"),
            params=params,
            timeout=10
        )

        if response.status_code != 200:
            print(
                "Telegram getUpdates hatası:",
                response.text
            )
            return []

        data = response.json()

        if not data.get("ok"):
            return []

        return data.get(
            "result",
            []
        )

    except Exception as exc:

        print(
            "Telegram update hatası:",
            exc
        )

        return []


def process_command(message, state):

    if not message:
        return

    chat = message.get(
        "chat",
        {}
    )

    chat_id = str(
        chat.get("id", "")
    )

    # Sadece bizim tanımlı Chat ID'miz
    # komut kullanabilsin.
    if TELEGRAM_CHAT_ID:

        if chat_id != str(
            TELEGRAM_CHAT_ID
        ):
            print(
                "Yetkisiz Telegram chat:",
                chat_id
            )
            return

    text = message.get(
        "text",
        ""
    )

    if not text:
        return

    text = text.strip()

    if not text.startswith("/"):
        return

    # Telegram komutlarının @bot kısmını temizle
    command_part = text.split()[0]

    command = (
        command_part
        .split("@")[0]
        .lower()
    )

    arguments = text.split()[1:]

    print(
        "Telegram komutu:",
        command,
        arguments
    )

    # --------------------------------------------------------
    # /START
    # --------------------------------------------------------

    if command == "/start":

        help_text = (
            "🤖 BIST TEKNİK ANALİZ BOTU\n"
            "\n"
            "Komutlar:\n"
            "\n"
            "📊 /analiz BSOKE\n"
            "Tek bir hissenin ayrıntılı günlük "
            "teknik analizini verir.\n"
            "\n"
            "🔎 /tara\n"
            "BIST hisselerini teknik skora göre tarar.\n"
            "\n"
            "📡 /sinyal\n"
            "15 dakikalık RSI sinyallerini gösterir.\n"
            "\n"
            "ℹ️ /start\n"
            "Bu yardım mesajını gösterir.\n"
            "\n"
            "Örnek:\n"
            "/analiz BSOKE\n"
            "\n"
            "⚠️ Bu bot yatırım tavsiyesi vermez."
        )

        send_telegram_message(
            help_text
        )

        return

    # --------------------------------------------------------
    # /SİNYAL
    # --------------------------------------------------------

    if command == "/sinyal":

        send_telegram_message(
            "⏳ 15 dakikalık BIST RSI taraması yapılıyor..."
        )

        result = signal_summary()

        send_telegram_message(
            result
        )

        return

    # --------------------------------------------------------
    # /ANALİZ
    # --------------------------------------------------------

    if command == "/analiz":

        if not arguments:

            send_telegram_message(
                "❌ Hisse kodu yazmalısın.\n\n"
                "Örnek:\n"
                "/analiz BSOKE"
            )

            return

        symbol = arguments[0]

        send_telegram_message(
            f"⏳ {symbol.upper()} teknik analizi hazırlanıyor..."
        )

        report = analyze_symbol(
            symbol
        )

        send_telegram_message(
            report
        )

        return

    # --------------------------------------------------------
    # /TARA
    # --------------------------------------------------------

    if command == "/tara":

        send_telegram_message(
            "⏳ BIST teknik taraması başladı.\n"
            "Hisseler tek tek analiz ediliyor..."
        )

        report = technical_scan()

        send_telegram_message(
            report
        )

        return

    # --------------------------------------------------------
    # BİLİNMEYEN KOMUT
    # --------------------------------------------------------

    send_telegram_message(
        "❓ Bilinmeyen komut.\n\n"
        "Komutları görmek için /start yaz."
    )


def process_telegram_commands(state):

    last_update_id = safe_int(
        state.get(
            "_telegram_update_id",
            0
        ),
        0
    )

    offset = (
        last_update_id + 1
        if last_update_id
        else None
    )

    updates = get_updates(
        offset=offset
    )

    if not updates:
        return state

    for update in updates:

        update_id = update.get(
            "update_id"
        )

        if update_id is None:
            continue

        if update_id <= last_update_id:
            continue

        message = update.get(
            "message"
        )

        if message:
            try:
                process_command(
                    message,
                    state
                )

            except Exception as exc:

                print(
                    "Komut işleme hatası:",
                    exc
                )

                try:
                    send_telegram_message(
                        "❌ Komut işlenirken hata oluştu:\n"
                        f"{exc}"
                    )
                except Exception:
                    pass

        last_update_id = update_id

        state[
            "_telegram_update_id"
        ] = last_update_id

        # Her update sonrasında kaydet.
        save_state(state)

    return state


# ============================================================
# NORMAL OTOMATİK SİNYAL SİSTEMİ
# ============================================================
def run_regular_alerts(state):

    new_state = dict(state)

    buy_hits = run_scan(
        BUY_CONDITION
    )

    sell_hits = run_scan(
        SELL_CONDITION
    )

    seen_symbols = set()

    messages = []

    # --------------------------------------------------------
    # AL
    # --------------------------------------------------------

    for hit in buy_hits:

        symbol = hit["symbol"]
        rsi = hit["rsi"]

        if rsi is None:
            continue

        tier = get_buy_tier(
            rsi
        )

        if tier is None:
            continue

        seen_symbols.add(
            symbol
        )

        label = (
            f"AL-{tier['name']}"
        )

        if state.get(symbol) != label:

            price = hit["price"]

            price_text = (
                f"{price:.2f}"
                if price is not None
                else "-"
            )

            messages.append(
                f"{tier['emoji']} "
                f"{tier['name']} AL sinyali\n"
                f"📌 {symbol}\n"
                f"💰 Fiyat: {price_text} TL\n"
                f"📊 RSI: {rsi:.1f}"
            )

            new_state[
                symbol
            ] = label

    # --------------------------------------------------------
    # SAT
    # --------------------------------------------------------

    for hit in sell_hits:

        symbol = hit["symbol"]
        rsi = hit["rsi"]

        if rsi is None:
            continue

        tier = get_sell_tier(
            rsi
        )

        if tier is None:
            continue

        seen_symbols.add(
            symbol
        )

        label = (
            f"SAT-{tier['name']}"
        )

        if state.get(symbol) != label:

            price = hit["price"]

            price_text = (
                f"{price:.2f}"
                if price is not None
                else "-"
            )

            messages.append(
                f"{tier['emoji']} "
                f"{tier['name']} SAT sinyali\n"
                f"📌 {symbol}\n"
                f"💰 Fiyat: {price_text} TL\n"
                f"📊 RSI: {rsi:.1f}"
            )

            new_state[
                symbol
            ] = label

    # --------------------------------------------------------
    # ARTIK KOŞULU SAĞLAMAYANLARI SIFIRLA
    # --------------------------------------------------------

    for symbol in list(
        new_state.keys()
    ):

        if symbol.startswith("_"):
            continue

        if symbol not in seen_symbols:

            new_state[
                symbol
            ] = None

    # --------------------------------------------------------
    # YENİ SİNYALLER
    # --------------------------------------------------------

    if messages:

        message = (
            "📊 BIST SİNYAL BOTU\n"
            "\n"
            + "\n\n".join(
                messages
            )
        )

        send_telegram_message(
            message
        )

        print(message)

    else:

        print(
            "Bu taramada yeni sinyal yok."
        )

    # --------------------------------------------------------
    # GÜNLÜK HEARTBEAT
    # --------------------------------------------------------

    today = datetime.now(
        timezone.utc
    ).date().isoformat()

    if new_state.get(
        "_heartbeat_date"
    ) != today:

        heartbeat = (
            "✅ BIST botu çalışıyor.\n\n"
            f"🟢 AL koşulu: "
            f"{len(buy_hits)} hisse\n"
            f"🔴 SAT koşulu: "
            f"{len(sell_hits)} hisse\n\n"
            "📡 Otomatik tarama aktif."
        )

        send_telegram_message(
            heartbeat
        )

        print(heartbeat)

        new_state[
            "_heartbeat_date"
        ] = today

    return new_state


# ============================================================
# ANA PROGRAM
# ============================================================

def main():

    print("=" * 60)
    print("BIST TEKNİK ANALİZ BOTU BAŞLADI")
    print("=" * 60)

    if telegram_ready():

        print(
            "Telegram bağlantısı: AKTİF"
        )

    else:

        print(
            "UYARI: Telegram Secrets bulunamadı."
        )

    state = load_state()

    # --------------------------------------------------------
    # ÖNCE TELEGRAM KOMUTLARINI KONTROL ET
    # --------------------------------------------------------

    state = process_telegram_commands(
        state
    )

    # --------------------------------------------------------
    # SONRA NORMAL 15 DK SİNYAL TARAMASI
    # --------------------------------------------------------

    try:

        state = run_regular_alerts(
            state
        )

    except Exception as exc:

        print(
            "Ana RSI taraması hatası:",
            exc
        )

        try:

            send_telegram_message(
                "⚠️ BIST botunda tarama hatası oluştu.\n\n"
                f"{exc}"
            )

        except Exception:
            pass

    # --------------------------------------------------------
    # SON DURUMU KAYDET
    # --------------------------------------------------------

    save_state(
        state
    )

    print("=" * 60)
    print("BIST BOTU TAMAMLANDI")
    print("=" * 60)


if __name__ == "__main__":
    main()
