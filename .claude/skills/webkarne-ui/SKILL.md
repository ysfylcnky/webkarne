---
name: webkarne-ui
description: WebKarne arayüz kuralları. Şablon, CSS, bileşen, ikon, grafik veya kullanıcıya görünen metin yazarken ya da değiştirirken kullan. Tasarım sistemini, token zorunluluğunu ve yasak listesini taşır.
---

# WebKarne arayüz kuralları

Bu skill, WebKarne'nin görsel dilini korumak için var. Arayüzle ilgili tek bir
satır bile yazmadan önce bu kurallar geçerlidir.

**Tam spesifikasyon: `docs/DESIGN-SYSTEM.md`.** Bu dosya onun yerine geçmez,
en sık ihlal edilen kuralların hatırlatıcısıdır. Yeni bir ekran, bileşen veya
davranış yazacaksan önce spesifikasyonun ilgili bölümünü oku.

---

## Değişmez üç kural

**1 · Token dışında değer yok.**
Renk, boşluk, yazı boyutu, satır yüksekliği, harf aralığı, yarıçap, süre,
easing — hepsi `web/static/tokens.css` içindeki değişkenlerden gelir. Şablonda
veya bileşen CSS'inde ham `#hex`, `px`, `ms` değeri görürsen bu bir hatadır.
Eksik bir değer varsa önce token olarak tanımla ve `docs/DESIGN-SYSTEM.md`'ye
işle; asla satır içine yazma.

**2 · Yeni bileşen icat etme.**
Bileşen envanteri `docs/DESIGN-SYSTEM.md § 6`'da kapalıdır. İhtiyaç mevcut
bileşenlerle karşılanamıyorsa kod yazmadan önce gerekçeni söyle ve onay bekle.

**3 · Yeni görsel dil önerme.**
Editorial / dijital rapor estetiği sabittir. Yeni bir sidebar, yeni bir kart
sistemi, yeni bir navigasyon kalıbı veya farklı bir stil önermeden önce mevcut
tasarımın neden yetersiz kaldığını açıkça gerekçelendir.

---

## Görsel dilin özeti

- Kırık beyaz zemin, koyu gri-siyah metin, hairline ayraçlar.
- **Renk yalnızca anlam taşır**: not (A yeşil, B mavi, C amber, D-F kırmızı),
  şiddet, delta, durum. Dekorasyon için renk yok, ayrı bir marka aksanı yok.
- Tipografi taşır: display serif başlıklar, nötr sans gövde, mono veri.
- Ayrım için sırayla: önce **boşluk**, sonra **çizgi**, en son **kart**.
- Kart yükseltilmiş nesne değil, veri kümesinin sınırıdır: hairline kenarlık,
  3px yarıçap, gölge yok.
- Her ekran aynı ritimle başlar: etiket + hairline → dev serif başlık → paragraf.

---

## Hareket

- Yalnızca `opacity` ve `transform` animasyonlanır.
- Yükseklik animasyonu `grid-template-rows: 0fr → 1fr` tekniğiyle yapılır.
- Süreler: hover `--t-fast`, beliren içerik `--t-base`, akordiyon `--t-slow`.
- Sayfa geçişi animasyonu yoktur.
- `prefers-reduced-motion` altında süreler düşer **ve** transform'lar kalkar.
- Bir hareket dikkat çekiyorsa yanlıştır.

---

## Dil ve metin

- Bulgu başlığı insan dilidir, kısaltmayla başlamaz.
  ✓ "DMARC politikası yeterince koruyucu değil"  ✗ "DMARC p=none"
- Suçlayıcı dil yok: "yapılandırmamışsınız" değil, "yapılandırılmamış".
- Korku dili yok: "saldırıya açıksınız", "tehlikedesiniz" yasak. Yerine somut
  sonuç: "adınıza sahte e-posta gönderilebilir".
- Kısaltmalar ilk geçtiğinde açılır ve terim ipucu taşır.
- **Arayüzde sabit metin yoktur.** Her dize çeviri anahtarından gelir; `tr` ve
  `en` dosyaları aynı anahtar kümesine sahiptir.

---

## Ölçüm durumlarının gösterimi

Bu, ürünün doğruluk iddiasının arayüzdeki karşılığıdır. Dört durum asla
birbirine karışmaz:

| Durum | Puan | Görünüm |
|---|---|---|
| Uygun | artırır | yeşil onay, sade satır |
| Yapılandırılmamış | **düşürür** | şiddet ikonu + hap, açılabilir bulgu |
| Ölçülemedi | **düşürmez, paydadan çıkar** | kesikli kenarlık, nötr ikon, "yeniden dene" |
| Uygulanamaz | girmez | soluk gri, ikonsuz, tek cümle gerekçe |

**"Ölçülemedi" asla "yapılandırılmamış" gibi gösterilmez ve asla puanı
düşürmez.** Aksi hâlde bot koruması olan siteler haksız yere cezalandırılır.

---

## Asla yapma

- Gölge, gradyan, cam efekti, neon, parlama
- Kalkan / kilit / kapüşonlu adam ikonografisi, matrix yeşili, terminal estetiği
- Emoji (arayüzde ve içerikte)
- Her bloğu karta çevirmek
- Renkli zeminli büyük uyarı bantları
- Tam ekran spinner ile bekletmek
- Düşük notu kırmızıya boğmak — F bile sakin gösterilir
- Anlam tablosu dışında renk kullanmak
- Koyu tema
- Sektör tablosunda diğer kurumları adıyla göstermek
- Grafik kütüphanesi yüklemek (grafikler sunucuda üretilen inline SVG'dir)
- Ön yüz çatısı veya derleme adımı eklemek

---

## Bitirmeden önce kontrol et

- [ ] Dosyada hiç ham renk, boşluk, boyut veya süre değeri kalmadı
- [ ] Kullanıcıya görünen her metin çeviri anahtarından geliyor, `tr` ve `en`
      karşılıkları yazıldı
- [ ] Türkçe karakterler (ğ ş ı İ ç ö ü) gerçek yazı tipinde doğru görünüyor
- [ ] Renk tek başına anlam taşımıyor; her renk yanında harf, ikon veya etiket var
- [ ] Etkileşimli her öğe klavyeyle erişilebilir, odak halkası görünür
- [ ] Akordiyon `aria-expanded` ve `aria-controls` taşıyor
- [ ] `prefers-reduced-motion` altında sayfa doğru davranıyor
- [ ] Grafiğin `<title>`/`<desc>`'i ve altında metin özeti var
- [ ] Yeni bir bileşen eklendiyse `/tr/stil` kataloğuna da eklendi
- [ ] Yazdırma görünümü bozulmadı (sidebar gizli, akordiyonlar açık)
