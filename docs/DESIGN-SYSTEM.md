# WebKarne — Design System & UX Specification

> Bu belge arayüzün tek referans kaynağıdır. Arayüzle ilgili her karar burada
> yazılıdır; burada yazmayan bir davranış uygulanmadan önce buraya eklenir.
>
> Belge Türkçedir (iç plan belgesi). Kod, sınıf adları ve commit mesajları
> İngilizcedir. Kullanıcıya görünen her metin çeviri dosyalarından gelir (K-08).
>
> İlgili belgeler: `docs/PLAN.md` (sistem planı), `CLAUDE.md` (kod kuralları).

---

## 0 · Bu belge nasıl kullanılır

Arayüz işi yapan her oturum bu belgeyi okur. Üç kural:

1. **Hiçbir görsel değer doğrudan yazılmaz.** Renk, boşluk, yazı boyutu, süre,
   yarıçap — hepsi `web/static/tokens.css` içindeki değişkenlerden gelir. Yeni
   bir değer gerekiyorsa önce token olarak tanımlanır ve bu belgeye işlenir.
2. **Yeni bileşen icat edilmez.** Bölüm 6'daki envanter kapalıdır. Bir ihtiyaç
   mevcut bileşenlerle karşılanamıyorsa önce gerekçe yazılır, sonra eklenir.
3. **Yeni görsel dil önerilmez.** Editorial / dijital rapor estetiği sabittir.

---

## 1 · Tasarım ilkeleri

- **Teknik sonuç, insan dili.** Kullanıcı teknik bilgiye zorla maruz kalmaz;
  isteyen üç kademe derine iner.
- **Bilgi yoğunluğu olur, görsel karmaşa olmaz.** Ayrım boşlukla yapılır.
- **Renk yalnızca anlam taşır.** Dekorasyon için renk kullanılmaz.
- **Sakinlik, düşük notta bile.** F alan bir kurumu korkutmuyoruz; ne olduğunu
  ve nasıl düzelteceğini anlatıyoruz.
- **Animasyon fark edilmez.** Bir hareket dikkat çekiyorsa yanlıştır.
- **Ölçemediğimizi ölçmüş gibi göstermeyiz.** Belirsizlik açıkça yazılır.

---

## 2 · Tokenlar

### 2.1 Renk

Nötr ölçek — arayüzün tamamı bunun üzerine kurulur.

| Token | Değer | Kullanım |
|---|---|---|
| `--bg` | `#F7F6F2` | Sayfa zemini (kırık beyaz) |
| `--surface` | `#FFFFFF` | Kart, kutu, panel zemini |
| `--surface-sunken` | `#F1EFEA` | Kod kutusu, tablo başlığı |
| `--ink` | `#17191A` | Birincil metin, başlıklar |
| `--ink-2` | `#575D60` | Gövde metni, açıklama |
| `--ink-3` | `#8B9095` | Etiket, eyebrow, ikincil bilgi |
| `--ink-4` | `#B4B8BB` | Devre dışı, "uygulanamaz" |
| `--line` | `#E4E1DB` | Hairline, kart kenarlığı |
| `--line-strong` | `#CBC7BF` | Bölüm ayracı, tablo çizgisi |

Anlam renkleri — **yalnızca** not, şiddet, delta ve durum için.

| Token | Değer | Anlam |
|---|---|---|
| `--good` | `#1C7A50` | A notu, olumlu, marka vurgusu, "sizin puanınız" |
| `--good-tint` | `#E9F2ED` | Olumlu bilgi kutusu zemini |
| `--info` | `#2A5FA5` | B notu, nötr teknik bilgi |
| `--info-tint` | `#E8EFF7` | Bilgi kutusu zemini |
| `--warn` | `#A5761C` | C notu, "Orta" şiddet |
| `--warn-tint` | `#FAF2E1` | Orta şiddet hapı zemini |
| `--bad` | `#C0392E` | D–F notu, "Yüksek" şiddet |
| `--bad-tint` | `#FBEAE8` | Yüksek şiddet hapı, puan kaybı kutusu |
| `--neutral-tint` | `#EEECE7` | "Düşük" şiddet hapı |

**Kural:** Bu tablonun dışında renk yoktur. Grafiklerde de yoktur — gri bağlam,
yeşil "sen". Marka için ayrı bir aksan rengi eklenmez.

### 2.2 Tipografi

| Rol | Aile | Not |
|---|---|---|
| Display | `Playfair Display` | Başlıklar, alan adı, not harfleri, alıntılar. Yalnızca 20px üstü. |
| Gövde/arayüz | `Public Sans` | Gövde, etiket, buton, navigasyon |
| Veri | `IBM Plex Mono` | DNS kayıtları, ham çıktı, sayısal tablolar |

