# ereader-en-tr-dictionary

E-okurlar (Kobo, ileride KOReader ve Kindle) icin, Tureng.com verisinden
derlenen acik kaynakli Ingilizce-Turkce sozluk. Cihazlarin fabrika cikisi
gelen en-tr sozlukleri zayif/eksik oldugu icin hazirlandi.

Hazir sozluk paketini indirip kurmak icin `dist/` klasorune bakman yeterli --
kod ve scriptlerle ugrasmana gerek yok. Kendi veri setinden farkli bir cift
(orn. baska bir dil) uretmek istersen asagidaki akis isine yarar.

## Klasor yapisi

```
data/          -> ham sozluk verisi (db.json, words.json) -- scraper burayi besler
scraper/       -> Tureng.com'u tarayip data/ altina yazan scriptler
converters/
  kobo/        -> data/ icindeki db.json'i Kobo sozluk paketine cevirir
  koreader/    -> ayni db.json'i StarDict paketine cevirir (KOReader native destekler)
  kindle/      -> ayni db.json'dan Kindle icin .opf+.xhtml KAYNAGI uretir (derleme icin kindlegen gerekir, bkz. asagi)
dist/          -> kuruma hazir, bitmis sozluk paketleri
```

## Akis

1. **`scraper/tureng_dictionary_scraper.py`** — `data/words.json` icindeki
   Ingilizce kelime listesini Tureng'in TR->EN tablolarindan tarar, her
   kelime icin anlamlari (kategori, tur, ornek cumle) `data/db.json`'a yazar.
   Asenkron (`curl_cffi` + `lxml`), otomatik hiz ayarli (AIMD concurrency),
   journal + snapshot ile kesintiye dayanikli.
2. **`scraper/tureng_phase2.py`** — Tek yonlu tarama, listede olmayan
   basliklari asla bulamaz. Bu script `data/db.json`'daki Turkce anlamlardan
   tohum kelimeler cikarip Tureng'in TR->EN yonunu tarayarak `words.json`'da
   eksik olan Ingilizce basliklari kesfeder. `--dry N` ile once tahmini
   kazanc olculebilir.
3. **`converters/kobo/tureng_kobo.py`** — `data/db.json`'i Kobo'nun native
   sozluk formatina (`dicthtml-*.zip`, gzip'li HTML parcalari + marisa-trie
   indeks) cevirir. `lemminflect` ile cekimli formlari (`ran` -> `run`)
   uretip ayni girise yonlendirir.
4. **`converters/koreader/tureng_stardict.py`** — `data/db.json`'i
   **StarDict** formatina cevirir (`.ifo`/`.idx`/`.dict`/`.syn`, zip'lenmis).
   KOReader bu formati kendi ici destekler, harici bir arac gerekmez.
   Cikti klasoru `koreader/data/dict/` altina kopyalanir. Cekimli formlar
   `.syn` dosyasi uzerinden ana kelimeye yonlendirilir.
5. **`converters/kindle/tureng_kindle.py`** — `data/db.json`'dan Kindle
   sozluk formati icin **kaynak** dosyalari (`.opf` + parcali `.xhtml`,
   `idx:entry`/`idx:orth`/`idx:infl` etiketleriyle) uretir. Bu script
   `.mobi` UretMEZ — son adim olarak `kindlegen dictionary.opf` ile
   derlenmesi gerekir. Amazon kindlegen'i ayri dagitmiyor; **Kindle
   Previewer 3**'un icine gomulu geliyor (Amazon'un sitesinden ucretsiz
   indirilir, kurulum klasorunde `.../lib/fc/bin/kindlegen` yolunda durur).

Ileride farkli cikti formatlari eklenebilir; ayni `data/db.json` her formatin
kaynagi olarak kullanilir.

## Hazir paketler ve kurulum

