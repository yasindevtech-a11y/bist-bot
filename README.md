# BIST Al-Sat Sinyal Botu — Telefon Üzerinden Kurulum

Bu bot bilgisayar gerektirmez. Kod GitHub'ın ücretsiz sunucularında (GitHub Actions)
çalışır, sen sadece Telegram'dan bildirim alırsın.

## 1. Telegram Bot Oluştur (2 dakika)

1. Telegram'da **@BotFather** hesabını bul, `/start` yaz.
2. `/newbot` komutunu gönder, botuna bir isim ver.
3. BotFather sana bir **token** verecek (örn. `123456:ABC-DEF...`). Bunu kaydet.
4. Şimdi kendi oluşturduğun bota git, herhangi bir mesaj yaz (örn. "merhaba").
5. Tarayıcıdan şu adresi aç (TOKEN yerine kendi token'ını yaz):
   `https://api.telegram.org/botTOKEN/getUpdates`
6. Çıkan JSON içinde `"chat":{"id": 123456789 ...}` kısmındaki sayıyı bul —
   bu senin **chat ID**'n.

## 2. GitHub Hesabı Aç ve Bu Kodu Yükle

1. [github.com](https://github.com) üzerinden ücretsiz hesap aç (telefon tarayıcısından yapılabilir).
2. Sağ üstten **New repository** ile yeni bir repo oluştur (adı önemli değil, örn. `bist-bot`), **Private** seç.
3. Bu klasördeki tüm dosyaları (bist_alert_bot.py, requirements.txt, .github klasörü, README.md)
   GitHub'ın web arayüzünden **"Add file → Upload files"** ile yükle. (Telefon tarayıcısından da yapılabilir.)

## 3. Telegram Bilgilerini GitHub'a Güvenli Şekilde Ekle

1. Repo sayfasında **Settings → Secrets and variables → Actions** yoluna git.
2. **New repository secret** ile iki secret ekle:
   - `TELEGRAM_BOT_TOKEN` → BotFather'dan aldığın token
   - `TELEGRAM_CHAT_ID` → 1. adımda bulduğun chat ID

## 4. Botu Aktif Et

1. Repo'da **Actions** sekmesine git.
2. "BIST Sinyal Botu" workflow'unu göreceksin — GitHub Actions dosyayı otomatik tanır.
3. İlk çalıştırmayı elle tetiklemek için **Run workflow** butonuna bas.
4. Çalışırsa Telegram'a (varsa sinyal) bildirim gelir. Sonrasında hafta içi
   10:00-18:10 arası her 15 dakikada bir otomatik çalışır — senin hiçbir şey
   yapmana gerek yok.

## Notlar

- Bu bot **sadece bildirim gönderir**, emir göndermez. Alım-satımı sen
  aracı kurum uygulamandan yapacaksın.
- **Kapsam:** Artık belirli birkaç hisse değil, BIST'te işlem gören
  **tüm hisseler** (XUTUM evreni — Yıldız, Ana ve Alt Pazar'ın tamamı)
  her taramada otomatik kontrol ediliyor. Veri kaynağı `borsapy`
  kütüphanesi (TradingView Screener API üzerinden, ~15 dakika gecikmeli).
- Strateji: RSI(14) aşırı alım/satım + 20 periyotluk hareketli ortalama
  kesişimi. `bist_alert_bot.py` içindeki `RSI_OVERSOLD`, `RSI_OVERBOUGHT`,
  `MA_PERIOD`, `MIN_VOLUME` değerlerini değiştirerek hassasiyeti
  ayarlayabilirsin. `MIN_VOLUME`, çok düşük hacimli/işlem görmeyen
  hisseleri elemek için var — düşürürsen daha fazla ama daha
  "gürültülü" sinyal alırsın.
- Tüm piyasayı taradığı için ilk günlerde beklenenden fazla bildirim
  gelebilir; `RSI_OVERSOLD`/`RSI_OVERBOUGHT` eşiklerini (örn. 25/75'e
  çekerek) daraltıp sinyal sıklığını azaltabilirsin.
- `borsapy` kütüphanesi kişisel ve eğitim amaçlı kullanım için
  ücretsizdir; ticari kullanım için Borsa İstanbul ile lisans
  görüşmesi gerekir (bkz. kütüphanenin GitHub sayfası).
- Bu bir yatırım tavsiyesi değildir, sinyaller garanti kâr anlamına
  gelmez. Kullanmadan önce bir süre sinyalleri gözlemleyip
  güvenilirliğini kendin değerlendirmen önerilir.
- Ücretsiz GitHub Actions'ın aylık kullanım limiti var (public
  repo'larda sınırsız, private repo'larda ~2000 dakika/ay ücretsiz) —
  15 dakikada bir çalışan bu bot bu limitin altında kalır.
