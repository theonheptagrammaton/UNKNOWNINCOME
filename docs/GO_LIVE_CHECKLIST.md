# Canlıya Geçiş Öncesi Kontrol Listesi

Bu liste **canlı sermaye** ile ilk emri göndermeden önce tek tek işaretlenir. Amaç
paranoya değil, geri alınamaz hataların kontrol edilebilir hatalara indirgenmesidir:
backtest'te bir bug rapor bozar, canlıda para götürür.

Doküman: `PROJE_DOKUMANI.md` §9.2–9.5, §13. Kural referansları `CLAUDE.md`.

> **Altın kural:** Bu listede tek bir kutu bile işaretsizse canlıya geçilmez.
> Aceleye getirilen tek adım, listenin tamamını geçersiz kılar.

---

## 0. Ön koşul — kapı gerçekten açık mı

- [ ] `GET /api/bot/gate?scope=global` → `passed: true`. **UI'da "Live readiness"
      kartı "Gate open" gösteriyor.** Kapalıysa `failures` listesindeki her madde
      kapatılmadan devam edilmez.
- [ ] Terfi kapısı eşikleri (§9.5) **düşürülmedi**. Ayarlar panelindeki değerler
      varsayılanlarla karşılaştırıldı: ≥30 gün, ≥30 işlem, PF ≥ 1,3, MaxDD ≤ %10.
      *Kapıyı geçmek için kapıyı alçaltmak, kapıyı kaldırmaktır.*
- [ ] Paper sicili **kesintisiz** ve gerçek canlı fiyat akışıyla üretildi (arada
      durdurulup yeniden başlatılan, boşluklu bir sicil değil).
- [ ] Canlı-paper sapma paneli (`Live vs paper`) makul: tracking error dar,
      korelasyon yüksek. Sapma zaten genişse canlıya geçmek sapmayı büyütür.

## 1. Borsa hesabı ve anahtarlar (§13)

- [ ] API anahtarı **yalnızca okuma + futures işlem** yetkili.
- [ ] **Withdraw (çekim) yetkisi KAPALI** — pazarlıksız. Borsa panelinden gözle doğrulandı.
- [ ] Borsa tarafında **IP whitelist** açık ve yalnızca VDS IP'si ekli.
- [ ] Anahtarlar **yalnızca Ayarlar UI'ından** girildi; repoda, `.env`'de, shell
      geçmişinde veya bir mesajlaşma uygulamasında anahtar **yok**.
- [ ] `SECRETS_KEY` env'de tanımlı, güçlü ve **yedeklenmiş** (kaybedilirse saklı
      anahtarlar çözülemez; sistem sessizce değil, hata vererek durur).