**Zorunlu kontrol:** Seçilen her yazı tipi `ğ Ğ ş Ş ı İ ç Ç ö Ö ü Ü` karakterlerini
taşımalıdır. Google Fonts'tan `latin-ext` alt kümesi istenir. Karakteri eksik bir
yazı tipi kullanılamaz — Türkçe metinde sessizce başka bir yazı tipine düşer ve
tüm sayfa bozulur.

Yedek yığınlar: display → `Georgia, 'Times New Roman', serif` ·
gövde → `-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif` ·
veri → `ui-monospace, Menlo, monospace`

### 2.3 Tipografi ölçeği

| Token | Boyut / satır | Harf aralığı | Kullanım |
|---|---|---|---|
| `--t-display-xl` | 64 / 1.05 | -0.022em | Ana sayfa başlığı |
| `--t-display-l` | 46 / 1.08 | -0.02em | Ekran başlığı, alan adı |
| `--t-display-m` | 34 / 1.16 | -0.015em | Bulgu başlığı |
| `--t-grade-xl` | 92 / 1.0 | -0.03em | Genel not harfi |
| `--t-grade-m` | 38 / 1.0 | -0.02em | Boyut kartı not harfi |
| `--t-section` | 22 / 1.3 | -0.01em | Bölüm başlığı (serif) |
| `--t-h3` | 17 / 1.4 | 0 | Alt başlık (sans, 600) |
| `--t-body` | 15.5 / 1.62 | 0 | Gövde |
| `--t-small` | 13.5 / 1.55 | 0 | Açıklama, yardımcı metin |
| `--t-label` | 10.5 / 1.4 | 0.14em | Eyebrow, etiket (büyük harf) |
| `--t-mono` | 13 / 1.6 | 0 | Kod, DNS kaydı |

Mobilde (`< 720px`) display ölçekleri sırasıyla 40 / 32 / 26'ya iner; gövde
değişmez.

### 2.4 Boşluk

4 tabanlı ölçek: `4 · 8 · 12 · 16 · 24 · 32 · 48 · 64 · 96 · 128`
Tokenlar `--s-1` … `--s-10`. Ölçek dışı değer kullanılmaz.

Bölüm arası dikey ritim: masaüstü `--s-8` (64), mobil `--s-6` (32).

### 2.5 Kenar, yarıçap, gölge

| Token | Değer |
|---|---|
| `--hairline` | `1px solid var(--line)` |
| `--r-box` | `3px` — kart, kutu, input |
| `--r-pill` | `999px` — şiddet hapları |
| `--shadow` | **yok** |

Gölge yoktur. Tek istisna: yapışkan üst bant kaydırıldığında alt hairline
belirir — gölge değil, çizgi.

### 2.6 Hareket

| Token | Değer | Kullanım |
|---|---|---|
| `--t-fast` | 120ms | Hover, odak, buton |
| `--t-base` | 200ms | Beliren içerik, geçiş |
| `--t-slow` | 320ms | Akordiyon açılışı |
| `--ease` | `cubic-bezier(0.22, 1, 0.36, 1)` | Varsayılan (yumuşak çıkış) |
| `--ease-inout` | `cubic-bezier(0.65, 0, 0.35, 1)` | İki yönlü geçiş |

**Kurallar:** Yalnızca `opacity` ve `transform` animasyonlanır (yükseklik için
`grid-template-rows: 0fr → 1fr` tekniği kullanılır). Sayfa geçişi animasyonu
yoktur. `prefers-reduced-motion: reduce` altında tüm süreler `1ms`, tüm
`transform` değerleri `none`.

### 2.7 Kırılım noktaları

| Ad | Aralık | Düzen |
|---|---|---|
| `sm` | `< 720px` | Tek kolon, sidebar çekmece, sağ kolon içeriğe gömülü |
| `md` | `720 – 1079` | Tek kolon, sidebar çekmece, sağ kolon ana içeriğin altında |
| `lg` | `1080 – 1439` | Sidebar sabit, sağ kolon ana içeriğin altında |
| `xl` | `≥ 1440` | Tam üç kolon |

---

## 3 · Düzen

### 3.1 Ölçüler

| Öğe | Değer |
|---|---|
| Sayfa maksimum genişliği | 1560px |
| Kenar boşluğu | 32px (mobil 20px) |
| Üst bant yüksekliği | 68px |
| Sol navigasyon genişliği | 264px |
| Sağ kolon genişliği | 340px |
| Ana içerik okuma genişliği | 720px (düz metin) |
| Ana içerik tam genişlik | Izgara ve kart blokları kolonu doldurur |

### 3.2 Analiz kabuğu

```
┌──────────────────────────────────────────────────────────────┐
│  ÜST BANT  (yapışkan)                                        │
├──────────┬───────────────────────────────────┬───────────────┤
│  SOL     │  ANA İÇERİK                       │  SAĞ KOLON    │
│  NAV     │                                   │  (yapışkan)   │
│  (yapış.)│                                   │               │
└──────────┴───────────────────────────────────┴───────────────┘
```

