# Karne — Sistem Planı

> Bu belge projenin tek referans kaynağıdır. Kod yazarken buradaki kararlara
> sadık kalınır. Bir karar değişecekse **önce bu dosya güncellenir**, sonra kod.
>
> Belge Türkçedir çünkü projenin iç planıdır. Kod, değişken adları, commit
> mesajları, README ve kullanıcıya dönük dokümantasyon İngilizcedir (bkz. K-08).

| | |
|---|---|
| **Süre** | Eylül 2026 → Haziran 2027 |
| **Teslim** | Tek teslim, yıl sonu |
| **Barındırma** | Küçük VPS (~5 €/ay) |
| **Arayüz dili** | Türkçe + İngilizce |
| **Geliştirici** | Tek kişi |

---

## 1. Ne inşa ediyoruz

Bir alan adı girildiğinde o kurumun dijital hijyenini dört boyutta ölçen,
sonucu açıklamalı bir karneye çeviren ve aynı motoru Türkiye çapında
on binlerce alan adına uygulayan bir sistem.

İki çıktısı var:

1. **Kamuya açık, çalışan bir araç** — kurumlar kendi alan adlarını test eder.
2. **Daha önce toplanmamış bir veri seti** — tezin ampirik omurgası.

### Boru hattı

```
[1] Çerçeve      Hangi alan adları ölçülecek: liste, sektör etiketi, örneklem
      ↓
[2] Toplayıcılar DNS · TLS/HTTP · tarayıcı · parmak izi (her biri bağımsız)
      ↓
[3] Ham depo     Gözlem olduğu gibi saklanır, asla silinmez, yorumlanmaz
      ↓
[4] Puanlama     Ham veriden not ve bulgu üretilir, kural dosyasına göre
      ↓
[5] Yüzey        Karne arayüzü · sektör panoları · API · açık veri · defterler
```

Tek yön: ölçüm → ham → puan → sunum. Her adım tekrar üretilebilir.

### Bir alan adı için üretilen çıktı

- Dört boyutta harf notu
- Her boyutta somut bulgular (`DMARC kaydı yok`, `onay öncesi 7 pazarlama çerezi`)
- Her bulgunun altında kopyala-yapıştır düzeltme talimatı
- Sektör karşılaştırması: "sektöründeki 340 kurumun ortalaması şu, sen şuradasın"

---

## 2. Mimari kararlar

Her karar bir kez verilir, gerekçesiyle kayda geçer. Tez metninde bu tablo
doğrudan kullanılacak.

### K-01 · Baştan sona Python

Toplayıcı, API, analiz ve model tek dilde. Ölçüm ekosisteminin tamamı
(dnspython, cryptography, Playwright, pandas, scikit-learn) zaten Python.
İkinci bir dil projeye hiçbir şey katmaz; bağlam değiştirme maliyeti ise gerçek.

### K-02 · Ham gözlem ile puanlama kesin olarak ayrı

**Planın en önemli kararı.** Toplayıcılar yorum yapmaz, sadece gördüğünü JSON
olarak yazar. Not ve bulgu, ham veriden sonradan türetilir.

Puanlama kuralları yıl boyunca değişecek. Ham veri durduğu için Kasım'daki
taramayı Mayıs'taki kurallarla yeniden puanlayabileceksin. Bu ayrım bozulursa
boylamsal analiz imkânsız hâle gelir.

### K-03 · Puanlama kuralları kodda değil, `config/scoring.toml` dosyasında

Ağırlıklar, eşikler ve harf notu sınırları veri olarak durur, sürüm numarası
taşır. Her puan kaydı hangi kural sürümüyle üretildiğini yazar. "Bu ağırlığı
neden 3 verdin" sorusunun cevabı tek dosyada.

### K-04 · SQLite, tek dosya, WAL modu

10.000 alan adı × aylık tarama × 8 ay = birkaç milyon satır; SQLite bunu rahat
taşır. Sunucu kurmak, yedeklemek, sürüm yönetmek yok — yedek almak dosyayı
kopyalamak. PostgreSQL'e ancak eşzamanlı yazma gerçekten sorun olursa geçilir.

### K-05 · Her toplayıcı bağımsız ve tek sorumlu

DNS toplayıcısı tarayıcıyı bilmez, tarayıcı DNS'i bilmez. Biri çökerse
diğerleri çalışır ve tarama kaydına kısmi sonuç yazılır. Bu aynı zamanda
Claude Code ile çalışmayı mümkün kılar: her modül tek oturumda yazılıp test
edilebilecek boyutta kalır.

### K-06 · Gizlilik ölçümü üç onay durumunda yapılır

Dokunmadan · reddettikten sonra · kabul ettikten sonra. Üçü ayrı kaydedilir.

KVKK açısından kritik olan birincisi. "Reddettim ama yine de yüklendi" bulgusu
ikincisinden çıkar ve projenin en çarpıcı sonucu odur. Tek durum ölçen bir
tasarım bu bulguyu üretemez.

### K-07 · Sadece pasif ve kamuya açık gözlem

Zafiyet taraması, dizin denemesi, port taraması, form gönderimi yok. Sıradan
bir ziyaretçinin tarayıcısının gördüğünden fazlasına bakılmaz. Sınır bir kez
çizilir, bir daha tartışılmaz.

### K-08 · Arayüz iki dilli, kod tek dilli

Arayüz ve rapor metinleri Türkçe + İngilizce, çeviri dosyalarından okunur
(arayüzde sabit metin yok). Kod, değişken adları, commit mesajları, README ve
kullanıcıya dönük dokümantasyon İngilizce. Bu plan belgesi Türkçe kalır.

### K-09 · Aylık yeniden tarama Kasım'da başlar

Zaman serisi sonradan üretilemez. Boyutların eksik olması önemli değil —
hangi boyut hazırsa onunla, ama Kasım'dan itibaren her ayın ilk haftası tarama
çalışır. Haziran'da 8 aylık boylamsal veri olur.

### K-10 · Depo baştan açık kaynak, veri seti teslimde

Kod ilk günden herkese açık (MIT veya Apache-2.0). Ölçüm verisi tez teslimine
kadar kapalı, teslimle birlikte yayımlanır.

### K-11 · DNS ölçümü sabit, doğrulayan resolver'larla yapılır

