/* eslint-disable react/no-unescaped-entities -- Turkish prose uses ' as a literal suffix separator (Lab'a, config'i); escaping every one hurts readability with no benefit. */
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Backtest Lab — Kılavuz",
  description: "Backtest Lab'ı sıfırdan, adım adım kullanma rehberi (Türkçe)",
};

/* ─────────────────────────── küçük yardımcı bileşenler ─────────────────────────── */

function Section({
  id,
  n,
  title,
  children,
}: {
  id: string;
  n: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-24 flex flex-col gap-4 border-t border-line pt-10">
      <h2 className="flex items-baseline gap-3 text-2xl font-semibold tracking-tight">
        <span className="font-mono text-sm text-paper">{n}</span>
        {title}
      </h2>
      <div className="flex flex-col gap-4 text-[15px] leading-relaxed text-fog-muted">
        {children}
      </div>
    </section>
  );
}

function Callout({
  kind = "info",
  title,
  children,
}: {
  kind?: "info" | "warn" | "tip" | "rule";
  title?: string;
  children: React.ReactNode;
}) {
  const styles: Record<string, string> = {
    info: "border-line bg-graphite",
    warn: "border-loss/50 bg-loss/10",
    tip: "border-profit/40 bg-profit/10",
    rule: "border-paper/40 bg-paper/10",
  };
  const icon: Record<string, string> = { info: "ℹ️", warn: "⚠️", tip: "✅", rule: "📌" };
  return (
    <div className={`flex flex-col gap-1 rounded-md border px-4 py-3 text-sm ${styles[kind]}`}>
      {title && (
        <span className="flex items-center gap-2 font-semibold text-fog">
          <span>{icon[kind]}</span>
          {title}
        </span>
      )}
      <div className="text-fog-muted">{children}</div>
    </div>
  );
}

/** Vurgulanmış anahtar kelime / arayüz etiketi. */
function K({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded bg-graphite-2 px-1.5 py-0.5 font-mono text-[13px] text-fog">
      {children}
    </span>
  );
}

function Field({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1 rounded-md border border-line bg-graphite px-4 py-3 sm:grid-cols-[160px_1fr] sm:gap-4">
      <span className="font-mono text-sm text-paper">{name}</span>
      <span className="text-sm text-fog-muted">{children}</span>
    </div>
  );
}

function TocLink({ href, label }: { href: string; label: string }) {
  return (
    <li>
      <a href={href} className="text-fog-muted transition-colors hover:text-fog">
        {label}
      </a>
    </li>
  );
}

/* ─────────────────────────────────── sayfa ─────────────────────────────────── */