Genel Bakış · Boyut ekranı · Bulgu tam sayfası · Sektör Karşılaştırması —
dördü de bu kabuğun içinde açılır. **Yeni sidebar veya farklı navigasyon icat
edilmez.**

Sol navigasyon ve sağ kolon `position: sticky`, üst bant yüksekliği kadar
offset ile. İkisi de kendi içinde kaydırılabilir.

### 3.3 Üst bant

Sol: kelime markası (display serif) → dikey hairline → iki satır etiket
("ALAN ADLARININ DİJİTAL / GÜVENLİK KARNESİ").
Sağ: `Yeni Analiz · Metodoloji · Sektör Analizleri · Açık Veri · Hakkında` →
dil değiştirici `TR | EN` (aktif olanın altı çizili).

**Düzeltme:** Referans görsellerde ana sayfa ve sonuç ekranlarının bağlantı
listesi farklı. Tek liste kullanılır; yukarıdaki sıra bağlayıcıdır.

### 3.4 Sol analiz navigasyonu

Sıra sabittir:

```
← Yeni analiz
example.com                     (display serif)
Analiz: 12 Eylül 2026           (--t-small, --ink-3)
────────────────────────────
⌂  Genel Bakış
01 E-posta ve Alan Adı Kimliği
02 Aktarım ve Sunucu Güvenliği
03 Gizlilik ve İzleme
04 Teknoloji ve Görünen Yüzey
────────────────────────────
▤  Sektör Karşılaştırması
────────────────────────────
↓  Raporu İndir (PDF)
⧉  Sonucu Paylaş
────────────────────────────
"Daha güvenli bir dijital
gelecek mümkün."   — WebKarne
[dağ illüstrasyonu]
© 2026 WebKarne
```

Aktif öğe: sol kenarda 2px `--good` çubuk + `--surface` zemin. Başka vurgu yok.

**Geri bağlantısı kararı:** Referanslarda "Sonuçlara Dön" ve "Önceki sayfaya dön"
şeklinde iki farklı etiket var ve birincisi zaten sonuçtayken anlamsız. Tek
davranış: her sonuç ekranında **"← Yeni analiz"**, ana sayfaya gider. Bir üst
seviyeye çıkma işini ana içerikteki breadcrumb yapar.

**Ölçülmemiş boyut:** Henüz ölçülmemiş boyutun satırı tıklanabilir kalır, sağında
küçük bir nabız noktası bulunur; o ekrana gidilirse "ölçülüyor" durumu gösterilir.

### 3.5 Ana içerik açılışı

Her ekran aynı ritimle başlar:

```
──── ETİKET (büyük harf, harf aralıklı)
Dev serif başlık
Gövde paragrafı (max 720px)
```

Bu ritim bozulmaz.

---

## 4 · Ekranlar

### 4.1 Ana sayfa

Kabuk yok (sidebar yok). Bol boşluk. İçerik sırası:

1. `01 ——` işareti + display XL başlık + gövde paragrafı
2. Sağda serif italik slogan + kısa kural çizgisi
3. İki sorgu paneli yan yana, aralarında dikey hairline ve ortasında "veya"
   - Sol: `ALAN ADI SORGULA · 01` · küre ikonu · serif alt başlık · input +
     siyah buton "Analiz Et →" · örnek satırı
   - Sağ: `E-POSTA SORGULA · 02` · zarf ikonu · aynı yapı
4. Aşağı ok + `NASIL ÇALIŞIR?` çapası
5. Dağ illüstrasyonu (sağ alt, çok soluk)
6. Alt bant: marka · slogan · Açık kaynak · GitHub ↗ · telif

`md` altında paneller alt alta gelir, "veya" yatay ayraca dönüşür.

### 4.2 Genel Bakış

1. Etiket `DİJİTAL GÜVENLİK KARNESİ` (e-postada `E-POSTA GÜVENLİK KARNESİ`)
2. Display L alan adı + tarih + iki cümlelik özet
3. Sağında dikey hairline ile ayrılmış genel not bloğu: `GENEL GÜVENLİK NOTU`
   etiketi + not harfi (`--t-grade-xl`, not rengi) + `87 / 100`
4. `DÖRT BOYUTTA SONUÇ` etiketi + hairline + dört boyut kartı
5. `Öne Çıkan Bulgular` — en fazla 3 bulgu satırı + "Tüm bulguları gör →"

Sağ kolon sırası: özet tint kutusu (yaprak ikonu) → serif italik alıntı →
Sektör Karşılaştırması kartı (aralık göstergesi) → Sonraki Adımlar kartı
(numaralı 1-2-3 + "Tüm önerileri gör →").