*(Karar: 2026-09-11, Sprint 2. Sprint 0/1'den taşınan iki açık soruyu kapatır.)*

Toplayıcılar sistem resolver'ı yerine `config/settings.toml`'da tanımlı **sabit,
DNSSEC doğrulayan** public resolver'ları kullanır: varsayılan **1.1.1.1 birincil,
8.8.8.8 yedek**. Gerekçe: Sprint 0'da ev yönlendiricisinin resolver'ı DNSSEC AD
bayrağını doğrulamadığı için imzalı alan adları (ör. internet.nl) yanlışlıkla
"doğrulanmadı" göründü; ayrıca tek resolver bazı SERVFAIL'leri maskeleyebiliyor
(turkiye.gov.tr). Sabit resolver seti ölçümü **tekrar üretilebilir** kılar ve
DNSSEC gözlemini doğru yapar. AD bayrağı yine "resolver'ın görüşü" olarak
işaretlenir (K-02: yorum değil gözlem).

**SERVFAIL yeniden-sorgu politikası.** SERVFAIL alınan bir sorgu, kısa bir
beklemeden sonra **bir kez** yeniden sorulur (resolver listesi birincil+yedeği
birlikte içerdiği için yeniden sorgu her ikisini de yeniden dener). Sonuç yine
SERVFAIL ise durum `requeried=true` notuyla kaydedilir. Bu, kesintili / tek-
resolver kaynaklı SERVFAIL'i temizler ama kalıcı "ölçülemedi" durumunu (kural 6)
olduğu gibi korur — SERVFAIL ile NXDOMAIN ayrı kalır. Timeout için ayrı ve mevcut
bir yeniden-deneme mantığı (dns.retries) zaten var; bu politika ondan bağımsızdır.

Tekil `scan` ve toplu `batch` aynı `DnsClient`'ı kullandığından bu karar her iki
yolda da aynı ham veriyi üretir.

### K-12 · A boyutu puanlama modeli

*(Karar: 2026-09-11, Sprint 3 · Oturum 1. K-02/K-03'ün somutlanması: A boyutu için
ağırlık, eşik ve harf sınırları. Tümü `config/scoring.toml` sürüm `1.0.0`'da yaşar;
kodda sabit eşik/ağırlık yoktur.)*

Ham DNS/e-posta verisi 0–100 ham puana ve bir harf notuna çevrilir. Puanlama
`scan_results`'ı yalnız **okur**; `scores`/`findings` türetilmiştir, `rescore` ile
güvenle silinip yeniden üretilebilir (aynı ham veri + aynı `ruleset_version` = aynı
not, hep).

- **Harf skalası (güvenliğe göre kalibre):** A≥85, B≥70, C≥55, D≥40, F<40. Mutlak
  ve tekrar-üretilebilir. Türkiye örnekleminde e-posta güvenliği genelde zayıf
  olduğundan (DMARC'ların çoğu `p=none`, DNSSEC neredeyse yok) klasik 90/80/70
  herkesi F'ye yığardı; bu eşikler örneklemi ayırt eder.
- **Ağırlıklar (kimlik-doğrulama ağırlıklı, toplam 100):** DMARC 35, SPF 25,
  DNSSEC 15, DANE 8, CAA 7, MTA-STS 6, TLS-RPT 4. **DKIM ve MX puana katılmaz.**
  DMARC 35 içinde: politika (`p=`) 25, toplu rapor (`rua`) 5, alt-alan (`sp=`) 5.
  SPF 25 içinde: sonlandırıcı 18 (`-all`=tam, `~all`=yarı, `?all`=düşük, `+all`=0),
  10-lookup sınırı 7.
- **DKIM puanlanmaz (yalnız gözlem).** Seçici adları DNS'ten keşfedilemez, tahmin
  edilir; 0/16 seçici bulmak "DKIM yok" değildir — akbank.com ve turkiye.gov.tr
  canlı koşuda 0/16 döndürdü, oysa internet.nl onların DKIM'ini görüyor. Bulunursa
  `EMAIL_DKIM_FOUND` (+ kısa anahtar için `EMAIL_DKIM_KEY_SHORT`), bulunamazsa
  `EMAIL_DKIM_NOT_OBSERVED` (info) yazılır; ceza yok.
- **"Ölçülemedi" (servfail/timeout) cezalandırılmaz (kural 6).** Ölçülemeyen
  gösterge paydadan düşülür; puan kalan ölçülen ağırlık üzerinden yüzdelenir
  (`raw_score = 100 × kazanılan / ölçülen_ağırlık`). Ölçülen ağırlık uygulanabilir
  ağırlığın %50'sinin altındaysa harf notu yerine **"yetersiz veri" (grade `I`)**
  verilir (raw_score yine kaydedilir). "Kayıt yok" (nxdomain/noanswer) gerçek
  yokluktur ve puanlanır — ölçülemedi ile ASLA karıştırılmaz.
- **Uygulanamaz göstergeler payda dışıdır.** MX yoksa posta-aktarım göstergeleri
  (MTA-STS, TLS-RPT, DANE) uygulanamaz sayılır ve paydadan düşülür — postasız bir
  alan adı "DANE yok" diye cezalandırılmaz. Üç durum ayrı tutulur: **yokluk ≠
  uygulanamaz ≠ ölçülemedi.**
- **Bulgu metinleri kodda değil.** `findings.code` sabit listeden gelir; her kodun
  `severity` ve `fix_hint_key`'i `scoring.toml`'da, insan-okur açıklama/düzeltme
  metni çeviri dosyalarında (K-08). Kod yalnız kod + kanıt üretir.

**Ruleset sürüm geçmişi.**

- **1.0.0** — ilk A boyutu modeli (yukarıdaki kararlar).
- **1.1.0** — **SPF softfail (`~all`) DMARC uygularken telafi edilir.** DMARC
  `p=reject`/`quarantine` ise hizasız posta zaten DMARC tarafından reddedilir;
  dolayısıyla `~all` gerçek bir boşluk bırakmaz ve yarım yerine tam-yakını (0.9)
  puanlanır (kesin `-all` için küçük bir üstünlük korunur). Bulgu yine yazılır
  (`dmarc_compensated=true` kanıtıyla), böylece düzeltme ipucu hâlâ `-all` önerir.
  internet.nl karşılaştırmasıyla fark edildi: internet.nl (dış referans aracın kendi
  alan adı) `~all`+`p=reject` kullanıyor ve kendi aracında %100 alıyor; bizde 1.0.0'da
  81 (B) idi, 1.1.0'da 88.2 (A). **Bu, o araca kalibrasyon değil**, bir çift-sayımın
  ilkeli düzeltmesidir (parity gösterge düzeyinde kalır, puan düzeyinde değil). Altı
  bilinen Türk alan adının notunu **değiştirmez** (hiçbiri `~all`+enforce değil) ve
  `rescore`'un yeniden-puanlanabilirliğini (K-02) canlı gösterir.

---

### K-13 · B boyutu puanlama modeli

*(Karar: 2026-09-12, Sprint 3. K-12'nin B boyutu (aktarım & sunucu güvenliği,
toplayıcı `tls_http`) için karşılığı. Ağırlık/eşik/bulgu kataloğu tümüyle
`config/scoring.toml` sürüm `1.2.0`'da yaşar; kodda sabit sayı yoktur. Aynı harf
skalası (A≥85…F<40), aynı üç-durum mantığı (yokluk ≠ uygulanamaz ≠ ölçülemedi) ve
aynı `_aggregate` çekirdeği A ile paylaşılır.)*

Ham `tls_http` verisi (normal bir tarayıcı ziyaretinin gördüğü kadarı, K-07)
0–100 ham puana ve harf notuna çevrilir. Aktif prob yok: STARTTLS zorlaması,
port taraması, dizin/dosya denemesi, zafiyet probu **yapılmaz** — TLS sürümleri
443'te sürüm başına ayrı, standart el sıkışmayla ölçülür (§4).

- **Ağırlıklar (toplam 100):** HTTPS zorlaması 25, TLS sürümleri 20, sertifika 20,
  HSTS 15, çekirdek güvenlik başlıkları 15, `security.txt` 5.
- **HTTPS zorlaması (25):** `http://` isteği tam zincir boyunca `https`'e çıkıyor
  mu. HTTPS'e hiç ulaşılmıyorsa 0 (`TRANSPORT_NO_HTTPS`, high); ulaşıyor ama zincirde
  `https`'ten sonra bir cleartext adım varsa kısmi puan (`cleartext_fraction`=0.4,
  `TRANSPORT_CLEARTEXT_REDIRECT`, high).