- [ ] `GET /api/bot/keys` yalnızca `····last4` maskesi dönüyor — düz metin dönmüyor.
- [ ] Testnet'ten mainnet'e geçerken anahtarlar **yeniden girildi** (testnet anahtarı
      mainnet'te çalışmaz; sessiz auth hatası en kötü keşif anıdır).

## 2. Sermaye ve risk sınırları (§9.4)

- [ ] Hesapta **yalnızca kaybedilmesi göze alınan** sermaye var. Bu satır bir
      formalite değil: sistem otonom işler ve gece 03:00'te sizi uyandırmaz.
- [ ] İlk açılış **mikro sermaye** ile. Ölçek büyütme, canlıda en az bir tam
      haftalık sorunsuz koşudan sonra tartışılır.
- [ ] `per_trade_pct` (varsayılan %1) gözden geçirildi.
- [ ] `max_daily_loss_pct` (%3) ve `max_total_drawdown_pct` (%15) doğru — ikincisi
      kill switch tetikler.
- [ ] `max_concurrent_positions` (5) ve ardışık zarar soğuması (4 zarar → 12 saat) aktif.
- [ ] `price_deviation_pct` (%1) fiyat sapma koruması açık.
- [ ] **Kaldıraç:** sert tavan 10x aşılmıyor, strateji varsayılanı 5x. Tavanı
      kullanmak hakkınız; 10x'te ~%10'luk ters hareketin likidasyon bölgesi olduğunu
      bilerek kullanın.
- [ ] **Marj modu isolated**, pozisyon modu **one-way** — testnet loglarında doğrulandı.
- [ ] Likidasyon tamponu (≥ 3×ATR) açık; derating olayları `risk_events`'e düşüyor.

## 3. Maliyet modeli (kural #2)

- [ ] Komisyon + slippage + **funding** açık. Kapalıysa bu liste geçersizdir.
- [ ] Komisyon oranı borsadaki gerçek kademeyle (VIP seviyesi, BNB indirimi) uyumlu.
- [ ] Funding maliyeti perpetual için hesaba katılıyor — long taşımanın sessiz gideri.

## 4. Testnet kanıtı (Faz 7 kabul)

- [ ] `python -m scripts.testnet_smoke --symbol BTCUSDT --qty 0.001 --leverage 5`
      çalıştırıldı ve **long + short round trip PASS**.
- [ ] Loglarda `set_margin_mode(isolated)` ve `set_leverage(N)` satırları görüldü.
- [ ] Venue'dan okunan pozisyonda kaldıraç ve marj modu beklenen değerde.
- [ ] Smoke çıktısında **anahtar izi yok** (redaksiyon filtresi çalışıyor).
- [ ] Testnet'te pozisyon **kapandı** — açık kalan mikro pozisyon bırakılmadı.

## 5. Kill switch — dört kanal da denendi (§9.4)

Hepsi **canlıya geçmeden önce** tek tek test edilir. Panik anında ilk kez denemek geç kalmaktır.

- [ ] UI'daki kill butonu (onaylı iki adım) çalışıyor.
- [ ] `POST /api/bot/killswitch` çalışıyor.
- [ ] Diskteki `KILLSWITCH` dosya bayrağı algılanıyor.
- [ ] Telegram `/kill` (whitelist chat, iki adımlı onay) çalışıyor.
- [ ] Kill sonrası: açık emirler iptal, yeni emir yolu kapalı, pozisyon kararı
      kullanıcıya soruluyor.
- [ ] Kill switch'i **temizlemeyi** de denediniz (tek yönlü bir kapı değil).

## 6. Operasyon ve gözlem

- [ ] Telegram bildirimleri çalışıyor; chat ID whitelist'i doğru.
- [ ] `/status`, `/pnl`, `/positions`, `/mode` komutları yanıt veriyor.
- [ ] VDS saati NTP ile senkron (imza zaman damgası hatası = sessiz emir reddi).
- [ ] Postgres yedeği alınıyor; `strategy_versions` ve `trades` kaybı geri alınamaz.
- [ ] Loglar toplanıyor ve **anahtar sızıntısı için tarandı** (`test_secrets.py`
      yeşil ve üretim logunda gözle kontrol yapıldı).
- [ ] Devre kesici ayarları (`live_max_retries`, breaker eşiği/cooldown) gözden geçirildi.
- [ ] Borsa bakım/duruş duyuruları kontrol edildi.

## 7. Mod şalteri — son adım (§9.6)

- [ ] Global şalter ve strateji şalteri **bilinçli** olarak LIVE'a alındı.
- [ ] Etkin modun ikisinin **düşüğü** olduğu anlaşıldı (global Paper → hiçbir
      strateji Live işlemez).
- [ ] Mod geçişi `audit_log`'a yazıldı ve Telegram bildirimi geldi.
- [ ] İlk 24 saat **aktif gözlem** altında: ilk birkaç emir gözle takip edilecek.

---

## İlk canlı işlemden sonra — 24 saatlik gözlem

- [ ] İlk dolum fiyatı beklenen aralıkta (slippage varsayımı gerçekle uyumlu).
- [ ] Komisyon ve funding kesintileri hesaplananla eşleşiyor.
- [ ] Emir-durum mutabakatı tutuyor: borsadaki pozisyon = lokal state.
- [ ] Tracking error paneli canlı-paper sapmasını makul gösteriyor.
- [ ] `risk_events` beklenmedik derating/red üretmiyor.

## Geri çekilme (rollback) planı

Aşağıdakilerden **biri** olursa mod derhal Paper'a alınır ve sebep bulunana kadar
geri dönülmez:

1. Emir-durum mutabakatı tutmuyor (borsa ile lokal state ayrışmış).
2. Tracking error paper'a göre belirgin ve kalıcı biçimde genişledi.
3. Beklenmeyen likidasyon derating'i veya marj/kaldıraç modu sapması.
4. Devre kesici tekrar tekrar açılıyor (borsa erişimi güvenilmez).
5. Günlük zarar limitine ilk gün ulaşıldı.
6. Loglarda anahtar izi bulundu → **anahtarlar derhal borsada iptal edilir**, sonra araştırılır.

> Paper'a dönmek başarısızlık değildir; kapıyı zorlamak başarısızlıktır.