**E-posta varyantı:** Aynı ekran, tek boyutla. Genel not = E-posta ve Alan Adı
Kimliği notu. Dört kart yerine tek kart ve yanında üç boyut için soluk
"alan adı analizinde ölçülür" kartı; bu kartlar tıklanınca aynı alan adı için
tam analiz başlatır. Sağ kolonun ilk kutusu kapsam açıklamasıdır (bkz. 4.7).

### 4.3 Boyut ekranı

1. Breadcrumb: `Genel Bakış › E-posta ve Alan Adı Kimliği`
2. Etiket + display L boyut adı + boyut notu (harf + puan, başlığın sağında)
3. Bir paragraf: bu boyutta neye bakıyoruz
4. **Kontrol listesi** — SPF, DKIM, DMARC, MX, DNSSEC, CAA, MTA-STS, TLS-RPT,
   DANE. Her satır: durum ikonu · kontrol adı · tek cümle sonuç · (varsa) puan
   etkisi · açılım oku
5. Listenin üstünde sağda: `Tümünü aç / Tümünü kapat`

Kontrol satırı bir bulgu taşıyorsa tıklanınca **yerinde açılır** (bölüm 5).
Sorunsuz kontroller de açılabilir; açılımları kısadır ("Bu kontrol nedir" +
"Sizin durumunuz").

Sağ kolon: boyut notu özeti · bu boyuttaki bulgu sayısı şiddete göre ·
"Bu boyut hakkında" rehber bağlantıları.

### 4.4 Bulgu — satır içi açılım ve tam sayfa

Aynı içerik, iki kap. İçerik tek kaynaktan gelir (`findings.code` +
çeviri dosyaları); iki farklı metin yazılmaz.

**Bölüm sırası (her iki kapta aynı):**

1. Puan etkisi satırı — *"Bu bulgu E-posta ve Alan Adı Kimliği puanınızı 15
   düşürüyor."* (tam sayfada sağ kolondaki karta taşınır)
2. **Bu ne anlama geliyor?**
3. **Sizin durumunuz** — mono kutu, sorunlu parça `--bad` ile vurgulu, kopyala
4. **Nasıl düzeltilir?** — numaralı adımlar + önerilen kayıt örneği (mono +
   kopyala) + sağlayıcıya göre not
5. **Teknik Detay** — *varsayılan kapalı*, ham DNS/HTTP çıktısı, sorgu zamanı,
   kullanılan çözümleyici
6. **İlgili Kaynaklar** — rehber bağlantıları (bölüm 7)

**Tam sayfa ek olarak:** breadcrumb, şiddet rozeti + `Önemli Bulgu` hapı,
display M başlık, ve bölüm başlıklarına kaydıran **yapışkan çapa şeridi**.

> Çapa şeridi, referans görselindeki sekme şeridiyle **görsel olarak aynıdır**;
> davranışı sekme değil, kaydırmadır. Gerekçe: sekme, açılımın içinde
> çalışmaz; aynı içeriği iki düzende yazmayı gerektirir; Ctrl+F, yazdırma ve
> PDF'te içeriğin üçte ikisini gizler.

**Tam sayfa sağ kolonu:** Puanınıza Etkisi (not harfi + puan) → Önerilen Kayıt
Örneği (mono + kopyala + not) → Daha Fazla Bilgi (rehber bağlantıları) →
yeşil tint "Hâlâ emin değil misiniz?" + rehber bağlantısı.

### 4.5 Sektör Karşılaştırması

1. Etiket + display L "Sektörünüzdeki konumunuz" + paragraf
2. Sağda serif italik kısa cümle
3. Dört istatistik döşemesi: Sektörünüz · Sektör Ortalaması · Sizin Puanınız ·
   Sektördeki Sıralamanız
4. Histogram — puan dağılımı, gri barlar, kullanıcının bini yeşil, iki kesikli
   referans çizgisi (sektör ortalaması, sizin puanınız)
5. Sağında: boyut bazında sektör farkı (dört satır, `+18 ▲` / `-12 ▼`)
6. Altta: sıralama tablosu (anonim, bkz. aşağı) · sektör dağılımı donutu ·
   "Sektör Analizleri Hakkında" + Metodolojiyi İncele butonu

**Sıralama tablosu — kimlik kuralı:** Diğer kurumlar **adıyla gösterilmez.**
Satırlar `Kurum 1 · 94`, `Kurum 2 · 92` biçimindedir; yalnızca kullanıcının
kendi satırı alan adıyla ve vurgulu görünür. Gerekçe: `docs/PLAN.md` etik
bölümü, kurum bazında teşhiri yasaklar.

**Küçük örneklem kuralı:** Sektörde 20'den az kurum varsa sıralama gösterilmez;
yalnızca dağılım ve ortalama gösterilir, üstte bir satır sebebini açıklar.