- **TLS sürümleri (20):** modern = TLS 1.2/1.3, legacy = TLS 1.0/1.1. Modern hiç
  yoksa 0 (`TRANSPORT_TLS_OUTDATED`, high); modern var ama legacy da kabul ediliyorsa
  kısmi (`legacy_fraction`=0.4, `TRANSPORT_TLS_LEGACY`, medium).
- **Sertifika (20):** zincir doğruluyor + hostname eşleşiyor mu, süresi doluyor mu.
  Doğrulamıyorsa 0 (`TRANSPORT_CERT_INVALID`, high); `expiry_warn_days`=15 günden az
  kaldıysa tam puan ama bulgu (`TRANSPORT_CERT_EXPIRING`, medium).
- **HSTS (15):** yeterli `max-age` (≥180 gün) için taban 0.6; `includeSubDomains`
  +0.25, `preload` +0.15 (üst sınır 1.0). Yoksa 0 (`TRANSPORT_NO_HSTS`, medium);
  `max-age` kısaysa 0.3 (`TRANSPORT_HSTS_SHORT`, low); `includeSubDomains` yoksa
  bulgu (`TRANSPORT_HSTS_NO_INCLUDESUBDOMAINS`, low).
- **Güvenlik başlıkları (15):** dört çekirdek başlık (`content-security-policy`,
  `x-frame-options`, `x-content-type-options`, `referrer-policy`) eşit paylı; eksik
  varsa `TRANSPORT_MISSING_SECURITY_HEADERS` (medium, kanıtta hangileri eksik).
- **`security.txt` (5):** olgunluk sinyali, varlık yeterli; yoksa
  `TRANSPORT_NO_SECURITY_TXT` (info).
- **"Ölçülemedi" (bağlantı hatası) cezalandırılmaz (kural 6).** Ana sayfaya hiç
  yanıt gelmemesi, TLS problarının tümünün hata vermesi ya da sertifikanın hiç
  alınamaması ilgili göstergeyi paydadan düşürür (0 yazılmaz). Ölçülen ağırlık
  uygulanabilir ağırlığın %50'sinin altındaysa harf yerine `I` (yetersiz veri).

**Doğrulama.** Yedi gerçek alan adı için notlar elle hesaplanıp teste donduruldu
(`tests/test_scoring_transport.py`): internet.nl 94.0 (A), akbank.com 91.25 (A),
itu.edu.tr 89.0 (A), istanbul.edu.tr 82.75 (B), turkiye.gov.tr 81.25 (B),
garantibbva.com.tr 70.0 (B), mumifashion.com 68.75 (C). Yediside HTTPS + modern TLS
+ geçerli sertifikayı (65 puan) sağlıyor; onları ayıran HSTS, güvenlik başlıkları
ve `security.txt`.

**Ruleset sürüm geçmişi (devam).**

- **1.2.0** — B boyutu (aktarım) eklendi: ağırlıklar, eşikler ve `TRANSPORT_` bulgu
  kataloğu. Salt ekleme; A modeli ve altı bilinen alan adının notu değişmez.

### K-14 · Canlı araç dağıtımı ve ölçüm menşei

*(Karar: 2026-09-17, Sprint 3 kapanışı. Canlı web sorgusunun DB'ye yazmasından doğan
dağıtım sorularını kapatır.)*

- **Sunucu DB'si yazılabilir bir kopyadır.** Web sorgusu her seferinde tarama yapıp
  sonucu yeni kayıt olarak eklediği için (kural 5) salt-okunur kopya çalışmaz. Yerel
  `data/karne.db` tutarlı bir yedekle (`sqlite3 .backup`) sunucuya kopyalanır; sektör
  karşılaştırması böylece ilk günden gerçek dağılımla çalışır. **Tez veri kümesinin
  kanonik kopyası yerelde kalır**; sunucu DB'si türetilmiş sayılır ve düzenli yedeklenir.
- **Web sorguları teze girmez.** Sunucudan yapılan taramalar `run_label` boş (ad-hoc)
  olarak yazılır; örneklemde olmayan yeni alan adları ayrıca `domains.source = "web"`
  taşır. Tez bulguları yalnız yerelden, sabit resolver'larla
  (K-11) yapılan **tur taramalarından** (`run_label` dolu) üretilir; böylece ölçüm tek
  menşeli kalır. Web sorguları yalnız araç kullanım istatistiği olarak raporlanır
  (Sprint 7 değerlendirme).
