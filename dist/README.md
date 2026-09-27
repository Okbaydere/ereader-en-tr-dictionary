Hazir, kurula hazir sozluk paketleri. Cihazina gore birini sec:

- **Kobo** -> `dicthtml-en-tr.zip`
  `.kobo/dict/` altina kopyala, cihazi yeniden baslat.
  (Test icin: `dicthtml-fr.zip` adiyla koyarsan sadece Fransizca-dilli
  kitaplarda devreye girer, yerlesik sozluge dokunmaz.)

- **KOReader** -> `stardict-en-tr.zip`
  Icindeki `stardict-en-tr/` klasorunu (butun halinde)
  `koreader/data/dict/` altina kopyala, KOReader'i yeniden baslat.

- **Kindle** -> `dictionary.mobi`
  USB ile baglayip `documents/dictionaries/` altina kopyala; Kindle'da
  Ayarlar -> Dil ve Klavyeler -> Sozlukler'den "Tureng Ingilizce-Turkce"
  sozlugunu sec.

Paketler `converters/` altindaki scriptlerle `data/db.json`'dan uretilir;
kaynak kod ve yeniden uretim akisi icin ana README'ye bakin.
