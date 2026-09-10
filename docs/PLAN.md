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
- Tarayıcı kimliğini açıkça bildirir: kullanıcı aracısı dizesinde proje adı ve bilgi sayfası adresi
- Taranmak istemeyen kurumlar için vazgeçme kanalı; bu tezde raporlanır
- Kurum bazında ciddi bulgular önce ilgili kuruma bildirilir, yayına sektör toplamıyla çıkılır
- Bölüm etik kurul onayı istiyorsa **Ekim ayında** başvurulur

### Yapmıyoruz

- Zafiyet sömürme, giriş denemesi, form gönderme, ödeme akışına dokunma
- Dizin/dosya deneme, yönetim paneli arama, port taraması
- DNS bölge transferi (AXFR) denemesi — teknik olarak mümkün ama gri alan, kapsam dışı
- Kişisel veri toplama; ölçüm kurumsal alan adı düzeyinde kalır
- Bot korumasını aşmaya çalışma; engellenirsek "ölçülemedi" diye kaydedip geçeriz

---

## 5. Veri modeli

Sekiz tablo yetiyor. K-02'nin karşılığı: `scan_results` ham JSON'u tutar ve
hiç değişmez; `scores` ve `findings` ondan türetilir, silinip yeniden
üretilebilir.

```
domains        id · domain · source · sector · is_public_body · added_at
scans          id · domain_id · started_at · finished_at · scanner_version
               · config_hash · consent_state · status · error
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