- **Aylık tur taraması yerelde, elle tetiklenir** (K-09'un uygulaması). Tek komutluk bir
  betik (`scripts/monthly_round`) batch → rescore (e-posta + aktarım) → DB yedeği
  sırasını çalıştırır; her ayın ilk haftası geliştirici çalıştırır. Otomatik zamanlayıcı
  kullanılmaz: kapalı bilgisayar ya da uyku modunun o ayı sessizce atlatması
  boylamsal seriye zarar verir, elle çalıştırma tarih ve süreyi kayıt altında tutar.
- **Kötüye kullanım sınırı iki katmanlıdır.** "Keyfi alan adı tarat" ucu sunucunun
  üçüncü taraflara DNS/HTTP üretmesine yol açabileceğinden (§4 hız sınırı ilkesi):
  (1) uygulama içinde aynı alan adının kısa bir bekleme süresi içinde yeniden
  taranmaması — süre içinde gelen sorgu o taramanın sonucunu gösterir — ve eşzamanlı
  canlı tarama sayısına üst sınır (değerler `config/settings.toml` `[web]`'de);
  (2) Cloudflare hız sınırı kuralı. IP adresi kaydı **tutulmaz**. Bu, "her sorgu
  sıfırdan taranır" kuralının tek istisnasıdır ve yalnız bekleme süresi içinde geçerlidir.
- **Tarayıcı kimliği.** Yayınla birlikte User-Agent, proje adı ve bilgi sayfasını
  bildirir: `WebKarne/1.0 (+https://webkarne.com/tr/hakkinda; passive measurement)`
  (§4). Değişiklik tarihi PROGRESS'e yazılır; önceki taramalar `config_hash` ile ayrışır.
- **Analiz bağımlılıkları ayrı gruptadır.** Tez figürleri için matplotlib/pandas
  `analysis` bağımlılık grubunda durur; yerelde kurulur, sunucuya kurulmaz.

### K-15 · Bileşik (genel) not şimdilik yok

*(Karar: 2026-09-17.)* Dört boyuttan yalnız ikisi (A, B) ölçülürken tek bir genel harf
notu, eksik boyutları görünmez kılıp yanıltıcı bir kesinlik üretir. Arayüz yalnız
**boyut-bazlı** not gösterir; ölçülmeyen boyutlar "henüz ölçülmedi" olarak kalır.
Bileşik skor, dört boyut hazırken **F boyutunda (Nisan)** tasarlanır ve `scoring.toml`'a
sürümlü olarak girer. O zamana dek `scoring.toml`'da bileşik kural yazılmaz.

### K-16 · C boyutu toplayıcısı: ham kayıt biçimi ve ölçüm koşulları

*(Karar: 2026-09-17, Sprint 4 · Oturum 1. K-06'nın üç onay durumunun nasıl
kaydedileceğini ve tarayıcı ölçümünün koşullarını sabitler.)*

- **Bağımlılık.** Playwright (Chromium) ayrı, varsayılan-dışı `privacy` uv grubunda
  durur (`uv sync --group privacy`, ardından `playwright install chromium`). Sunucuya
  kurulmaz; toplayıcı Playwright'ı tembel içe aktarır, yoksa açık hata verir. C boyutu
  bu karar değişene dek **yalnız yerelde, tek alan adında** (`karne scan --collectors
  privacy`) çalışır; `batch`'e ve web arayüzüne bağlanması ayrı karardır (alan adı
  başına ~45 sn × 3 durum).
- **Kayıt yapısı.** Bir tarama = bir `scans` satırı + bir `scan_results`
  (`collector="web_privacy"`) satırı. Üç onay durumu payload içinde `states.untouched`,
  `states.rejected`, `states.accepted` altında **ayrı kayıtlar** olarak durur; her biri
  temiz (çerezsiz, service worker'ı engellenmiş) ayrı bir tarayıcı bağlamında ölçülür.
  Henüz uygulanmamış durum `outcome="not_run"` taşır. Bu yapıda `scans.consent_state`
  kullanılmaz (NULL); `cookies`/`requests` projeksiyon tabloları taraf tanımı
  uygulanınca doldurulur.
- **Ölçüm sonucu durumları (kural 6).** Her durum kaydı bir `outcome` taşır: `loaded`
  (ölçüldü) · `http_error` (ana belge 4xx/5xx) · `blocked` (yalnız gözlenebilir bir
  bot-engeli işareti varsa, kanıtıyla) · `timeout` · `dns_error` · `navigation_error` ·
  `browser_error` · `not_run`. Yalnız `loaded` "ölçüldü" sayılır. Hata durumunda o ana
  kadar görülen çerez/istekler yine saklanır ama boş liste **asla** "çerez yok" demek
  değildir.
- **Kaydedilen / kaydedilmeyen.** Çerezler tarayıcı protokolünden (HttpOnly dâhil) ad,
  domain, path, expires, session, secure, httpOnly, sameSite ile; **değerleri
  kaydedilmez**. localStorage/sessionStorage yalnız **anahtar** adlarıyla. Ağ
  istekleri **tam URL** ile (en çok `max_url_length` karakter, kesilirse işaretlenir):
  D boyutu sürüm parametrelerini ve etiket kimliklerini bu ham veriden türetecek, geriye
  dönük yeniden toplanamaz. URL'lerdeki kimlikler taze, anonim ölçüm tarayıcısına aittir,
  gerçek bir kişiye değil.
- **Birinci/üçüncü taraf ayrımı toplayıcıda yapılmaz** (kural 1). Toplayıcı ham host'u
  yazar; ayrım analiz katmanında, repoya tarihli ve hash'li konmuş bir Public Suffix List
  anlık görüntüsüyle (eTLD+1) yapılır ve kullanılan liste sürümü sonuca yazılır. Yeni
  bağımlılık eklenmez.
- **İzleyici veri seti** (host → şirket/ülke) henüz seçilmedi — açık karar; aday
  listesi ve lisansları seçimden önce kaynağından doğrulanıp buraya yazılır.
- **Tarayıcı kimliği (§4 uygulaması).** User-Agent = Chromium'un kendi UA dizesi +
  `settings.toml`'daki WebKarne kimliği eki. Saf `WebKarne/1.0` dizesi bazı onay
  platformlarının banner'ı botlara göstermemesine ve izleyicilerin yüklenmemesine yol
  açar; bu, sıradan ziyaretçinin gördüğünden farklı bir sayfa ölçmek demektir (K-06'yı
  bozar). Kimlik yine açıkça bildirilir.
- **Koşullar ve sınırlar (K-07).** Yalnız ana sayfa; bağlantı takibi, form, giriş yok.
  `untouched` durumunda hiçbir etkileşim yapılmaz (`interactions` boş olmak zorunda);
  sayfa yüklendikten sonra sabit bir gözlem penceresi (15 sn) beklenir. Navigasyon
  zaman aşımı, durum başına süre bütçesi, navigasyonlar arası asgari bekleme, istek üst
  sınırı, dil/saat dilimi/görüntü alanı `settings.toml` `[web_privacy]`'de.
  Bot koruması aşılmaya çalışılmaz; engel "ölçülemedi" (`blocked`) olarak kaydedilir.

**K-16 eki — Sprint 4 · Oturum 2 (2026-09-17): tarayıcı modu, onay arayüzü, reddet.**

- **Tarayıcı modu: pencereli (headless değil) Chromium, pencere ekran dışında.** Ön
  keşifte (40 Türk ana sayfası) headless Chromium sitelerin ~%30'unda engellendi ve
  engellenenler büyük e-ticarette yığıldı — sektör karşılaştırmasında sistematik
  yanlılık. "Yeni headless" modu fark yaratmadı (UA yine `HeadlessChrome`). UA'ya
  dokunmadan, WebKarne kimliği dururken pencereli Chromium 12 engelden 7'sini açtı
  (işbank, trendyol, n11, lcw, teknosa, getir, decathlon); hepsiburada, pegasus,
  yemeksepeti, arçelik, beko, THY yine engelledi ve öyle kaydedilir. Gerekçe: sıradan
  ziyaretçi pencereli tarayıcı kullanır; otomasyon-imzalı modu seçmemek bot korumasını
  aşmak değildir (UA sahtelenmez, kimlik açık, §4). Ekran dışı pencerede arka plan
  kısıtlaması kapatılır ki sayfa normal hızda çalışsın. Kullanılan mod her payload'da
  (`browser.headless`) kayıtlıdır; tur boyunca sabit tutulur.
- **Onay arayüzü gözlemi (`consent_ui`), iki durumda da.** Toplayıcı yalnız gözlem
  yazar: CMP imzaları ve kanıtı (global değişken, betik host'u, seçici), TCF API varlığı,
  banner (hangi kuralla bulundu, çerçeve, shadow DOM içinde mi, metni — ilk 2000
  karakter) ve banner içindeki **tüm** tıklanabilir kontroller (etiket metni, geometri,
  görünürlük/opaklık/display, CSS id), eşleşen rol (`reject`/`accept`/`settings`) ve
  eşleşen kural kimliği. Gizli kontroller de kaydedilir (dr.com.tr'de Cookiebot "Reddet"
  düğmesi DOM'da ama `visibility:hidden; opacity:0`; görünür reddet, banner metnindeki
  tıklanabilir "Reddet" kelimesidir). "Reddet ilk ekranda mı", "karanlık
  desen mi" yargısı analiz katmanındadır. `untouched` durumunda arayüz gözlem penceresinin
  sonunda okunur; tıklama yoktur.
- **Kural seti config'de (`[web_privacy.consent]`), yeni bağımlılık yok.** (1) CMP'ye
  özgü imzalar ve banner/kontrol seçicileri (OneTrust, Cookiebot, Didomi, Usercentrics,
  CookieYes, Complianz, iubenda ve yerli **Efilli**); (2) Türkçe+İngilizce etiket
  kalıpları (CMP'siz özel banner'lar ve CMP'nin standart dışı düğmeleri için — ör.
  vodafone.com.tr OneTrust'ta "Reddet" metin içi bir bağlantıdır). Etiketler Türkçe-duyarlı
  küçük harfe normalize edilir; sınıflandırma Python'da saf fonksiyondur. Kural listesi
  `config_hash`'e girer; eşleşen kural kanıt olarak yazılır.
- **"Reddet" tanımı: yalnız ilk katman.** Banner'ın ilk ekranındaki, **görünür**, reddet
  rolüyle eşleşen **tek** kontrole **bir kez** tıklanır; "yalnızca zorunlu çerezler"
  türü seçenekler de reddet sayılır ama ayrı kural kimliğiyle kaydedilir (analiz
  ayırabilir). Öncelik: CMP'ye özgü kural, sonra etiket kalıbı. İkinci katmana (Ayarlar)
  inilmez; ilk katmanda görünür reddet yoksa tıklanmaz ve `control_not_found` yazılır
  (kendisi bir gözlemdir). Gizli bir kontrole asla tıklanmaz.
- **Reddet protokolü.** Temiz bağlam → ana sayfa → banner/reddet kontrolü için en çok
  `banner_wait_seconds` beklenir → tıklama → 15 sn gözlem → **ana sayfa bir kez yeniden
  yüklenir** (birçok site onayı sonraki sayfa görüntülemesinde uygular) → 15 sn gözlem →
  banner yeniden okunur. Her istek navigasyon başından `t_ms` ve faz (`before_action` /
  `after_action` / `after_reload`) taşır; çerez ve storage anahtarları her fazın sonunda
  anlık görüntü olarak kaydedilir. Tıklama olmazsa (banner/kontrol yok, tıklama başarısız)
  sonrası gözlenmez ve yeniden yükleme yapılmaz; sonuç `consent_action.result`'ta durur
  (`clicked` / `banner_not_found` / `control_not_found` / `click_failed`), sayfa yüklendiyse
  `outcome` yine `loaded`'dır. `interactions` en çok bir reddet tıklaması içerebilir.
- **Blok işaretleri genişletildi.** Bazı engel sayfaları 200 döner (işbank: "İstek
  Engellendi") ya da Türkçedir (decathlon: "Bir dakika lütfen..."): durum kodundan bağımsız
  sayılan ayrı bir başlık listesi eklendi.

---

## 3. Ne ölçüyoruz

Dört boyut, dört bağımsız toplayıcı. İlk ikisi tamamen pasif ve saniyeler
sürüyor; üçüncüsü gerçek tarayıcı gerektiriyor ve pahalı; dördüncüsü
diğerlerinin verisinden türetiliyor.

### A — E-posta ve alan adı kimliği

*Yalnızca DNS sorgusu · alan adı başına ~1 saniye · hedef sisteme dokunmuyor · ilk modül*

| Gösterge | Ne bakılıyor | Neden önemli |
|---|---|---|
| **SPF** | Kayıt var mı, birden fazla mı (varsa kayıt geçersiz), sonlandırıcı `-all` / `~all` / `?all` / `+all`, DNS sorgu sayısı 10 sınırını aşıyor mu, `include` zinciri kim | Sonlandırıcı gevşekse ya da sorgu sınırı aşılmışsa kayıt görünürde vardır ama koruma yoktur — "var/yok" ölçen araçların kaçırdığı yer |
| **DMARC** | Kayıt, `p=` politikası, `sp=` alt alan politikası, `pct=`, `rua`/`ruf` rapor adresi, sözdizimi | Tek en güçlü gösterge. `p=none` "izliyorum ama engellemiyorum" demek; rapor adresi yoksa izleme de yok, kayıt tamamen sembolik |
| **DKIM** | Yaygın seçicilerde kayıt taraması, anahtar uzunluğu, boş `p=` | Seçici adları DNS'ten keşfedilemez, tahmin edilir — bilinen yöntem sınırlılığı, tezde açıkça yazılacak |
| **MX** | Kayıt var mı, kaç tane, hangi sağlayıcı | Sektör analizinin altın verisi: "üniversitelerin %X'i postasını yurt dışı sağlayıcıda tutuyor" |
| **MTA-STS · TLS-RPT** | `_mta-sts` TXT + `/.well-known/mta-sts.txt`, `_smtp._tls` kaydı | Posta aktarımının zorunlu şifreli olup olmadığı; yaygınlığın düşük çıkması kendi başına bulgu |
| **DANE / TLSA** | MX sunucuları için TLSA kayıtları | Bir üst seviye posta güvenliği; DNSSEC ile birlikte anlam kazanır |
| **DNSSEC** | DS kaydı, imza zinciri doğrulanıyor mu | Alan adının sahteciliğe karşı korunması |
| **CAA** | Hangi sertifika otoritelerine izin verilmiş | Yetkisiz sertifika üretimine karşı koruma |
| **Alt alan adları** | Sertifika Şeffaflığı loglarından (crt.sh) pasif çıkarım | Kurumun gerçek dijital yüzeyi ana alan adından büyüktür |

### B — Aktarım ve sunucu güvenliği

*HTTP/TLS bağlantısı · alan adı başına birkaç saniye · sadece ana sayfa isteği*

| Gösterge | Ne bakılıyor | Neden önemli |
|---|---|---|
| **HTTPS zorunluluğu** | `http://` isteği nereye gidiyor, kaç adımda, ara adımlarda şifresiz atlama var mı | Zincirdeki tek şifresiz adım tüm önlemleri boşa çıkarır |
| **TLS yapılandırması** | Desteklenen sürümler (1.0/1.1 açık mı, 1.3 var mı), şifre takımları | En kolay ölçülen, en kolay düzeltilen zafiyet sınıfı |
| **Sertifika** | Geçerlilik, kalan gün, veren, zincir bütünlüğü, alan adı eşleşmesi | Süresi dolmak üzere olan sertifika, izleme aracının en somut faydası |
| **HSTS** | Başlık, `max-age` yeterliliği, `includeSubDomains`, preload | Kısa `max-age` ya da alt alanları kapsamayan politika korumanın yarısıdır |
| **Güvenlik başlıkları** | CSP (ve `unsafe-inline` yüzünden anlamsızlaşmış mı), `X-Frame-Options`/`frame-ancestors`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` | Başlığın varlığını saymak kolay, işe yarayıp yaramadığını değerlendirmek zor — ayrıştığımız yer |
| **Bilgi sızıntısı** | `Server`, `X-Powered-By`, `X-Generator` | Saldırgana bedava istihbarat; D boyutuyla birleşince risk sinyali |
| **security.txt** | `/.well-known/security.txt` var mı, iletişim geçerli mi | Güvenlik bildirim kanalı olup olmadığı; nadir ve ayırt edici olgunluk göstergesi |
| **Çerez nitelikleri** | `Secure`, `HttpOnly`, `SameSite` | B ile C arasındaki köprü: aynı çerez hem güvenlik hem gizlilik açısından puanlanır |

### C — Gizlilik ve izleme

*Gerçek tarayıcı (Playwright) · alan adı başına ~45 sn × üç onay durumu · en pahalı, en değerli boyut*

Her site üç kez ziyaret edilir: **dokunmadan** (banner'a hiç tıklamadan,
15 sn bekleyerek), **reddettikten sonra**, **kabul ettikten sonra**. Her
durumun sonucu ayrı kaydedilir.

| Gösterge | Ne bakılıyor | Neden önemli |
|---|---|---|
| **Çerezler (tam liste)** | Tarayıcı protokolü üzerinden *bütün* çerezler — HttpOnly dahil. Ad, alan, birinci/üçüncü taraf, ömür, nitelikler, hangi onay durumunda yazıldığı | JavaScript'ten bakan araçlar HttpOnly çerezleri göremez; araçların birbirini tutmamasının başlıca sebebi bu |
| **Depolama** | localStorage, sessionStorage, IndexedDB anahtarları | Çerez sayılmadığı için denetimden kaçan izleme yöntemi |
| **Üçüncü taraf istekleri** | Host, kaynak türü, boyut; host bir izleyici veri setiyle eşleştirilip sahibi şirkete ve ülkeye bağlanır | Ağ ve yoğunlaşma analizinin hammaddesi |
| **Bilinen etiketler** | GA4, Tag Manager, Meta Pixel, TikTok, Hotjar, Clarity, Yandex Metrica vb. imza tespiti | Sektör karşılaştırmasında en okunaklı gösterge |
| **Parmak izi teknikleri** | Canvas, WebGL, AudioContext, font sayımı API çağrılarının JS kancalarıyla yakalanması | Çerezsiz izleme; teknik olarak en zor kısım, yöntemi literatürde hazır |
| **Onay arayüzü** | Banner var mı, "reddet" ilk ekranda mı, önceden işaretli kutu var mı, hangi onay platformu | Karanlık desen ölçümü; davranışsal katman |
| **Yurt dışına aktarım** | Üçüncü taraf hostların ülke çözümlemesi; Google Fonts gibi klasiklerin ayrıca işaretlenmesi | KVKK'nın en tartışmalı maddelerine doğrudan veri |
| **Politika metinleri** | Gizlilik politikası, çerez politikası, KVKK aydınlatma metni; bulunuyorsa metin saklanır | E boyutunun girdisi; şimdi toplanmazsa sonra yeniden tarama gerekir |

### D — Teknoloji ve görünen yüzey

*Diğer toplayıcıların verisinden türetilir · ek istek gerektirmez*

| Gösterge | Ne bakılıyor | Neden önemli |
|---|---|---|
| **Platform ve sürüm** | WordPress, WooCommerce, Ticimax, İdeasoft, T-Soft, Shopify, OpenCart… ve sürüm numaraları | Türkiye e-ticaretinin platform dağılımı tek başına yayınlanabilir bulgu |
| **Eklenti envanteri** | Varlık adreslerindeki `?ver=` parametrelerinden eklenti ve tema sürümleri | Kurumun ilan ettiği yazılım envanteri; zafiyet veritabanlarıyla eşleştirilebilir |
| **JS kütüphaneleri** | jQuery, React vb. sürümleri, bilinen zafiyetli sürüm listeleriyle karşılaştırma | Dışarıdan gözlemlenebilir risk sinyali — F boyutunun en güçlü girdilerinden |
| **Altyapı** | CDN/WAF, barındırma sağlayıcısı, IP'nin ülkesi | Yoğunlaşma analizinin ikinci ekseni |

### internet.nl ile kapsam denkliği (parity)

internet.nl olgun, kamuya açık bir denetim aracıdır ve bu proje için doğal bir dış
referanstır. **Hedef:** internet.nl'in hem "website" hem "email" testinde baktığı
her göstergeyi Karne de ölçsün; örtüşen her yerde sonuçlar **uyumlu** olsun. Bu
örtüşme tezde bağımsız bir doğrulama ekseni sağlar — bir aracın bulgusunu diğeri
teyit eder. Fark: Karne ham veriyi saklar ve puanı ayrı katmanda üretir (K-02),
bu yüzden yüzde/not değil **göstergeler** kıyaslanır.

| internet.nl göstergesi | Karne karşılığı | Durum |
|---|---|---|
| SPF · DKIM · DMARC | A boyutu | ✅ Sprint 0 |
| DNSSEC | A boyutu | ✅ Sprint 0 (alan adının DS'i; MX host imzası eklenecek) |
| DANE / TLSA | A boyutu | ✅ Sprint 0 (Adım 3'te atlanmış, sonradan eklendi) |
| MTA-STS · TLS-RPT | A boyutu | ✅ Sprint 0 |
| STARTTLS (posta sunucu TLS) | — (K-07: pasif kalır) | ❌ Kapsam dışı; DNS-tarafı DANE/MTA-STS/TLS-RPT karşılar (bkz. bölüm 4) |
| IPv6 / erişilebilirlik | A boyutu — yeni (AAAA kaydı varlığı) | ⏳ Sprint 2 |
| HTTPS zorunluluğu · TLS · sertifika · HSTS | B boyutu | ⏳ Sprint 3 |
| Güvenlik başlıkları (CSP, X-Frame-Options…) | B boyutu | ⏳ Sprint 3 |
| RPKI (route origin doğrulama) | D boyutu — yeni (altyapı) | ⏳ Sprint 5 |

**Yeni eklenen göstergeler ve yerleri:**

- **IPv6 / AAAA (Sprint 2).** internet.nl gerçek IPv6 *erişilebilirliğini* test
  eder; Karne pasif modelde web/MX/NS için **AAAA kaydı varlığını** ölçer (saf DNS,
  erişilebilirliğe iyi bir vekil). Canlı bağlantı testi yapılmaz.
- **STARTTLS (karar bekliyor).** Posta sunucusunda TLS pazarlığını görmek port
  25'e canlı SMTP bağlantısı gerektirir; K-07'nin "pasif / tarayıcı-eşdeğeri"
  sınırıyla gerilim taşır. Karar verilene kadar Karne posta-aktarım güvenliğini
  yalnız DNS-tarafı sinyallerle (MTA-STS, TLS-RPT, DANE) ölçer.
- **RPKI (Sprint 5).** Alan adının sunucu IP'leri için ROA doğrulaması; pasif
  (RPKI deposu / RIPE verisi sorgusu). D boyutuna (altyapı) girer.

### Sonraki fazların boyutları

**E — Beyan ile gerçek (Nisan).** C boyutunda toplanan politika metinleri bir
dil modeliyle yapılandırılır (hangi veri toplanıyor, kimlerle paylaşılıyor,
yurt dışı aktarım beyan ediliyor mu) ve gözlenen davranışla karşılaştırılır.
Çıktı: kurum bazında çelişki listesi.

**F — Risk skoru ve doğrulama (Nisan–Mayıs).** Dört boyutun göstergelerinden
bileşik risk skoru üretilir, KVKK'nın kamuya açıkladığı veri ihlali
bildirimleriyle eşleştirilerek öngörü gücü test edilir.

---

## 4. Etik ve hukuki sınırlar

Bu bölüm tezin ayrı bir alt başlığı olacak ve kodun içinde yaşayacak.
Sınırların bir kısmı yorum değil, doğrudan yazılım kısıtıdır.

### Yapıyoruz

- Yalnızca kamuya açık veri: sıradan bir ziyaretçinin tarayıcısının gördüğü ve herkese açık DNS kayıtları
- Alan adı başına saniyede en fazla bir istek, eşzamanlılık sınırlı, tarama gece saatlerinde
- Tarayıcı kimliğini açıkça bildirir: kullanıcı aracısı dizesinde proje adı ve bilgi sayfası adresi (`WebKarne/1.0 (+https://webkarne.com/tr/hakkinda; …)`, bkz. K-14; gerçek tarayıcı ölçümünde Chromium UA'sına ek olarak, bkz. K-16). Tarayıcı ölçümü pencereli Chromium ile yapılır: otomasyon-imzalı headless mod seçilmez, UA sahtelenmez (K-16 eki)
- Taranmak istemeyen kurumlar için vazgeçme kanalı; bu tezde raporlanır
- Kurum bazında ciddi bulgular önce ilgili kuruma bildirilir, yayına sektör toplamıyla çıkılır
- Bölüm etik kurul onayı istiyorsa **Ekim ayında** başvurulur

### Yapmıyoruz

- Zafiyet sömürme, giriş denemesi, form gönderme, ödeme akışına dokunma
- Dizin/dosya deneme, yönetim paneli arama, port taraması
- DNS bölge transferi (AXFR) denemesi — teknik olarak mümkün ama gri alan, kapsam dışı
- Kişisel veri toplama; ölçüm kurumsal alan adı düzeyinde kalır
- Bot korumasını aşmaya çalışma; engellenirsek "ölçülemedi" diye kaydedip geçeriz

### Sınır kararı: STARTTLS — DNS-pasif kalınır

internet.nl, posta sunucularında STARTTLS'i **canlı SMTP bağlantısıyla** test eder.
Bu, saf DNS'in ötesinde port 25'e bağlantı demektir ve yukarıdaki "port taraması
yok / tarayıcının gördüğünden fazlası yok" sınırıyla gerilim taşır.

**Karar (2026-09-11): Karne STARTTLS için canlı SMTP bağlantısı yapmaz.** K-07
korunur; posta-aktarım güvenliği yalnız DNS-tarafı sinyallerle (MTA-STS, TLS-RPT,
DANE) ölçülür. Konu, aktarım katmanının ele alındığı **Sprint 3'te**, gerekirse
etik kurul bağlamıyla yeniden değerlendirilebilir; o zamana dek kapsam dışıdır ve
bu paragraf güncellenmeden STARTTLS kodu yazılmaz.

### Sınır kararı: TLS sürüm keşfi — çoklu el sıkışma kabul edilir

*(Karar: 2026-09-11, Sprint 3 · B boyutu.)* B boyutu, bir sitenin desteklediği TLS
sürümlerini (1.0/1.1/1.2/1.3) ölçmek için **her sürüme standart 443 portu üzerinden
ayrı bir TLS el sıkışması** dener. Bu, tarayıcının pazarlıkla seçtiği tek sürümün
ötesine geçer ama **port taraması, zafiyet denemesi veya sömürü değildir**: yalnız
herkese açık HTTPS portunda sıradan el sıkışmalardır (bir tarayıcı da 1.3 başarısız
olursa 1.2 dener). K-07'nin "sıradan bir ziyaretçinin gördüğünden fazlası yok"
sınırı içinde kabul edilir; STARTTLS'ten (port 25'e canlı SMTP) farkı budur.
Sınırlar korunur: **cipher takımlarının tam taraması YAPILMAZ** (her sürümde yalnız
pazarlıkla seçilen cipher kaydedilir); dizin/dosya denemesi, form gönderimi yok;
her istekte timeout + hız sınırı zorunlu. Sertifika: önce doğrulayan el sıkışma
(verified + neden), başarısızsa doğrulamasız ikinci el sıkışma ile sertifika
detayı yine de kaydedilir (süresi dolmuş/self-signed'i görebilmek için). HTTP
zorunluluğu: `http://` kökünden en çok 10 hop yönlendirme zinciri izlenir; her
hop'un şeması/host'u/durumu kaydedilir, ara şifresiz adım ve host değişimi
işaretlenir. Toplayıcı yine yorum yapmaz (rule 1); "1.0 açık = kötü", "max-age
kısa" gibi yargılar puanlama katmanındadır (K-02).

---

## 5. Veri modeli

Sekiz tablo yetiyor. K-02'nin karşılığı: `scan_results` ham JSON'u tutar ve
hiç değişmez; `scores` ve `findings` ondan türetilir, silinip yeniden
üretilebilir.

```
domains        id · domain · source · sector · is_public_body · added_at
scans          id · domain_id · started_at · finished_at · scanner_version
               · config_hash · consent_state · status · error
               (consent_state: C boyutunda kullanılmaz, üç durum payload'da — K-16)
scan_results   scan_id · collector · payload_json          ← ham, dokunulmaz
cookies        scan_id · name · domain · party · http_only · secure
               · samesite · lifetime_days · consent_state
requests       scan_id · host · party · resource_type · tracker_org · country
dns_records    scan_id · rtype · selector · value · valid · notes
scores         scan_id · dimension · raw_score · grade · ruleset_version
findings       scan_id · code · severity · evidence_json · fix_hint_key
```

`findings.code` sabit bir kod listesinden gelir (`EMAIL_NO_DMARC`,
`PRIVACY_PRECONSENT_TRACKER`, `TLS_LEGACY_VERSION`…). Düzeltme talimatı ve
açıklama metinleri koda değil çeviri dosyalarına yazılır — iki dilli arayüz
bu sayede bedava gelir.

---

## 6. Depo yapısı

```
karne/
  CLAUDE.md                 # Claude Code'un uyacağı kurallar
  pyproject.toml
  docs/
    PLAN.md                 # bu dosya
    PROGRESS.md             # her oturumun sonunda güncellenir
  config/
    settings.toml           # tarama parametreleri, hız sınırları, seçici listeleri
    scoring.toml            # ağırlıklar, eşikler, harf notu sınırları (sürümlü)
  karne/
    models.py               # veri şeması
    storage.py              # SQLite katmanı
    frontier.py             # alan adı listesi ve sektör etiketleri
    collectors/
      dns_email.py          # A boyutu
      tls_http.py           # B boyutu
      web_privacy.py        # C boyutu (Playwright, üç onay durumu)
      fingerprint.py        # D boyutu
    analyze/
      scoring.py            # ham → not
      graph.py              # üçüncü taraf ağı, yoğunlaşma
      policy_check.py       # E boyutu (Nisan)
      risk_model.py         # F boyutu (Mayıs)
    api/main.py             # FastAPI
    web/                    # arayüz + i18n (tr/en)
    cli.py                  # karne scan / batch / rescore / export
  data/karne.db             # gitignore'da
  notebooks/                # tez bulgularının üretildiği defterler
  paper/                    # tez metni ve şekiller
  tests/
```

---

## 7. Takvim

Sıra bilinçli: en riskli ve en yaratıcı işler ortada, sonda yalnızca yazım var.
Aralık sonundaki kilometre taşı kritik — orada hem yayınlanabilir bir bulgu
hem canlı bir araç oluyor, projenin geri kalanı bonus hâline geliyor.

### Sprint 0 · 10–30 Eylül — İskelet ve ilk ölçüm

Depo, CLAUDE.md, paket yapısı, SQLite şeması, `karne scan <domain>` komutu.
Yalnızca A boyutu. Kendi alan adın ve tanıdığın on kurumla test.

**Çıktı:** tek komutla bir alan adının e-posta karnesi

### Sprint 1 · Ekim — Örneklem: Türkiye evreni

Tranco listesinden ve `.tr` uzantılardan Türkiye evrenini çıkar. Sektör
etiketle: banka, üniversite, kamu kurumu, belediye, hastane, e-ticaret, medya.
"Türk sitesi" tanımını yaz ve savun — bu bir yöntem kararı, tezde bir sayfa
yer tutacak. Etik kurul gerekiyorsa başvuru bu ay.

**Çıktı:** ~10.000 alan adlık, sektör etiketli örneklem çerçevesi

### Sprint 2 · Kasım — İlk ülke çapı tarama

Toplu tarama altyapısı: paralellik, hız sınırı, hata yönetimi, yarıda kalan
taramayı sürdürme. A boyutunu tüm örnekleme uygula. İlk analiz defteri.
**Aylık cron bu ay devreye girer ve bir daha durmaz.**

**Bulgu #1:** Türkiye'nin e-posta güvenliği karnesi

### Sprint 3 · Aralık — Puanlama motoru ve canlı araç ★ KİLOMETRE TAŞI

B boyutu (TLS/HTTP), `scoring.toml`, harf notu mantığı, bulgu kodları ve
düzeltme metinleri. FastAPI + iki dilli arayüz, VPS kurulumu, alan adı
sorgulama. Kendi tekstil işinin sitesi ilk gerçek kullanıcı.

**Çıktı:** savunulabilir minimum tez + canlı ürün

### Sprint 4 · Ocak–Şubat — Gizlilik boyutu

En zor teknik parça, iki aya yayılmış. Playwright altyapısı, üç onay durumu,
çerezlerin tam listesi, üçüncü taraf eşleştirme, parmak izi kancaları, banner
ve karanlık desen tespiti. Politika metinleri de bu taramada toplanır.

**Bulgu #2:** Türk sitelerinde onay öncesi izleme

### Sprint 5 · Mart — Ağ, yoğunlaşma, parmak izi

D boyutu ve graf analizi: kim kimi görüyor, kaç kurum aynı sağlayıcıya
bağımlı, tek bir servis düşerse ne olur. Sektör panoları ve karşılaştırmalı
görselleştirmeler arayüze girer.

**Bulgu #3:** Türkiye internetinin bağımlılık haritası

### Sprint 6 · Nisan — Beyan-gerçek ve risk modeli

E boyutu: politika metinlerinin dil modeliyle yapılandırılması ve gözlenen
davranışla karşılaştırılması. F boyutu: bileşik risk skoru ve KVKK ihlal
bildirimleriyle doğrulama.

**Bulgu #4:** skorun öngörü gücü

### Sprint 7 · Mayıs–Haziran — Değerlendirme, yazım, teslim

Tasarım bilimi çerçevesinde değerlendirme: kullanıcı testleri, uzman
görüşleri, araç kullanım istatistikleri. Boylamsal analiz (Kasım–Mayıs, yedi
ölçüm). Tez yazımı, veri setinin yayını, savunma.

**Teslim:** tez + canlı araç + açık veri seti

---

## 8. Claude Code ile çalışma düzeni

Kod Claude Code ile yazılıyor. Düzen olmazsa üç ay sonra proje kendi içinde
kaybolur. Dört kural:

1. **Üç dosya kalıcı hafızadır.** `docs/PLAN.md` ne yapacağımızı,
   `CLAUDE.md` nasıl yapacağımızı, `docs/PROGRESS.md` nereye kadar geldiğimizi
   tutar. Her oturum bu üçünü okuyarak başlar, PROGRESS.md güncellenerek biter.

2. **Bir oturum, bir modül.** Toplayıcılar bilerek küçük ve bağımsız
   tasarlandı. "SPF ayrıştırıcısını yaz ve şu on alan adında test et" iyi bir
   görev; "gizlilik modülünü yap" kötü bir görev.

3. **Önce beklenen çıktı, sonra kod.** Her toplayıcı için bilinen bir alan
   adının beklenen sonucunu elle yazıp teste koy. Ölçüm kodunda sessiz hata en
   tehlikeli hatadır: kod çalışır, sayı üretir, sayı yanlıştır.

4. **Her sprint sonunda üç şey.** Çalışan kod, bulguyu üreten bir analiz
   defteri, tez metnine giren birkaç paragraf. Yazımı sona bırakırsan Mayıs'ta
   sekiz ayı hatırlamaya çalışırsın.