Kodla ugrasmak istemeyenler icin `dist/` altinda (ve
[Releases](https://github.com/Okbaydere/ereader-en-tr-dictionary/releases)
sayfasinda) kurula hazir paketler var. Cihazina gore:

| Cihaz | Paket | Nereye atilir |
|---|---|---|
| **Kobo** | `dicthtml-en-tr.zip` | USB ile bagla -> `.kobo/dict/` -> cihazi yeniden baslat |
| **KOReader** | `stardict-en-tr.zip` | icindeki `stardict-en-tr/` klasorunu `koreader/data/dict/` altina kopyala |
| **Kindle** | `dictionary.mobi` | USB ile bagla -> `documents/dictionaries/` -> Ayarlar'dan sozluk olarak sec |

Not: Kobo'da yerlesik Ingilizce sozlugu korumak istersen, zip'i
`dicthtml-fr.zip` adiyla koy (sadece Fransizca-dilli kitaplarda devreye girer).

## Veri

`data/db.json` (246.479 baslik, ~98 MB) ve `data/words.json` boyutlari
yuzunden repoda tutulmuyor; **[Releases](https://github.com/Okbaydere/ereader-en-tr-dictionary/releases)**
sayfasindan indirip `data/` altina koyun. Kendi verinizi uretmek isterseniz
asagidaki akis sifirdan da calisir (bos `data/` ile baslayip bir kelime
listesi ile besleyerek).

## Kurulum

```fish
python3 -m venv .venv
source .venv/bin/activate.fish
pip install -r requirements.txt
```

## Kullanim

```fish
cd scraper
python3 tureng_dictionary_scraper.py     # ilk toplama turu (data/ altina yazar)
python3 tureng_phase2.py --dry 200       # kesif turu icin tahmini kazanc
python3 tureng_phase2.py                 # words.json'a yeni basliklari ekle
python3 tureng_dictionary_scraper.py     # yeni basliklari da cek

cd ../converters/kobo
python3 tureng_kobo.py ../../data/db.json dicthtml-en-tr.zip

cd ../koreader
python3 tureng_stardict.py ../../data/db.json stardict-en-tr

cd ../kindle
python3 tureng_kindle.py ../../data/db.json kindle-en-tr-src
```

- **Kobo**: uretilen `dicthtml-en-tr.zip` dosyasini `.kobo/dict/` altina atmak yeterli.
- **KOReader**: `stardict-en-tr.zip` icindeki `stardict-en-tr/` klasorunu
  `koreader/data/dict/` altina kopyala.
- **Kindle**: `kindle-en-tr-src/` icindeki `dictionary.opf`'i kindlegen ile
  derle, ciktiyi Kindle'a `documents/dictionaries/` altina at.

## Icerik

- **246.479** Ingilizce baslik (headword), **715.278** anlam (sense) --
  kelime basina ortalama **2,9 anlam**.
- Bunlardan **227.564** tanesi bagimsiz kok kelime; kalan **18.915** tanesi
  baska bir basligin cekimli hali olarak da (lemminflect eslestirmesiyle)
  ayni girise yonlendirilir (`ran` -> `run` gibi).
- Kelime turu dagilimi: %58 isim, %27 sifat, %8 fiil, %4 zarf, kalani
  unlem/zamir/baglac ve turu isaretsiz girisler.
- Anlamlarin **~%10'unda** (70.813) Tureng'in kendi orneginden gelen
  Ingilizce-Turkce ornek cumle cifti var. (Tatoeba/TED2020 ile
  zenginlestirilmis, ornek cumlesi cok daha yuksek oranli ikinci bir surum
  de hazirladim -- bkz. Notlar.)
- Her kelime icin en fazla 7 anlam tutuluyor (Tureng'in kategori sirasina
  gore secilerek); ornekli anlamlar oncelikli, kalan slotlar orneksiz
  anlamlarla dolduruluyor.

## Notlar

- Sozluk verisi (`data/`) ve bitmis paketler (`dist/`) Tureng.com'dan
  derlenmistir; kisisel/egitim amacli kullanim icin paylasilmaktadir.
- Ornek cumle zenginlestirme (Tatoeba/TED2020 birlestirme, POS bazli
  eslestirme) ayri bir asama olup bu repoya henuz eklenmedi.
- Kindle kaynagi (`converters/kindle/`) sadece XML iyi-bicimlilik acisindan
  test edildi; kindlegen'in kendisiyle derlenip Kindle'da calisip
  calismadigi henuz dogrulanmadi. Derleme sirasinda hata alirsan
  (ozellikle cok sayida cekim/inflection ile ilgili limitler bilinen bir
  sorun) issue acabilirsin.

## Lisans

Kod MIT lisanslidir -- bkz. [LICENSE](LICENSE). `data/` ve `dist/` icindeki
sozluk verisi bu lisansin kapsaminda degildir.