**Sektörü belirlenemeyen alan adı:** Sekme kaybolmaz. "Türkiye geneli" moduna
düşer; sektöre özgü satırlar gizlenir, üstte açıklama ve "Sektör seç →" bulunur.

**Sektör düzeltme:** Tahmin edilen sektör başlıkta gösterilir ve
`Sektörünüz: Üniversiteler · değiştir` ile değiştirilebilir. Değişiklik
yalnızca görünümü etkiler, **veri setine yazılmaz.**

### 4.6 Rehber sayfası

Kabuk dışıdır (sidebar yok), ama üst bant ve tipografi aynıdır. Bir analizden
gelindiyse üstte `← analize dön` bulunur ve tam olarak gelinen bulguya döner.

Yapı: display L başlık → bir cümlelik tanım → *Neden var* → *Nasıl çalışır* →
*Yaygın hatalar* → *Nasıl yapılandırılır* (sağlayıcı örnekleriyle) → *Sık
sorulanlar* → *İlgili rehberler*.

### 4.7 E-posta kapsam açıklaması

Şu metin, e-posta analizinin Genel Bakış ekranında **sağ kolonun ilk kutusu**
olarak (mavi tint, `i` ikonu) gösterilir ve kapatılamaz:

> E-posta adresinin içeriği, mesajları veya kişisel verileri analiz edilmez.
> Analiz, adresin bağlı olduğu alan adının kamuya açık e-posta güvenlik
> yapılandırması üzerinden gerçekleştirilir.

Aynı metin ana sayfadaki e-posta panelinin altında tek satır özet olarak
(`--t-small`, `--ink-3`) bulunur ve PDF raporunun kapağında tekrarlanır.

---

## 5 · Bulgu açılımı — etkileşim kuralları

