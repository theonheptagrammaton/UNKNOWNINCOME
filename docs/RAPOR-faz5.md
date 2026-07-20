# RAPOR — Faz 5: Strateji Motoru + Paper Trading + Trade Deck

Kapsam: `docs/PROJE_DOKUMANI.md` §8 + §9 + §10 + §15/Faz 5. Durum: **tamam** (2026-07-20).

## Ne yapıldı

### Strateji genome + değişmez sürümleme (§8.1–8.2)
- **Genome = `RunConfig` + ad** (`strategy/genome.py`). `backtest/config.py` zaten "§8.1
  genome ile ileri-uyumlu"; bu eşitlik sayesinde paper bot, backtest'in doğruladığı **aynı
  sinyal yolunu** koşar — ikinci, kayan bir kural motoru yok, paper↔backtest karşılaştırması
  bedava (§9.1). `genome_hash` (kanonik SHA-256) + `diff_genomes` (UI versiyon diff).
- **`strategies` + `strategy_versions`** (§11): her düzenleme yeni **değişmez** versiyon,
  `parent_version_id` soy ağacı + `source` (hangi run/scan). `active_version_id` = botun
  koşacağı versiyon; onu yeni satıra çevirmek = **hot-reload** (süreç değil, veri gerçeği).
- **"Convert to strategy" (§10.1):** backtest run **veya** discovery liderlik satırından;
  provenance + WFO raporu taşınır (`strategy/service.py`).

### Üç katmanlı düzenleme (§8.6)
- UI kural kurucu + **ham JSON editörü** (içe/dışa aktarma) → `POST /strategies/{id}/versions`,
  her kayıt yeni versiyon. **Python plugin yükleyici** (`strategy/plugins/`, `plugin_loader`,
  `plugin_registry`): `register(registry)` ile özel primitive ekler; kural motoru tanımadığı
  primitive'i registry'den çözer (`build_clause` fallback). Örnek: `pct_above`. Hot-reload:
  bot her tick aktif versiyonu okur + `POST /strategies/reload-plugins`.

### Paper doldurma + risk duvarı (§9.1, §9.3, §9.4)
- **`ExecutionAdapter` protokolü** (`place/cancel/positions/balance`) + `PaperAdapter`:
  fiyat + slippage + komisyon + funding tahakkuku, net tek-yön pozisyon; nakit muhasebesi
  backtest motoruyla birebir (paper↔backtest tutarlı). Aynı tablolara `mode=paper`.
