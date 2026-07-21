# UNKNOWNINCOME — Claude Code Hafıza Dosyası

Otonom backtest + trading sistemi. Kaynak gerçek: `docs/PROJE_DOKUMANI.md` (v1.1) **+** `docs/PROJE_DOKUMANI-v2.md` (v2 eki — §20–§31, kural 13–20, Faz 8–14; v1.1'i geçersiz kılmaz, üstüne biner). **Çelişkide v2 kazanır.** Büyük her karardan önce ilgili bölümü oku. Fazlar ve kabul kriterleri: v1.1 §15 + v2 §22–§27 (yol haritası v2 §29). Açık kararlar ve varsayılanları: v1.1 §16.

**devseed SENTETİKTİR ve hiçbir kabul kriterini kapatamaz (kural 13).**

## Stack
- Backend: Python 3.11+ · FastAPI · arq + Redis · PostgreSQL (uygulama durumu)
- Piyasa verisi: Parquet dosyaları + DuckDB sorgu katmanı (`/data/parquet/{market}/{symbol}/{tf}.parquet`)
- Backtest: vectorbt (kütle tarama) + backtesting.py (finalist doğrulama) · Optuna (parametre)
- İndikatörler: TA-Lib + pandas-ta, tek registry arkasında (200+); custom eklenti: `backend/app/indicators/custom/`
- Frontend: Next.js 15 · TypeScript · Tailwind · lightweight-charts
- Veri/emir: ccxt — Binance USDT-M perpetual futures ilk adaptör (long+short, funding verisi dahil) · adapter pattern (`data/`, `execution/`)
- Deploy: Docker Compose → Coolify/VDS

## Pazarlıksız kurallar
1. Lookahead bias yasak: sinyal bar kapanışında, dolum sonraki bar açılışında. Testle koru.
2. Komisyon + slippage + funding (perpetual) varsayılan AÇIK; kapatılırsa raporda kırmızı etiket.
3. Strateji, walk-forward + OOS geçmeden "candidate" üstüne çıkamaz.
4. Canlı emir yolu terfi kapısı (§9.5) + kill switch olmadan çalışamaz — birim testiyle kanıtlı.
5. Timestamp'ler UTC; UI'da Europe/Istanbul'a çevrilir.
6. Her koşu config hash + seed ile tekrarlanabilir.
7. API anahtarları koda/loga/frontend'e sızmaz; withdraw yetkisiz anahtar varsayımı.
8. Çekirdek asset-agnostic; piyasa özel kod yalnızca `data/` ve `execution/` adaptörlerinde.
9. Type hint zorunlu; metrik + maliyet + sinyal primitifleri pytest'li.
10. Açık kararlarda (§16) varsayılanı uygula, alternatifi interface arkasında bırak. Dokümanda cevabı olmayan mimari soruda dur ve sor.
11. Kaldıraç: sert tavan 10x, güvenli varsayılan 5x, isolated marj; likidasyon fiyatı girişe ≥ 3×ATR mesafede değilse o işlem için otomatik düşür.
12. Dinamik evren tarihli snapshot'larla saklanır; backtest, test tarihindeki evreni kullanır (survivorship bias yasağı).

### Ek kurallar — v2 §21 (1–12 aynen geçerli, bunlar üstüne biner)
13. Sentetik veriyle kabul kriteri kapatılamaz. `devseed` bir geliştirme kolaylığıdır, kanıt değil; her kriter gerçek piyasa verisiyle tekrar doğrulanır.
14. Ham metrik tek başına terfi ettirmez. Her sıralamada ham Sharpe'ın yanında düzeltilmiş (deflated) değer görünür; terfi kararı düzeltilmiş değere bakar. Ham metrik UI'da "ham" etiketi taşır.
15. Gürültü testi zorunlu ve tekrarlıdır. Keşif hattı düzenli olarak rastgele yürüyüş verisine koşulur; gürültüden aday çıkıyorsa hat bozuktur ve kullanılmaz.
16. Risk portföy düzeyinde ölçülür. Hiçbir strateji tek başına değerlendirilmez; pozisyonlar sembol bazında netleştirilir; korelasyon bir tahsis girdisidir.
17. Kapasite bilinmeden ölçek büyütülmez. Her stratejinin doyum büyüklüğü tahmin edilir; tahmin yoksa büyütme yasaktır.
18. Her strateji ölümlüdür. Tanımlı bir yarı ömrü vardır ve tahsisini periyodik olarak yeniden hak etmek zorundadır.
19. Her ayar doğal dil açıklamasıyla doğar. Yeni bir config parametresi aynı commit'te §28 sözlüğüne üç satırla yazılır (ne yapar · yükseltirsen · düşürürsen); açıklaması olmayan ayar merge edilmez.
20. Canlı sapma ölçülmekle kalmaz, kapatılır. Tracking error eşiği aşarsa sistem otomatik Paper'a düşer ve bildirim gönderir.

## Dizin yapısı
```
backend/app/{api, core, data, indicators, backtest, discovery, strategy, execution, models, workers}
frontend/app/{backtest, trade}   # Sayfa 1: Backtest Lab · Sayfa 2: Trade Deck
```

## Komutlar
```
docker compose up --build        # tüm servisler
cd backend && pytest             # backend testleri
cd backend && ruff check .       # lint
cd frontend && pnpm dev          # UI geliştirme
```

## Çalışma disiplini
- Faz faz ilerle (doküman §15). Önce plan sun, onaydan sonra kodla.
- Faz sonunda kabul kriterlerini tek tek kanıtla; geçmeden sonraki faza başlama.
- Kapsam dışına çıkma; istenmemiş özellik ekleme.
- UI: dil İngilizce; karakter hibrit — Sessiz Lüks minimal kabuk (siyah/grafit, negatif alan, grotesk tipografi), veri-yoğun paneller; responsive.

## Alan kuralları (kısa)
- Strateji genome'ları JSON ve değişmez sürümlü (`strategy_versions`); soy ağacı korunur.
- Her sinyal `reason` + `indicator_snapshot` ile loglanır — şeffaflık pazarlıksızdır.
- Risk katmanı (doküman §9.4) bot ile adaptör arasındaki zorunlu duvardır; hiçbir emir atlayamaz.
- Kill switch dört kanal: UI butonu · `POST /api/bot/killswitch` · `KILLSWITCH` dosya bayrağı · Telegram `/kill` (whitelist chat, iki adımlı onay).
- PAPER/LIVE modu tek `ExecutionAdapter` arayüzü arkasında; bot kodu moddan habersizdir.
- Mod şalteri: global + strateji bazlı **Live/Paper/Off**; etkin mod ikisinin düşüğü (Off < Paper < Live). Sinyal başına onay yok.
- Strateji düzenleme üç katman (UI builder · JSON/YAML · Python plugin `strategy/plugins/`) aynı genome'a yazar; hot-reload; her değişiklik yeni değişmez versiyon.
- Telegram komutları: `/status` `/pnl` `/positions` `/mode` `/kill` — yalnızca whitelist chat ID.