| Soru | Karar | Gerekçe |
|---|---|---|
| Aynı anda birden fazla açık olabilir mi? | **Evet** | Kullanıcı iki bulguyu karşılaştırabilmeli; otomatik kapanma kaydırma konumunu zıplatır |
| Biri açılınca diğeri kapanır mı? | Hayır | Yukarıdaki gerekçe |
| Animasyon | `grid-template-rows 0fr → 1fr`, `--t-slow`, `--ease`; içerik `opacity 0→1` `--t-base` gecikmeli | Yükseklik animasyonu için tek pürüzsüz teknik |
| Kaydırma konumu | Açılan öğenin **üst kenarı sabit kalır** | Kullanıcı tıkladığı satırı gözden kaybetmez |
| Açılan içerik ekrandan taşarsa | Sadece başlık görünür kalacak kadar yumuşak kaydırma | Uzun teknik detayda yön kaybı olmaz |
| Kapanma | Başlığa tekrar tıklama; başlık yapışkan değil | Basit ve öngörülebilir |
| Toplu kontrol | Boyut ekranında `Tümünü aç / kapat` | Tarama ve yazdırma için |
| URL | Açılınca `replaceState` ile `…/dmarc-zayif` yazılır | Link kopyalanabilir, ama geri tuşu bulguları tek tek kapatmaz |
| Klavye | Başlık `<button>`, `aria-expanded`, `aria-controls`; Enter/Space açar | Erişilebilirlik |
| Derin bağlantıyla gelindiğinde | İlgili bulgu açık gelir ve görünür alana kaydırılır (reduced-motion'da anında) | Paylaşılan link doğru yeri gösterir |

---

## 6 · Bileşen envanteri

Envanter kapalıdır. Her bileşenin durumları: `varsayılan · hover · odak ·
devre dışı · yükleniyor` (uygulanabilir olanlar).

| # | Bileşen | Notlar |
|---|---|---|
| 01 | Etiket + hairline (eyebrow) | Her ekranın açılışı |
| 02 | Sayfa başlığı bloğu | Etiket + display başlık + paragraf |
| 03 | Not gösterimi | Harf + `puan / 100`; harf rengi not tablosundan |
| 04 | Boyut kartı | Numara + ad + not + puan + açıklama + ok |
| 05 | Bulgu satırı (kapalı) | Şiddet ikonu + başlık + özet + hap + ok |
| 06 | Bulgu açılımı | Bölüm 4.4 sırası |
| 07 | Kontrol satırı | Boyut ekranındaki SPF/DMARC/… satırları |
| 08 | Durum satırı | "Ölçülemedi" / "Uygulanamaz" (bölüm 8) |
| 09 | Şiddet hapı | Yüksek / Orta / Düşük |
| 10 | Tint kutusu | Yeşil (olumlu) · Mavi (bilgi) · Pembe (puan kaybı) |
| 11 | Mono kod kutusu | Kopyala düğmesi sağ üstte |
| 12 | Numaralı adım listesi | "Nasıl düzeltilir" ve "Sonraki Adımlar" |
| 13 | Sağ kolon kartı | Başlık + içerik, hairline kenarlık |
| 14 | İstatistik döşemesi | İkon + etiket + değer |
| 15 | Aralık göstergesi | İki noktalı çizgi: ortalama (gri) ve sen (yeşil) |
| 16 | Histogram | Inline SVG |
| 17 | Donut | Inline SVG, ortada toplam |
| 18 | Delta çubuğu | Boyut bazında sektör farkı |
| 19 | Sıralama tablosu | Anonim satırlar + vurgulu kendi satırın |
| 20 | Sorgu paneli | Ana sayfa, iki varyant |
| 21 | Buton | Birincil (siyah dolgu) · İkincil (hairline) · Metin bağlantı (ok ile) |
| 22 | Terim ipucu | Noktalı alt çizgi + kısa tanım (bölüm 7) |
| 23 | Breadcrumb | Ana içeriğin üstünde |
| 24 | Çapa şeridi | Bulgu tam sayfasında, yapışkan |
| 25 | Boş/hata durumu bloğu | Ortalanmamış; sol hizalı, tek paragraf + eylem |
| 26 | Dağ illüstrasyonu | Yalnızca sol navigasyon altı ve ana sayfa sağ altı |

**Kart kuralı:** Kart yükseltilmiş nesne değil, birbirine ait veri kümesinin
sınırıdır. `--hairline` kenarlık, `--r-box` yarıçap, gölge yok, zemin farkı
yalnızca `--surface`. Ayrım için önce boşluk, sonra çizgi, en son kart denenir.

---

## 7 · Bilgi ve öğretim katmanı

Kullanıcı teknik bilgiye zorlanmaz ama isteyen üç kademe derine iner. Bu
katman ürünün yarısıdır; eksik bırakılmaz.

### Kademe 1 — Terim ipucu

Kısaltmalar ve teknik terimler (DMARC, SPF, DKIM, DNSSEC, HSTS, CAA…) metin
içinde noktalı alt çizgiyle işaretlenir. Üzerine gelince / odaklanınca /
dokununca **en fazla 160 karakterlik** bir tanım açılır, altında
`Rehberi aç →`. Modal değildir, sayfayı kilitlemez, klavyeyle erişilebilir.

### Kademe 2 — Bulgunun içindeki bölümler

"Bu ne anlama geliyor?", "Nasıl düzeltilir?", "Teknik Detay" — bunlar **o alan
adına özgüdür**, genel bilgi değildir. Kullanıcının kendi durumunu anlatır.

### Kademe 3 — Rehber sayfaları

Alan adından bağımsız, kalıcı eğitim içerikleri. Adres: `/tr/rehber/<slug>`.
Her bulgu en az bir rehbere bağlanır; bağlantılar tam sayfada sağ kolondaki
**"Daha Fazla Bilgi"** kartında, satır içi açılımda ise **"İlgili Kaynaklar"**
bölümünde toplanır.

**Açılış kararı:** Rehber aynı sekmede kendi sayfası olarak açılır (yeni sekme
değil, çekmece değil). Üstte `← analize dön` bulunur ve gelinen bulguya, açık
hâlde geri döner. Gerekçe: rehberler kalıcı, paylaşılabilir, aranabilir ve
yazdırılabilir olmalı; çekmece bunların hiçbirini vermez.

**İlk sürüm rehber listesi (A boyutu):**

`dmarc-nedir` · `dmarc-politikalari` (none / quarantine / reject farkı) ·
`dmarc-nasil-yapilandirilir` · `spf-nedir` · `spf-10-sorgu-siniri` ·
`dkim-nedir` · `dkim-seciciler` · `mx-kayitlari` · `dnssec-nedir` ·
`caa-nedir` · `mta-sts-ve-tls-rpt`

Sonraki sprintlerde B, C ve D boyutlarının rehberleri eklenir.

**Yan fayda:** Bu rehberler hem arama motorlarından organik ziyaretçi getirir
hem de tez metninin ekler bölümüne doğrudan girer.

---

## 8 · Durum makineleri

### 8.1 Analiz yaşam döngüsü

Sonuç kabuğu **hemen** render edilir; bekleme ekranı yoktur.

| Aşama | Görünen |
|---|---|
| `başladı` | Alan adı, tarih, kabuk yerinde. Genel not alanında ince nabız çizgisi. Dört boyut kartı `ölçülüyor…` etiketiyle. |
| `boyut tamamlandı` | O kartın notu belirir: `opacity 0→1` + `translateY(4px→0)`, `--t-base`. Sol navigasyondaki nabız noktası söner. |
| `bulgular geldi` | Öne Çıkan Bulgular listesine satır eklenir, aynı belirme hareketiyle. |
| `tümü tamamlandı` | Genel not belirir; puan 0'dan hedefe sayar (600ms, `--ease`; reduced-motion'da anında). |
| `kısmen başarısız` | Karne normal görünür; etkilenen boyutun notu yanında `kısmi ölçüm` işareti. |
| `tamamen başarısız` | Karne yerine tek bir açıklama bloğu + `Yeniden dene` + destek bağlantısı. |

