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
dist/          -> kuruma hazir, bitmis sozluk paketleri (dicthtml-en-tr.zip vb.)
```

Ileride `converters/koreader/` ve `converters/kindle/` eklenecek; ayni
`data/db.json` farkli cikti formatlarina cevrilebilecek.

## Veri

`data/db.json` (246.479 baslik, ~98 MB) ve `data/words.json` boyutlari
yuzunden repoda tutulmuyor; **[Releases](https://github.com/Okbaydere/ereader-en-tr-dictionary/releases)**
sayfasindan indirip `data/` altina koyun. Kendi verinizi uretmek isterseniz
asagidaki akis sifirdan da calisir (bos `data/` ile baslayip bir kelime
listesi ile besleyerek).

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

## Kurulum

```fish
python3 -m venv .venv
source .venv/bin/activate.fish
pip install -r requirements.txt
```

## Kullanim

Script'ler veriyi repo yerlesiminde otomatik olarak `data/` altinda bulur
yazar (o klasor yoksa calisma dizinini kullanir):

```fish
cd scraper
python3 tureng_dictionary_scraper.py     # ilk toplama turu (data/ altina yazar)
python3 tureng_phase2.py --dry 200       # kesif turu icin tahmini kazanc
python3 tureng_phase2.py                 # words.json'a yeni basliklari ekle
python3 tureng_dictionary_scraper.py     # yeni basliklari da cek

cd ../converters/kobo
python3 tureng_kobo.py ../../dist/dicthtml-en-tr.zip
```

Uretilen `dicthtml-en-tr.zip` dosyasini Kobo'ya `.kobo/dict/` altina atmak
yeterli. Cikti adini vermezsen `dicthtml-en.zip` uzere calisma dizinine yazilir.

## Icerik

- **246.479** Ingilizce baslik (headword), **715.278** anlam (sense) --
  kelime basina ortalama **2,9 anlam**.
- Bunlardan **227.564** tanesi bagimsiz kok kelime; kalan **18.915** tanesi
  baska bir basligin cekimli hali olarak da (lemminflect eslestirmesiyle)
  ayni girise yonlendirilir (`ran` -> `run` gibi).
- Kelime turu dagilimi: %58 isim, %27 sifat, %8 fiil, %4 zarf, kalani
  unlem/zamir/baglac ve turu isaretsiz girisler.
- Anlamlarin **~%10'unda** (70.813) Tureng'in kendi orneginden gelen
  Ingilizce-Turkce ornek cumle cifti var.
- Her kelime icin en fazla 7 anlam tutuluyor (Tureng'in kategori sirasina
  gore secilerek); ornekli anlamlar oncelikli, kalan slotlar orneksiz
  anlamlarla dolduruluyor.

## Notlar

- Sozluk verisi (`data/`) ve bitmis paketler (`dist/`) Tureng.com'dan
  derlenmistir; kisisel/egitim amacli kullanim icin paylasilmaktadir.


## Lisans

Kod MIT lisanslidir -- bkz. [LICENSE](LICENSE). `data/` ve `dist/` icindeki
sozluk verisi bu lisansin kapsaminda degildir.