export default function BacktestTutorialPage() {
  return (
    <div className="flex flex-col gap-10">
      {/* Başlık */}
      <header className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <span className="text-xs uppercase tracking-[0.3em] text-fog-faint">
            Backtest Lab · Kullanım Kılavuzu
          </span>
          <Link
            href="/backtest"
            className="rounded border border-line px-3 py-1.5 text-sm text-fog-muted transition-colors hover:border-fog-faint hover:text-fog"
          >
            ← Backtest Lab'a dön
          </Link>
        </div>
        <h1 className="text-4xl font-semibold tracking-tight">Backtest Lab nasıl kullanılır?</h1>
        <p className="max-w-3xl text-[15px] leading-relaxed text-fog-muted">
          Bu sayfa Backtest Lab'ın <strong className="text-fog">her butonunu, her kutusunu ve
          her sonucu</strong> hiç bilmeyen birine anlatır gibi, adım adım açıklar. Acele etme;
          baştan sona bir kez oku, sonra sayfayı açıp birlikte dene. Hiçbir teknik bilgi
          varsaymıyoruz.
        </p>
        <Callout kind="info" title="En kısa özet (bir cümle)">
          Backtest = “Bu alım–satım kuralını <em>geçmiş fiyat verisi</em> üzerinde çalıştırsaydım
          ne olurdu?” sorusunu, gerçek para riske atmadan, komisyon/kayma/funding dâhil
          hesaplayan bir zaman makinesidir.
        </Callout>
      </header>

      {/* İçindekiler */}
      <nav className="rounded-md border border-line bg-graphite px-5 py-4">
        <span className="text-xs uppercase tracking-[0.2em] text-fog-faint">İçindekiler</span>
        <ol className="mt-3 grid list-none grid-cols-1 gap-x-8 gap-y-1.5 text-sm sm:grid-cols-2">
          <TocLink href="#nedir" label="0 · Backtest nedir, neden var?" />
          <TocLink href="#basla" label="1 · Başlamadan önce: veri şart" />
          <TocLink href="#akis" label="2 · Büyük resim: 3 adımlık akış" />
          <TocLink href="#evren" label="3 · Evren: Sembol, Zaman Dilimi, Yön, Seed" />
          <TocLink href="#indikator" label="4 · İndikatörler ve “operand” kavramı" />
          <TocLink href="#kural" label="5 · Kurallar (giriş/çıkış sinyalleri)" />
          <TocLink href="#primitif" label="6 · 6 sinyal primitifi tek tek" />
          <TocLink href="#maliyet" label="7 · Maliyetler: komisyon, kayma, funding" />
          <TocLink href="#sermaye" label="8 · Sermaye: bakiye, pozisyon %, kaldıraç" />
          <TocLink href="#calistir" label="9 · Çalıştır ve durumlar" />
          <TocLink href="#sonuc" label="10 · Sonuçları okuma: metrikler" />
          <TocLink href="#grafik" label="11 · Grafikler ve işlem tablosu" />
          <TocLink href="#ornek" label="12 · Baştan sona örnek" />
          <TocLink href="#hata" label="13 · Sık hatalar ve ipuçları" />
          <TocLink href="#altin" label="14 · Altın kurallar" />
        </ol>
      </nav>

      {/* 0 — Nedir */}
      <Section id="nedir" n="0" title="Backtest nedir, neden var?">
        <p>
          Diyelim ki aklında bir fikir var: “Fiyat, kısa vadeli ortalamasını yukarı kestiğinde
          <strong className="text-fog"> al</strong>, aşağı kestiğinde <strong className="text-fog">sat</strong>.”
          Bu fikir kâr ettirir mi? Bilmiyorsun. İki yol var:
        </p>
        <ul className="ml-5 list-disc space-y-1">
          <li>
            <strong className="text-loss">Kötü yol:</strong> Gerçek parayla dene, aylarca bekle,
            belki batır.
          </li>
          <li>
            <strong className="text-profit">İyi yol:</strong> Geçmiş fiyatları al, kuralını o
            veriler üzerinde “sanki canlıymış gibi” çalıştır ve sonucu gör. İşte bu{" "}
            <strong className="text-fog">backtest</strong>.
          </li>
        </ul>
        <p>
          Backtest Lab, bu ikinci yolu yapan sayfadır. Sen bir strateji tarif edersin (hangi
          indikatörler, hangi kurallar), sistem geçmiş mumların üstünde işlemleri simüle eder ve
          sana “ne kadar kazandırırdı, ne kadar riskliydi” diye rapor verir.
        </p>
        <Callout kind="warn" title="Önemli: Geçmiş, geleceğin garantisi değildir">
          İyi bir backtest sonucu, stratejinin gelecekte de kâr edeceğini <em>garanti etmez</em>.
          Sadece “bu fikir geçmişte mantıklı mıydı?” sorusunu yanıtlar. Bu yüzden sistemde ayrıca
          walk-forward, paper (kâğıt üstü) mod ve terfi kapıları vardır — canlıya geçmek uzun bir
          yoldur.
        </Callout>
      </Section>

      {/* 1 — Başla */}
      <Section id="basla" n="1" title="Başlamadan önce: veri şart">
        <p>
          Zaman makinesinin çalışması için “geçmiş” gerekir. Yani backtest yapmadan önce ilgili
          sembolün fiyat verisinin sisteme yüklenmiş olması lazım. Sayfanın sağ üstünde şuna
          benzer bir yazı görürsün:
        </p>
        <div className="rounded-md border border-line bg-graphite px-4 py-3 font-mono text-sm text-fog-faint">
          225 indicators · 5 data series
        </div>
        <ul className="ml-5 list-disc space-y-1">
          <li>
            <K>indicators</K> — kullanabileceğin toplam indikatör sayısı (örn. 225). Bu her zaman
            doludur.
          </li>
          <li>
            <K>data series</K> — yüklü fiyat serisi sayısı (sembol × zaman dilimi). Eğer burası{" "}
            <K>0</K> ise, henüz veri yok demektir ve <K>Symbol</K> kutusunda seçenek çıkmaz.
          </li>
        </ul>
        <Callout kind="tip" title="Veri yoksa ne yapılır?">
          Veri yükleme bir operatör adımıdır (Binance'ten indirme). Örneğin BTCUSDT için 5m/15m/1h/4h
          verisi yüklüyse, <K>Symbol</K> kutusuna BTCUSDT yazıp o zaman dilimlerini seçebilirsin.
          Data series <K>0</K> ise önce veri yüklenmelidir.
        </Callout>
      </Section>

      {/* 2 — Akış */}
      <Section id="akis" n="2" title="Büyük resim: 3 adımlık akış">
        <p>Her backtest aynı üç adımdan geçer. Sayfayı da yukarıdan aşağıya bu sırayla doldurursun:</p>
        <div className="grid gap-3 sm:grid-cols-3">
          {[
            ["1 · Tarif et", "Sembol/zaman dilimini seç, indikatörleri ekle, giriş–çıkış kurallarını yaz, maliyet ve sermayeyi ayarla."],
            ["2 · Çalıştır", "“Run backtest” butonuna bas. Sistem kuyruğa alır, işçi (worker) simülasyonu koşar."],
            ["3 · Oku", "Metrikler, grafikler ve işlem tablosu gelir. Yorumla, kuralını değiştir, tekrar çalıştır."],
          ].map(([t, d]) => (
            <div key={t} className="flex flex-col gap-1 rounded-md border border-line bg-graphite px-4 py-3">
              <span className="font-mono text-sm text-paper">{t}</span>
              <span className="text-sm text-fog-muted">{d}</span>
            </div>
          ))}
        </div>
        <p>
          Bu döngüyü istediğin kadar tekrar edersin: tarif et → çalıştır → oku → düzelt. Backtest
          “deneme yanılma” işidir; ilk seferde mükemmel strateji beklenmiyor.
        </p>
      </Section>

      {/* 3 — Evren */}
      <Section id="evren" n="3" title="Evren: Sembol, Zaman Dilimi, Yön, Seed">
        <p>
          Sayfanın en üstündeki dört kutu, testin “hangi piyasada, hangi çözünürlükte, hangi
          yönde” koşacağını belirler.
        </p>
        <Field name="Symbol">
          Test edilecek varlık, örn. <K>BTCUSDT</K> (Bitcoin / USDT vadeli). Kutuya yazmaya
          başlayınca yüklü semboller açılır. Yalnızca verisi olan sembolü seçebilirsin.
        </Field>
        <Field name="Timeframe">
          Mum periyodu: <K>1m</K>, <K>5m</K>, <K>15m</K>, <K>1h</K>, <K>4h</K>, <K>1d</K>. Her
          “mum” bir zaman dilimidir. <K>1h</K> = her mum 1 saat. Küçük zaman dilimi = çok işlem +
          çok gürültü; büyük zaman dilimi = az işlem + daha net trend. Seçtiğin zaman diliminin
          verisi yüklü olmalı.
        </Field>
        <Field name="Direction">
          İşlem yönü:
          <ul className="ml-5 mt-1 list-disc space-y-0.5">
            <li><K>long</K> — sadece <strong className="text-profit">alış</strong> (fiyat yükselince kazan).</li>
            <li><K>short</K> — sadece <strong className="text-loss">açığa satış</strong> (fiyat düşünce kazan).</li>
            <li><K>both</K> — ikisi de açık; kurallara göre hem long hem short girer.</li>
          </ul>
          <span className="mt-1 block">
            Not: <K>long</K> seçersen short kuralların yok sayılır (ve tersi). Emin değilsen{" "}
            <K>both</K> ile başla.
          </span>
        </Field>
        <Field name="Seed">
          “Rastgelelik tohumu”. Bazı hesaplar (örn. bazı iç örneklemeler) rastgelelik içerir. Seed
          sabit olduğu için <strong className="text-fog">aynı config + aynı seed → birebir aynı
          sonuç</strong> verir. Yani sonucu bir başkası aynı ayarlarla tekrar üretebilir. Genelde
          varsayılan (<K>42</K>) yeter.
        </Field>
        <Callout kind="rule" title="Lookahead (geleceği görme) yasağı">
          Sinyal her zaman mumun <strong className="text-fog">kapanışında</strong> üretilir, işlem
          ise <strong className="text-fog">bir sonraki mumun açılışında</strong> dolar. Yani sistem
          asla “geleceği bilerek” işlem yapmaz — bu gerçekçiliğin ve dürüstlüğün temelidir.
        </Callout>
      </Section>

      {/* 4 — İndikatörler */}
      <Section id="indikator" n="4" title="İndikatörler ve “operand” kavramı">
        <p>
          İndikatör, ham fiyattan hesaplanan bir yardımcı çizgidir (ortalama, momentum, oynaklık…).
          Kuralların bu çizgilere bakar. Önce indikatörü <strong className="text-fog">eklersin</strong>,
          sonra kuralda ona <strong className="text-fog">referans verirsin</strong>.
        </p>
        <p>
          <K>Indicators</K> bölümünde <K>+ indicator</K> ile yeni satır eklersin. Her satırda:
        </p>
        <Field name="key">
          İndikatörün <strong className="text-fog">takma adı</strong> — kuralların bu adı kullanır.
          Örn. hızlı ortalamaya <K>ema_fast</K>, yavaşa <K>ema_slow</K> diyebilirsin. İstediğin ismi
          verebilirsin; kısa ve anlamlı olsun.
        </Field>
        <Field name="indicator">
          Gerçek indikatörü seçtiğin açılır liste (aranabilir). Örn. <K>ema</K> (üssel hareketli
          ortalama), <K>rsi</K>, <K>atr</K>, <K>macd</K>, <K>bbands</K>… 200+ seçenek var.
        </Field>
        <Field name="parametreler">
          Seçtiğin indikatöre göre otomatik çıkan kutular. Örn. <K>ema</K> için <K>timeperiod</K>{" "}
          (kaç mumun ortalaması). <K>ema_fast</K> = 9, <K>ema_slow</K> = 21 klasik bir ikilidir.
        </Field>
        <p>Sağdaki <K>✕</K> ile indikatör satırını silersin.</p>

        <Callout kind="info" title="“Operand” ne demek? (çok önemli)">
          Operand = bir kuralın <em>karşılaştırdığı şey</em>. İki tür operand vardır:
          <ul className="ml-5 mt-1 list-disc space-y-0.5">
            <li>
              <strong className="text-fog">Fiyat alanları:</strong> <K>open</K>, <K>high</K>,{" "}
              <K>low</K>, <K>close</K>, <K>volume</K> — her zaman hazırdır.
            </li>
            <li>
              <strong className="text-fog">İndikatör anahtarları:</strong> eklediğin her{" "}
              <K>key</K> (örn. <K>ema_fast</K>). Kuralda operand olarak seçebilirsin.
            </li>
          </ul>
        </Callout>
        <Callout kind="warn" title="Tek çıktı vs. çok çıktı (dikkat!)">
          Bazı indikatörlerin tek çıktısı vardır (örn. EMA → tek çizgi). Bunlara doğrudan{" "}
          <K>key</K> adıyla ulaşırsın: <K>ema_fast</K>. Bazılarının birden çok çıktısı vardır (örn.
          MACD → <K>macd</K>, <K>macdsignal</K>, <K>macdhist</K>). Bunlarda operand{" "}
          <K>key.çıktı</K> şeklindedir: <K>macd_ind.macd</K>, <K>macd_ind.macdsignal</K>. Yani
          çok-çıktılı bir indikatörde <strong className="text-fog">çıplak key</strong> operand
          olarak <em>bulunmaz</em>.
        </Callout>
      </Section>

      {/* 5 — Kurallar */}
      <Section id="kural" n="5" title="Kurallar: giriş ve çıkış sinyalleri">
        <p>
          Kurallar, “ne zaman gir, ne zaman çık” kararını verir. Dört ayrı liste vardır:
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          {[
            ["Long entry", "Long (alış) pozisyonu AÇ.", "profit"],
            ["Long exit", "Açık long pozisyonu KAPAT.", "fog"],
            ["Short entry", "Short (açığa satış) pozisyonu AÇ.", "loss"],
            ["Short exit", "Açık short pozisyonu KAPAT.", "fog"],
          ].map(([t, d, c]) => (
            <div key={t} className="flex flex-col gap-1 rounded-md border border-line bg-graphite px-4 py-3">
              <span className={`font-mono text-sm ${c === "profit" ? "text-profit" : c === "loss" ? "text-loss" : "text-fog"}`}>
                {t}
              </span>
              <span className="text-sm text-fog-muted">{d}</span>
            </div>
          ))}
        </div>
        <p>
          Her listeye <K>+ clause</K> ile bir veya birden çok <strong className="text-fog">koşul
          (clause)</strong> eklersin. Bir koşul, bir <strong className="text-fog">sinyal primitifi</strong>{" "}
          (aşağıda anlatılıyor) ve onun operandlarından oluşur.
        </p>
        <Callout kind="info" title="Aynı listedeki koşullar VE (AND) ile birleşir">
          Long entry'de 2 koşul varsa, pozisyon <strong className="text-fog">ikisi de aynı anda
          doğruysa</strong> açılır. “Ya biri ya öteki” (VEYA) istiyorsan bunu şimdilik ayrı
          stratejilerle test edersin. Bir liste <strong className="text-fog">boşsa</strong>, o
          sinyal hiç tetiklenmez (örn. long exit boşsa, long pozisyon başka bir nedenle —
          ters sinyal ya da stop — kapanana dek açık kalır).
        </Callout>
        <p>
          Her koşulda: soldaki açılır liste <strong className="text-fog">primitifi</strong> seçer;
          sağındaki kutular o primitifin operandları/ayarlarıdır. <K>✕</K> koşulu siler.
        </p>
        <Callout kind="warn" title="Kırmızı “(unknown)” operand görürsen">
          Bir operand kutusu <span className="text-loss">kırmızı</span> ve yanında{" "}
          <K>(unknown)</K> yazıyorsa, o kural artık var olmayan bir operanda bakıyor demektir
          (indikatörü sildin, adını değiştirdin ya da çok-çıktılı bir indikatörle değiştirdin).
          Bu durumda <strong className="text-fog">Run butonu kapanır</strong> ve üstte uyarı çıkar.
          Kutudan geçerli bir operand seç; uyarı kaybolunca çalıştırabilirsin.
        </Callout>
      </Section>

      {/* 6 — Primitifler */}
      <Section id="primitif" n="6" title="6 sinyal primitifi — tek tek">
        <p>
          Primitif = kuralın “kalıbı”. Sistemde 6 yerleşik primitif var. Hepsi mum{" "}
          <strong className="text-fog">kapanışında</strong> değerlendirilir (lookahead-güvenli).
        </p>

        <div className="flex flex-col gap-4">
          <div className="rounded-md border border-line bg-graphite p-4">
            <p className="font-mono text-sm text-paper">line_cross(a, b, direction)</p>
            <p className="mt-1 text-sm text-fog-muted">
              <strong className="text-fog">İki çizginin kesişimi.</strong> <K>a</K> serisi <K>b</K>{" "}
              serisini keser mi? <K>direction</K>: <K>up</K> (a, b'yi yukarı keser — “altın kesişim”),
              <K>down</K> (aşağı keser), <K>cross</K> (herhangi bir yön). Klasik örnek:{" "}
              <K>a=ema_fast, b=ema_slow, direction=up</K> → hızlı ortalama yavaşı yukarı kesince al.
            </p>
          </div>

          <div className="rounded-md border border-line bg-graphite p-4">
            <p className="font-mono text-sm text-paper">threshold_cross(x, level, direction)</p>
            <p className="mt-1 text-sm text-fog-muted">
              <strong className="text-fog">Bir sabit seviyeyi geçmek.</strong> <K>x</K> serisi{" "}
              <K>level</K> sayısını <K>up</K>/<K>down</K>/<K>cross</K> yönünde geçer mi? Örnek:{" "}
              <K>x=rsi, level=30, direction=up</K> → RSI 30'un altından yukarı çıkınca (aşırı
              satımdan dönüş) al.
            </p>
          </div>

          <div className="rounded-md border border-line bg-graphite p-4">
            <p className="font-mono text-sm text-paper">slope(x, lookback, direction)</p>
            <p className="mt-1 text-sm text-fog-muted">
              <strong className="text-fog">Eğim / yön.</strong> <K>x</K> serisi son{" "}
              <K>lookback</K> mumda hangi yöne gidiyor? <K>direction</K>: <K>up</K> (yükseliyor),
              <K>down</K> (düşüyor), <K>flat</K> (yatay). Örnek: <K>x=ema_slow, lookback=5,
              direction=up</K> → ana trend yukarıysa.
            </p>
          </div>

          <div className="rounded-md border border-line bg-graphite p-4">
            <p className="font-mono text-sm text-paper">band_touch(price, upper, lower, mode)</p>
            <p className="mt-1 text-sm text-fog-muted">
              <strong className="text-fog">Bir bandı test etmek/kırmak.</strong> Fiyatın (
              <K>price</K>) bir üst (<K>upper</K>) ve alt (<K>lower</K>) banda göre davranışı.
              Bantlar genelde Bollinger gibi çok-çıktılı bir indikatörden gelir (örn.{" "}
              <K>bb.upperband</K> / <K>bb.lowerband</K>). <K>mode</K> seçenekleri: <K>touch_upper</K>,{" "}
              <K>touch_lower</K> (banda değme), <K>break_upper</K>, <K>break_lower</K> (bandı kırma),
              <K>revert_upper</K>, <K>revert_lower</K> (banttan geri dönme). Örnek:{" "}
              <K>price=close, lower=bb.lowerband, mode=touch_lower</K> → fiyat alt banda değince al.
            </p>
          </div>

          <div className="rounded-md border border-line bg-graphite p-4">
            <p className="font-mono text-sm text-paper">regime(x, rule)</p>
            <p className="mt-1 text-sm text-fog-muted">
              <strong className="text-fog">Rejim / filtre koşulu.</strong> <K>x</K> serisi metin
              olarak yazılan bir koşulu sağlıyor mu? <K>rule</K> örnekleri: <K>gt:25</K> (25'ten
              büyük), <K>lt:0</K> (0'dan küçük). Tipik kullanım: <K>x=adx, rule=gt:25</K> → yalnızca
              güçlü trend varken işlem yap (ADX &gt; 25). Bunu bir long entry'ye ikinci koşul olarak
              ekleyip “sadece trend varken al” süzgeci kurabilirsin.
            </p>
          </div>

          <div className="rounded-md border border-line bg-graphite p-4">
            <p className="font-mono text-sm text-paper">pattern(series, direction)</p>
            <p className="mt-1 text-sm text-fog-muted">
              <strong className="text-fog">Mum formasyonu.</strong> Bir mum-formasyonu indikatörünün
              (TA-Lib CDL… ailesi) sinyalini yön olarak okur. <K>direction</K>: <K>bullish</K>{" "}
              (yükseliş formasyonu), <K>bearish</K> (düşüş), <K>any</K> (herhangi). Örnek:{" "}
              <K>series=cdlengulfing, direction=bullish</K> → boğa yutan formasyonu oluşunca.
            </p>
          </div>
        </div>

        <Callout kind="tip" title="Mantığı kur: giriş bir sebep, çıkış bir sebep">
          İyi bir başlangıç: <em>giriş</em> için bir tetik (örn. line_cross up), istersen bir{" "}
          <em>filtre</em> (örn. regime adx&gt;25), ve <em>çıkış</em> için ya ters tetik (line_cross
          down) ya da ilerideki stop/target (aşağıda). Her koşulun bir gerekçesi olsun.
        </Callout>
      </Section>

      {/* 7 — Maliyetler */}
      <Section id="maliyet" n="7" title="Maliyetler: komisyon, kayma, funding">
        <p>
          Gerçek dünyada her işlem para götürür. Bu bölüm o maliyetleri modeller — ve{" "}
          <strong className="text-fog">varsayılan olarak açıktır</strong>. Kapatırsan sonuç
          gerçekçiliğini yitirir (aşağıdaki “Costless” uyarısına bak).
        </p>
        <Field name="Commission (bps)">
          Komisyon, <strong className="text-fog">baz puan</strong> (bps) cinsinden. 1 bps = %0.01.
          Varsayılan <K>4</K> = işlem başına (her yön) %0.04 — Binance USDT-M taker ücretine yakın.
          Al ve sat ayrı ayrı ücretlenir.
        </Field>
        <Field name="Slippage model">
          <strong className="text-fog">Kayma</strong> = emrinin, hedeflediğin fiyattan biraz farklı
          dolması. İki model:
          <ul className="ml-5 mt-1 list-disc space-y-0.5">
            <li><K>fixed_bps</K> — sabit bps kayma (yanındaki <K>Slippage (bps)</K> kutusu, varsayılan <K>5</K>).</li>
            <li><K>atr</K> — oynaklığa bağlı kayma; <K>ATR mult</K> (varsayılan <K>0.05</K>) × o anki ATR kadar. Oynak piyasada kayma büyür — daha gerçekçi.</li>
          </ul>
        </Field>
        <Field name="Funding">
          Vadeli (perpetual) piyasalarda 8 saatte bir ödenen/alınan <strong className="text-fog">fonlama
          ücreti</strong>. İşaretliyse (varsayılan) tarihsel funding uygulanır: genelde long öder,
          short alır. Uzun süre pozisyon taşıyan stratejilerde önemlidir.
        </Field>
        <Callout kind="warn" title="“Costless run” kırmızı etiketi">
          Komisyon, kayma veya funding'den birini kapatırsan, sonuç panelinde{" "}
          <span className="text-loss">Costless run</span> kırmızı rozeti çıkar ve kapalı bileşen{" "}
          <span className="text-loss">OFF</span> olarak işaretlenir. Bu bir <em>uyarıdır</em>:
          gerçekte olmayan, fazla iyimser bir sonuca bakıyorsun. Maliyetleri açık tutmak esastır.
        </Callout>
      </Section>

      {/* 8 — Sermaye */}
      <Section id="sermaye" n="8" title="Sermaye: başlangıç bakiyesi, pozisyon %, kaldıraç">
        <Field name="Initial cash">
          Başlangıç bakiyesi (USDT), varsayılan <K>10000</K>. Tüm getiriler buradan hesaplanır.
        </Field>
        <Field name="Size %">
          Her pozisyona bakiyenin ne kadarının konulacağı. <K>1.0</K> = bakiyenin %100'ü. <K>0.5</K>{" "}
          = yarısı. Küçük değer = daha az risk, daha yavaş büyüme.
        </Field>
        <Field name="Leverage">
          Kaldıraç çarpanı. <K>1.0</K> = kaldıraçsız (spot gibi). <K>5.0</K> = pozisyon 5 katı;
          hem kâr hem zarar 5 kat. Yüksek kaldıraç <strong className="text-loss">likidasyon</strong>{" "}
          (pozisyonun zorla kapatılması) riski demektir.
        </Field>
        <Callout kind="rule" title="Kaldıraç sınırları (sistem kuralı)">
          Sert tavan <strong className="text-fog">10x</strong>, güvenli varsayılan{" "}
          <strong className="text-fog">5x</strong>, izole marj. Likidasyon fiyatı girişe çok
          yakınsa sistem o işlem için kaldıracı otomatik düşürebilir. Yeni başlıyorsan{" "}
          <K>1.0</K> ile kal — önce stratejiyi doğrula, sonra kaldıraç düşün.
        </Callout>
      </Section>

      {/* 9 — Çalıştır */}
      <Section id="calistir" n="9" title="Çalıştır ve durumlar">
        <p>
          Her şey hazırsa en alttaki <K>Run backtest</K> butonuna bas. Buton, çözülmemiş
          (kırmızı) operand yoksa aktiftir. Basınca sistem işi kuyruğa alır ve bir arka plan
          işçisi (worker) simülasyonu koşar. Üstte küçük bir durum göstergesi döner:
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          {[
            ["queued", "İş kuyruğa alındı, sıra bekliyor."],
            ["running", "Simülasyon çalışıyor."],
            ["done", "Bitti — rapor aşağıda açılır."],
            ["failed", "Hata oldu — kırmızı kutuda mesaj çıkar."],
          ].map(([s, d]) => (
            <div key={s} className="flex items-center gap-3 rounded-md border border-line bg-graphite px-4 py-3">
              <span className="font-mono text-sm text-paper">{s}</span>
              <span className="text-sm text-fog-muted">{d}</span>
            </div>
          ))}
        </div>
        <Callout kind="warn" title="Sık görülen hata mesajı">
          <span className="font-mono text-[13px]">
            rule references unknown operand(s): ema_fast. Available operands: …
          </span>
          <br />
          Anlamı: bir kural <K>ema_fast</K> operandına bakıyor ama böyle bir operand yok (indikatörü
          değiştirdin/sildin). Mesaj sana <strong className="text-fog">geçerli operandların
          listesini</strong> de verir. Kuralda doğru operandı seç. Normalde arayüz zaten kırmızı
          uyarı verip Run'ı kapatır; bu mesajı en çok JSON/API üzerinden çalışırken görürsün.
        </Callout>
        <p>
          <strong className="text-fog">no market data</strong> hatası ise seçtiğin sembol/zaman
          diliminde veri olmadığını söyler — data series'i kontrol et.
        </p>
      </Section>

      {/* 10 — Sonuçlar */}
      <Section id="sonuc" n="10" title="Sonuçları okuma: metrikler">
        <p>
          Rapor en üstte bir <strong className="text-fog">Composite score</strong> (bileşik skor)
          ve maliyet rozetleriyle başlar, sonra metrik kutucukları gelir. Yeşil = iyi/kâr, kırmızı
          = kötü/zarar tonlaması vardır.
        </p>
        <Field name="Composite score">
          Stratejinin genel “kalite notu” — birçok metriği tek sayıya sıkıştırır (yüksek daha iyi).
          Farklı stratejileri hızlı kıyaslamak için. Yanındaki rozet{" "}
          <span className="text-profit">passes filters</span> ya da{" "}
          <span className="text-fog-faint">below filters</span> der.
        </Field>
        <Field name="passes / below filters">
          <strong className="text-fog">Sert filtreler:</strong> işlem sayısı ≥ 30, Max Drawdown ≤
          %25, Profit Factor ≥ 1. Üçünü de geçen strateji “passes filters” alır — yani istatistiksel
          olarak ciddiye alınabilir. Geçemeyen strateji (az işlem, çok risk ya da zarar) “below
          filters”tır.
        </Field>

        <p className="mt-2 text-fog">Metrik kutucukları — her biri ne der:</p>
        <div className="grid gap-2">
          {[
            ["Net return", "Tüm maliyetler düşülmüş toplam getiri (%). Asıl sonuç budur."],
            ["CAGR", "Yıllık bileşik büyüme oranı (%). Getiriyi “yıllık” ölçeğe çevirir; farklı süreleri kıyaslamak için."],
            ["Sharpe", "Risk-ayarlı getiri. Getiriyi toplam oynaklığa böler. Kabaca >1 iyi, >2 çok iyi."],
            ["Sortino", "Sharpe gibi ama sadece AŞAĞI (kötü) oynaklığı cezalandırır. Yukarı oynaklık ceza değildir."],
            ["Calmar", "CAGR / Max Drawdown. Getiriyi en kötü düşüşe göre tartar; yüksek daha iyi."],
            ["Max drawdown", "Tepe noktadan en dibe en büyük düşüş (%). Dayanman gereken en acı an. Küçük daha iyi."],
            ["DD duration", "En uzun düşüş süresinin kaç bar sürdüğü. Ne kadar süre zararda kaldığın."],
            ["Win rate", "Kazanan işlemlerin oranı (%). Tek başına yanıltıcı olabilir — profit factor ile birlikte oku."],
            ["Profit factor", "Toplam kâr / toplam zarar. >1 kârlı, <1 zararlı. 1.5+ sağlıklı sayılır."],
            ["Expectancy", "İşlem başına beklenen kazanç ($). Pozitif olması, ortalama her işlemin kazandırdığı demektir."],
            ["Avg win/loss", "Ortalama kazanç / ortalama kayıp oranı. 1'in üstü, kazançların kayıplardan büyük olduğunu gösterir."],
            ["Trades", "Toplam işlem (round-trip: giriş+çıkış) sayısı. 30'un altı istatistiksel olarak zayıftır."],
            ["Exposure", "Zamanın yüzde kaçında piyasada (pozisyonda) kaldığın. Düşükse sermayen çoğu zaman boşta demektir."],
            ["SQN", "System Quality Number — işlem sonuçlarının tutarlılığı/kalitesi. Yüksek = daha güvenilir sistem."],
            ["Final equity", "Testin sonundaki bakiye ($). Başlangıç bakiyesiyle kıyasla."],
          ].map(([m, d]) => (
            <div key={m} className="grid grid-cols-1 gap-1 rounded-md border border-line bg-graphite px-4 py-2.5 sm:grid-cols-[150px_1fr] sm:gap-4">
              <span className="font-mono text-sm text-fog">{m}</span>
              <span className="text-sm text-fog-muted">{d}</span>
            </div>
          ))}
        </div>

        <Callout kind="tip" title="Tek metriğe âşık olma">
          Yüksek getiri tek başına bir şey ifade etmez. Birlikte bak: <em>Net return</em> +{" "}
          <em>Max drawdown</em> (kaça mal oldu?) + <em>Profit factor</em> (tutarlı mı?) +{" "}
          <em>Trades</em> (yeterli örneklem var mı?). 500% getiri ama %70 drawdown ve 8 işlem =
          kumar; %40 getiri, %12 drawdown, 120 işlem, PF 1.6 = iş.
        </Callout>
      </Section>

      {/* 11 — Grafikler */}
      <Section id="grafik" n="11" title="Grafikler ve işlem tablosu">
        <Field name="Price & signals">
          Mum grafiği. Girişler <span className="text-profit">▲</span>, çıkışlar{" "}
          <span className="text-fog">▽</span> işaretleriyle gösterilir. Stratejinin “nerede alıp
          nerede sattığını” gözünle görürsün — mantıklı yerlerde mi işlem açmış?
        </Field>
        <Field name="Equity & drawdown">
          Üstte bakiye eğrisi (equity) — zamanla paran nasıl değişmiş. Altta drawdown — tepeden ne
          kadar geri çekilmişsin. Düz ve yukarı bir eğri + sığ drawdown iyidir; testere gibi inip
          çıkan eğri risklidir.
        </Field>
        <Field name="Monthly returns">
          Aylık getiri ısı haritası. Her kutu bir ay; <span className="text-profit">yeşil</span> kâr,{" "}
          <span className="text-loss">kırmızı</span> zarar. Getiri birkaç şanslı aya mı sıkışmış,
          yoksa aylara yayılmış mı — istikrarı buradan görürsün.
        </Field>
        <Field name="Trades">
          Her round-trip işlemin satırı. Kolonlar:
          <ul className="ml-5 mt-1 list-disc space-y-0.5">
            <li><K>Side</K> — long / short.</li>
            <li><K>Entry</K> / <K>Exit</K> — giriş ve çıkış zamanı (Europe/Istanbul).</li>
            <li><K>Entry px</K> / <K>Exit px</K> — giriş ve çıkış fiyatı.</li>
            <li><K>Bars</K> — işlemin kaç mum sürdüğü.</li>
            <li><K>Fees</K> — o işlemin komisyon+kayma maliyeti.</li>
            <li><K>Funding</K> — o işlemde ödenen/alınan fonlama.</li>
            <li><K>Net P&amp;L</K> — net kâr/zarar ($). Yeşil kazanç, kırmızı kayıp.</li>
            <li><K>Return</K> — o işlemin yüzde getirisi.</li>
          </ul>
        </Field>
        <p>
          Üst köşede <K>#config_hash</K> ve <K>bars</K> yazar. Config hash, tam bu ayarların
          parmak izidir — aynı hash = aynı test. Bir sonucu paylaşırken bu hash işine yarar.
        </p>
      </Section>

      {/* 12 — Örnek */}
      <Section id="ornek" n="12" title="Baştan sona örnek (varsayılan EMA stratejisi)">
        <p>
          Sayfa ilk açıldığında hazır gelen strateji: <strong className="text-fog">EMA 9 × EMA 21
          kesişimi</strong>. Birlikte adım adım okuyalım:
        </p>
        <ol className="ml-5 list-decimal space-y-2">
          <li>
            <strong className="text-fog">İki indikatör:</strong> <K>ema_fast</K> = EMA(9) ve{" "}
            <K>ema_slow</K> = EMA(21). Biri hızlı, biri yavaş ortalama.
          </li>
          <li>
            <strong className="text-fog">Long entry:</strong>{" "}
            <K>line_cross(a=ema_fast, b=ema_slow, direction=up)</K> — hızlı ortalama yavaşı yukarı
            kesince <span className="text-profit">al</span>.
          </li>
          <li>
            <strong className="text-fog">Long exit:</strong> aynı kesişim <K>down</K> yönünde —
            hızlı, yavaşın altına inince long'u <span className="text-fog">kapat</span>.
          </li>
          <li>
            <strong className="text-fog">Short:</strong> tam tersi — <K>down</K> ile short aç,{" "}
            <K>up</K> ile short'u kapat.
          </li>
          <li>
            <strong className="text-fog">Maliyetler açık</strong> (komisyon 4 bps, kayma 5 bps,
            funding açık), sermaye 10.000, kaldıraç yok. <K>Run backtest</K>'e bas.
          </li>
          <li>
            <strong className="text-fog">Sonuç:</strong> metrikleri oku. Örn. gerçek BTCUSDT/1h
            verisinde bu basit strateji ~100 işlem üretip Profit Factor'ü 1'in <em>altında</em>
            (zararda) çıkabilir — yani “tek başına EMA kesişimi” yetmez. İşte backtest tam da bunu,
            para kaybetmeden, önceden söyler.
          </li>
        </ol>
        <Callout kind="tip" title="Şimdi sen dene">
          Bu tabana bir <strong className="text-fog">filtre</strong> ekle: long entry'ye ikinci
          koşul olarak <K>regime(x=adx, rule=gt:25)</K> koy (önce bir <K>adx</K> indikatörü
          eklemeyi unutma). “Sadece trend güçlüyken al” kuralı sonucu nasıl değiştiriyor? Çalıştır
          ve karşılaştır.
        </Callout>
      </Section>

      {/* 13 — Hatalar */}
      <Section id="hata" n="13" title="Sık hatalar ve ipuçları">
        <div className="flex flex-col gap-3">
          <Callout kind="warn" title="Aşırı uydurma (overfitting)">
            Parametreleri geçmişe birebir uydurup harika sonuç bulmak kolaydır ama gelecekte
            çöker. Az sayıda, mantıklı parametre kullan. Sonuç “fazla mükemmelse” şüphelen.
          </Callout>
          <Callout kind="warn" title="Çok az işlem">
            10-15 işlemle çıkan yüksek getiri şanstır. Sert filtre 30 işlem ister; anlamlı
            sonuç için daha da fazlası iyidir.
          </Callout>
          <Callout kind="warn" title="Maliyetleri kapatmak">
            “Costless” sonuçlar seni kandırır. Komisyon/kayma/funding küçük görünür ama çok
            işlemde birikir ve kârlı görünen stratejiyi zarara çevirebilir. Açık tut.
          </Callout>
          <Callout kind="tip" title="Küçükten büyüğe">
            Önce tek koşullu basit bir kuralla başla, çalıştığını gör, sonra filtre/çıkış ekle.
            Her seferinde tek şeyi değiştir ki neyin sonucu değiştirdiğini anla.
          </Callout>
          <Callout kind="tip" title="Aynı ayarı tekrar üretmek">
            Bir sonucu beğendiysen <K>config_hash</K> ve <K>seed</K>'i not al. Aynı config + seed
            her zaman birebir aynı sonucu verir.
          </Callout>
        </div>
      </Section>

      {/* 14 — Altın kurallar */}
      <Section id="altin" n="14" title="Altın kurallar (sistemin garantileri)">
        <ul className="ml-5 list-disc space-y-2">
          <li>
            <strong className="text-fog">Lookahead yok:</strong> sinyal mum kapanışında, dolum
            sonraki açılışta. Sistem geleceği göremez.
          </li>
          <li>
            <strong className="text-fog">Maliyetler varsayılan açık:</strong> kapatırsan kırmızı
            “Costless” etiketiyle uyarılırsın.
          </li>
          <li>
            <strong className="text-fog">Tekrarlanabilirlik:</strong> her koşu config hash + seed
            ile birebir tekrar üretilebilir.
          </li>
          <li>
            <strong className="text-fog">Şeffaflık:</strong> her işlem, giriş/çıkış zamanı, fiyatı
            ve maliyetiyle tabloda görünür — gizli sihir yok.
          </li>
          <li>
            <strong className="text-fog">Backtest ≠ canlı garanti:</strong> burada iyi olan bir
            strateji, canlıya çıkmadan önce walk-forward ve paper mod kapılarından geçmek
            zorundadır.
          </li>
        </ul>
        <div className="mt-4 flex flex-wrap gap-3">
          <Link
            href="/backtest"
            className="rounded bg-fog px-6 py-2.5 text-sm font-semibold text-void transition-colors hover:bg-fog-muted"
          >
            Backtest Lab'a git ve dene →
          </Link>
          <a
            href="#nedir"
            className="rounded border border-line px-6 py-2.5 text-sm text-fog-muted transition-colors hover:border-fog-faint hover:text-fog"
          >
            ↑ Başa dön
          </a>
        </div>
      </Section>
    </div>
  );
}