Sayfa bu sırada yenilenirse aynı tarama kaydına döner; tarama baştan başlamaz.

### 8.2 Kontrol durumları — dört durum, dört dil, dört puan davranışı

| Durum | Anlamı | Puan | Görsel |
|---|---|---|---|
| **Uygun** | Kontrol edildi, doğru yapılandırılmış | Artırır | Yeşil onay, sade satır |
| **Yapılandırılmamış** | Kontrol edildi, kayıt yok veya zayıf | **Düşürür** | Şiddet ikonu + hap, açılabilir bulgu |
| **Ölçülemedi** | Teknik engel: zaman aşımı, sunucu hatası, bot koruması | **Düşürmez — paydadan çıkar** | Kesikli kenarlıklı nötr satır, nötr ikon, `yeniden dene` |
| **Uygulanamaz** | Bu alan adı için anlamsız (MX yoksa MTA-STS değerlendirilmez) | Girmez | `--ink-4` soluk satır, ikonsuz, tek cümle gerekçe |

**Değişmez kural:** "Ölçülemedi" asla "yapılandırılmamış" gibi gösterilmez ve
asla puanı düşürmez. Aksi hâlde güvenlik katmanı olan siteler haksız yere
cezalandırılır — bu hem ürün hatası hem tezde ölçüm geçerliliği sorunudur.
(`docs/PLAN.md` K-06'nın arayüzdeki karşılığı.)

Bir boyutta ölçülemeyen kontrol varsa: boyut notunun yanında `kısmi ölçüm`
işareti; PDF ve paylaşım çıktısında açık uyarı satırı.

### 8.3 Hata ve boş durumlar

| Durum | Davranış |
|---|---|
| Geçersiz alan adı biçimi | Input altında satır içi hata, sayfa değişmez, odak inputta kalır |
| Geçersiz e-posta biçimi | Aynı |
| Alan adı bulunamadı (NXDOMAIN) | Sonuç ekranına gidilir, "Bu alan adı bulunamadı" bloğu; **tarama kaydı yine oluşturulur** (tez verisi için) |
| Alan adı var, hiçbir kontrol yapılamadı | Açıklama bloğu + olası sebepler + `Yeniden dene` |
| Sektör verisi yok | Bölüm 4.5'teki "Türkiye geneli" modu |
| Bulgu yok (her şey uygun) | Öne Çıkan Bulgular yerine yeşil tint kutusu: bu alan adında öne çıkan bir sorun bulunamadı + hangi kontrollerin yapıldığı |

Boş durumlar ortalanmaz, illüstrasyon kullanmaz, espri yapmaz. Sol hizalı tek
paragraf + tek eylem.

---

## 9 · URL haritası ve geçmiş

```
/tr/                                        ana sayfa
/tr/analiz/<tarama_id>                      genel bakış (donmuş sonuç)
/tr/analiz/<tarama_id>/eposta               boyut
/tr/analiz/<tarama_id>/aktarim
/tr/analiz/<tarama_id>/gizlilik
/tr/analiz/<tarama_id>/teknoloji
/tr/analiz/<tarama_id>/sektor               sektör karşılaştırması
/tr/analiz/<tarama_id>/eposta/dmarc-zayif   bulgu (çapa + tam sayfa)
/tr/alan/example.com                        en son taramaya yönlendirir
/tr/rehber/<slug>                           rehber sayfası
/tr/metodoloji · /tr/hakkinda · /tr/acik-veri
/en/…                                       birebir aynı yapı
```

**Kurallar**

- Sayfa yenilenince sonuç korunur; yeniden tarama yapılmaz (kötüye kullanım
  koruması olarak da işe yarar).
- Satır içi açılım URL'yi `replaceState` ile günceller; geçmişe kayıt eklemez.
- Paylaş düğmesi **tarama kaydı adresini** kopyalar (donmuş sonuç). Gerekçe:
  "şu tarihte şu sonucu aldım" iddiası sonradan değişmemeli.
- Dil değiştirme aynı sayfada kalır, yalnızca önek değişir; kaydırma konumu ve
  açık bulgular korunur.
- Geri tuşu: bir üst ekrana çıkar, bulguları tek tek kapatmaz.

---

## 10 · PDF ve paylaşım

**PDF.** Aynı HTML'in yazdırma stilinden sunucuda üretilir; ayrı bir tasarım
yoktur. İçerik: kapak (alan adı, tarih, genel not, kapsam notu) → özet →
dört boyut → **tüm bulgular açık hâlde, teknik detay dâhil** → ölçüm yöntemi
notu → varsa kısmi ölçüm uyarısı. Her sayfanın altında tarama adresi ve tarih.

Yazdırma stilinde: sidebar ve sağ kolon gizlenir, akordiyonlar açılır, bağlantılar
yanlarında adresleriyle yazılır, renkler korunur.

**Paylaşım.** Tek eylem: adresi kopyala + kısa onay. İlk kullanımda tek satır
uyarı: paylaşılan sayfa herkese açıktır. Görsel/kart üretimi P2'dir.

---

## 11 · Erişilebilirlik

- Metin kontrastı en az 4.5:1; büyük başlık ve not harflerinde en az 3:1.
  `--ink-3` yalnızca 13px üstü ve ikincil bilgide kullanılır.
- **Renk tek başına anlam taşımaz.** Her not ve şiddet, renkle birlikte harf,
  ikon veya metin etiketi taşır.
- Tüm etkileşimli öğeler klavyeyle erişilebilir; odak halkası görünür
  (`2px solid --good`, `offset 2px`).
- Akordiyon: `<button aria-expanded aria-controls>`; içerik `role="region"` ve
  `aria-labelledby`.
- Grafikler: `<title>` + `<desc>` içerir, altında metin özeti bulunur
  (*"Sektör ortalaması 68, sizin puanınız 87; en yoğun aralık 61-80."*).
- Dil değiştirici `<html lang>` değerini değiştirir.
- `prefers-reduced-motion` tam desteklenir.

---

## 12 · İçerik ve dil kuralları

- **Bulgu başlığı insan dilidir**, kısaltmayla başlamaz.
  ✓ "DMARC politikası yeterince koruyucu değil" ✗ "DMARC p=none"
- İkinci cümle teknik gerçeği verir: "DMARC kaydınız mevcut ancak p=none olarak
  yapılandırılmış."
- **Suçlayıcı dil yok.** "Yapılandırmamışsınız" değil, "yapılandırılmamış".
- **Korku dili yok.** "Saldırıya açıksınız", "tehlikedesiniz" yasak. Yerine somut
  sonuç: "adınıza sahte e-posta gönderilebilir".
- Kısaltmalar ilk geçtiğinde açılır ve terim ipucu taşır.
- Sayılar ve puanlar `font-variant-numeric: tabular-nums`.
- Tarihler uzun biçim: "12 Eylül 2026".
- Arayüzde sabit metin yoktur; her dize çeviri anahtarıyla gelir. Türkçe ve
  İngilizce dosyalar aynı anahtar kümesine sahiptir; eksik anahtar derlemede
  hata verir.

---

## 13 · Asla yapma

- Gölge, gradyan, cam efekti, neon, parlama
- Kalkan / kilit / kapüşonlu adam ikonografisi, matrix yeşili, terminal estetiği
- Emoji (arayüzde ve içerikte)
- Her bloğu karta çevirmek
- Renkli zeminli büyük uyarı bantları
- Tam ekran spinner ile bekletmek
- Düşük notu kırmızıya boğmak; F bile sakin gösterilir
- Anlam tablosu dışında renk kullanmak
- Yeni sidebar, yeni navigasyon, yeni kart sistemi icat etmek
- Koyu tema
- Sayfa geçişi animasyonu
- Sektör tablosunda başka kurumları adıyla göstermek
- "Ölçülemedi" durumunu eksiklik gibi göstermek

---

## 14 · Uygulama notları

- **Sunucu tarafı render** (Jinja şablonları) + küçük vanilla JS. SPA yok,
  ön yüz çatısı yok, derleme adımı yok.
- JavaScript yalnızca dört şey için: akordiyon, kopyala, terim ipucu, ilerleyen
  tarama güncellemesi. Sonuncusu için HTMX veya sade `fetch` yeterlidir.
- **Grafikler sunucuda üretilen inline SVG'dir.** Grafik kütüphanesi yüklenmez:
  küçük kalır, tema tokenlarını kullanır, yazdırmada ve PDF'te bozulmaz.
- `web/static/tokens.css` tek görsel kaynaktır; başka yerde ham değer bulunursa
  hata sayılır.
- **Canlı bileşen kataloğu:** `/tr/stil` adresinde her bileşen her durumuyla
  render edilir. Yeni bir bileşen önce burada doğrulanır. Bu sayfa üretimde de
  açık kalır; tez ekine ekran görüntüsü buradan alınır.
- İkonlar: ince çizgili, 1.5px, tek renkli, kütüphane yerine proje içi SVG seti.
  İkon yalnızca anlam taşıdığı yerde kullanılır, dekorasyon olarak kullanılmaz.