- **`RiskLayer` = zorunlu duvar:** adaptör **name-mangled private**; `place_order`'a tek yol
  `submit`. Tüm §9.4 limitleri: ATR risk boyutlama (karar #4), maks eşzamanlı (5), günlük
  zarar (%3→gün durur), toplam DD (%15→kill), ardışık zarar soğuması (4→12h), fiyat sapma
  koruması (>%1), kaldıraç tavanı (10x/5x), **likidasyon tamponu** (liq ≥3×ATR değilse
  otomatik düşür, rule #11). Blok → `risk_events`; katman I/O'suz (bot yazar) → test edilebilir.

### Mod şalteri + kill switch (§9.6, §9.4)
- **Etkin mod = min(global, strateji)**, Off<Paper<Live (`bot/mode.py`). **LIVE Faz 7'ye kadar
  motor-reddi** (adaptör yok) — `execution_mode` asla "live" döndürmez, UI'da tooltip'li disabled.
- **Kill switch 4 kanal** (`bot/killswitch.py`): UI · `POST /api/bot/killswitch` · disk
  `KILLSWITCH` dosyası · Telegram `/kill`. İlk/ikinci/dördüncü kanal **paylaşılan veri
  volümündeki dosyayı** düşürür (api/worker ortak) → bot tek ucuz senkron kontrol ile dördünü
  de onurlandırır, ≤0.5 sn poll → <2 sn'de durur. Engaged → emir iptal + giriş yolu kapalı +
  `risk_event` + bildirim; pozisyonlar operatöre bırakılır.

### Paper bot motoru (§10.2)
- `bot/engine.py`: `tick()` deterministik bir döngü, `run()` denetimli kill-farkında sonsuz
  döngü (worker'da arka-plan asyncio görevi — **5 servis korunur**). Her tick: kill kontrolü →
  global mod → etkin modu ≥ paper her strateji için **aktif genome** yükle (hot-reload) → son
  kapanan barı değerlendir (`bot/signals.evaluate_latest`, `reason` + `indicator_snapshot`) →
  `RiskLayer` → `PaperAdapter` → signal/order/trade/equity/risk_event yaz. Fiyat kaynağı = son
  kapanış barı (canlı WS Faz 7). Restart'ta açık trade + equity'den rehydrate.

### Telegram (§10.3)
- `bot/telegram.py`: saf `handle_command` (whitelist-only, `/kill` & `/mode live` iki-adım,
  tümü `audit_log`) → offline test edilebilir. `/status /pnl /positions /mode paper|off
  [strateji] /kill`. Gerçek long-poll + `TelegramNotifier` yalnızca token varsa (operatör).

### API (§12) + UI (§10.2)
- `api/strategies.py` (from-run, list/get, versions GET+POST, diff, promote/pause/retire, mode,
  reload-plugins) + `api/bot.py` (start/stop, killswitch±clear, mode, portfolio, equity, signals,
  decisions, risk-events, audit, settings). Bot worker startup'ta başlar.
- **Trade Deck (`/trade`):** durum şeridi (büyük LIVE/PAPER/OFF şalteri + equity + günlük PnL +
  rejim + KILL SWITCH), portföy, sinyal akışı (reason + indicator_snapshot), strateji kartları
  (statü, kayan PF, mod şalteri, promote/pause/retire, **ham JSON genome editörü** + versiyon
  diff), karar günlüğü (risk-reddedilenler dahil), ayarlar (risk limitleri + terfi kapısı).
  Discovery liderliğinde **"Convert to strategy" aktif**.

## Kabul kriterleri — kanıt
| Kriter | Kanıt |
|---|---|
| Paper bot 72h kesintisiz | Worker asyncio döngüsü ("paper bot loop started"); `test_multi_cycle_soak_is_stable` (50 döngü, equity>0 sürekli). **72h sunucuda / 1h lokal soak = operatör plan-B** |
| Her sinyalde reason + snapshot | `test_signal_has_reason_and_indicator_snapshot`; canlı: `open_long` → `regime(ema,gt:0)` + `ema=66.33, close=69.88` |
| Kill switch 4 kanaldan <2 sn | `test_bot_killswitch` (dosya/api/ui/telegram parametrik → tick killed, emir yok, killswitch risk_event) + poll ≤0.5 sn; canlı API kanalı doğrulandı |
| Telegram mod geçişi + whitelist | `test_bot_telegram` (mode paper→off, iki-adım /kill engage, non-whitelist reject, tüm komut audit'li) |
| Genome hot-reload restart'sız | `test_genome_hot_reload_without_restart`; canlı: v2 kaydı aynı süreçte pozisyonu kapattı (open 1→0, close_long) |
| Risk limit bloklar + risk_events | `test_risk_limit_blocks_order_and_records_event` + `test_execution_risk` (11 test, tüm §9.4) + mimari: `test_no_bypass_adapter_is_private` |

Toplam: **pytest 155/155** (46 yeni), ruff temiz, `next build` başarılı (/trade 6.24 kB),
tsc + eslint temiz.

## Canlı doğrulama (Docker stack, 2026-07-20)
5 servis healthy + "paper bot loop started". `devseed BTCUSDT 1h` → always-long genome ile
backtest (1 işlem) → `POST /strategies/from-run` → strateji+global paper → **~8 sn sonra**:
`status` equity 9997.93 (komisyon/slippage), open_positions 1; `signals` → `open_long`,
reason=`regime(ema,gt:0)`, snapshot `ema/close`, outcome filled. `POST /bot/killswitch` →
killswitch=true + decision log'da `killswitch` risk olayı + audit `killswitch.engage`. Yeni
versiyon (JSON editör yolu) kaydedince bot restart'sız pozisyonu kapattı (open 1→0, `close_long`).

## Açık kararlar (kullanıcı onaylı)
1. **Genome = `RunConfig` + ad** — backtest'in doğruladığı aynı sinyal yolunu yeniden kullanır.
2. **Bot worker içinde arka-plan görevi** — yeni compose servisi yok, denetimli/restart-güvenli.
3. **Paper fiyatı = son kapanış barı** (pollled); gerçek WS akışı Faz 7'ye ertelendi.
4. **Telegram gerçek polling + 72h/1h soak = operatör plan-B** — saf komut/bildirim mantığı
   birim testli, deterministik lokal soak testli (Faz 1 & 4 deseniyle tutarlı).

## Yerel doğrulama (operatör)
```bash
python -m app.data.cli devseed --symbols BTCUSDT --tf 1h --bars 600   # SENTETİK
docker compose up --build                                            # 5 servis + bot loop
# backtest çalıştır → /trade veya Discovery'de "Convert to strategy" → strateji+global PAPER
# http://localhost:3000/trade → durum şeridi, sinyal akışı, strateji kartı, karar günlüğü
```
Not: `devseed` verisi SENTETİKTİR. LIVE şalteri UI'da görünür ama Faz 7'ye kadar devre dışı.
Telegram için `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` + `TELEGRAM_ENABLED=true` gerekir (operatör).
