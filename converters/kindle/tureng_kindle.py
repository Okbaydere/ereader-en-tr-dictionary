#!/usr/bin/env python3
"""db.json -> Kindle sozluk kaynagi (.opf + .xhtml parcalari).

ONEMLI: Bu script sadece kindlegen'in derleyecegi KAYNAK dosyalari uretir,
dogrudan .mobi UretMEZ. Amazon kindlegen'i artik ayri dagitmiyor; Kindle
Previewer 3'un icine gomulu geliyor (Amazon'un sitesinden ucretsiz indirilir).

Derleme (bu script'in ciktisini urettikten sonra, kendi bilgisayaninda):
  macOS : "/Applications/Kindle Previewer 3.app/Contents/lib/fc/bin/kindlegen" dictionary.opf
  Windows: "C:\\Program Files (x86)\\Amazon\\Kindle Previewer 3\\lib\\fc\\bin\\kindlegen.exe" dictionary.opf
(Tam yol Previewer surumune gore degisebilir; klasoru gezip kindlegen'i bul.)

Kullanim: python3 tureng_kindle.py [db.json] [cikti_klasoru] [--chunk N]
Referans: Amazon "Building a Kindle Dictionary" rehberi, idx:entry/idx:orth/idx:infl etiketleri.
"""
import html
import json
import os
import sys
import zipfile
from xml.dom import minidom

NOISE_CATS = {'yaygın kullanım', 'genel', ''}
DEFAULT_CHUNK = 20000


def build_defs(entries: list) -> str:
    seen, cats_seen, ps = set(), set(), []
    for e in entries:
        tr = (e.get('tr') or '').strip()
        if not tr:
            continue
        pos = (e.get('pos_en') or e.get('pos') or '').strip()
        cat = (e.get('category') or '').strip()
        key = (pos, cat.lower(), tr.lower())
        if key in seen:
            continue
        seen.add(key)
        parts = []
        if pos:
            parts.append(f'<i>{html.escape(pos)}</i>')
        if cat and cat.lower() not in NOISE_CATS and cat.lower() not in cats_seen:
            cats_seen.add(cat.lower())
            parts.append(f'[{html.escape(cat)}]')
        parts.append(f'<b>{html.escape(tr)}</b>')
        ex_en = (e.get('example_en') or '').strip()
        ex_tr = (e.get('example_tr') or '').strip()
        if ex_en:
            parts.append(f'<br/>&#8220;{html.escape(ex_en)}&#8221;')
            if ex_tr:
                parts.append(f'<br/>&#8594; {html.escape(ex_tr)}')
        ps.append('<p>' + ' '.join(parts) + '</p>')
    return ''.join(ps)


def entry_xhtml(idx: int, word: str, defs: str, variants: set) -> str:
    infl = ''
    if variants:
        iforms = ''.join(f'<idx:iform value="{html.escape(v)}"/>' for v in sorted(variants))
        infl = f'<idx:infl>{iforms}</idx:infl>'
    return (
        f'<idx:entry name="default" scriptable="yes" spell="yes">'
        f'<idx:short><a id="w{idx}"></a>'
        f'<idx:orth value="{html.escape(word)}"><b>{html.escape(word)}</b>{infl}</idx:orth>'
        f'{defs}'
        f'</idx:short></idx:entry><hr/>'
    )


def write_content_file(path: str, entries_xhtml: list, title: str):
    body = ''.join(entries_xhtml)
    doc = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns:math="http://exslt.org/math" xmlns:svg="http://www.w3.org/2000/svg" '
        'xmlns:tl="https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf" '
        'xmlns:saxon="http://saxon.sf.net/" xmlns:xs="http://www.w3.org/2001/XMLSchema" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:cx="https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf" '
        'xmlns:idx="https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf" '
        'xmlns:mbp="https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf" '
        'xmlns:mbname="https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf" '
        'xmlns:xlink="http://www.w3.org/1999/xlink">\n'
        f'<head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"/><title>{html.escape(title)}</title></head>\n'
        f'<body><mbp:frameset>{body}</mbp:frameset></body></html>'
    )
    with open(path, 'w', encoding='utf-8') as f:
        f.write(doc)


def write_opf(path: str, content_files: list, book_title: str):
    manifest = ''.join(
        f'<item id="content{i}" href="{fn}" media-type="application/xhtml+xml"/>\n'
        for i, fn in enumerate(content_files)
    )
    spine = ''.join(f'<itemref idref="content{i}"/>\n' for i in range(len(content_files)))
    opf = f'''<?xml version="1.0" encoding="utf-8"?>
<package unique-identifier="uid" xmlns:idx="https://kindlegen.s3.amazonaws.com/AmazonKindlePublishingGuidelines.pdf">
<metadata>
<dc-metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:oebpackage="http://openebook.org/namespaces/oeb-package/1.0/">
<dc:Title>{html.escape(book_title)}</dc:Title>
<dc:Language>tr</dc:Language>
<dc:Identifier id="uid">tureng-en-tr-dict</dc:Identifier>
</dc-metadata>
<x-metadata>
<DictionaryInLanguage>en</DictionaryInLanguage>
<DictionaryOutLanguage>tr</DictionaryOutLanguage>
<DefaultLookupIndex>default</DefaultLookupIndex>
</x-metadata>
</metadata>
<manifest>
{manifest}</manifest>
<spine>
{spine}</spine>
<guide></guide>
</package>
'''
    with open(path, 'w', encoding='utf-8') as f:
        f.write(opf)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    chunk = DEFAULT_CHUNK
    if '--chunk' in sys.argv:
        chunk = int(sys.argv[sys.argv.index('--chunk') + 1])
    db_path = args[0] if args else 'db.json'
    out_dir = args[1] if len(args) > 1 else 'kindle-en-tr-src'

    # koreader converter'daki variants_of ile ayni mantik (lemminflect)
    from lemminflect import getInflection
    POS_TAGS = {'noun': ['NNS'], 'verb': ['VBD', 'VBG', 'VBZ', 'VBN'],
                'adjective': ['JJR', 'JJS'], 'adverb': ['RBR', 'RBS']}
    FALLBACK = ['NNS', 'VBD', 'VBG', 'VBZ', 'VBN']

    def variants_of(w, poss):
        tags = set()
        for p in poss or ():
            tags.update(POS_TAGS.get(p, []))
        if not tags:
            tags = set(FALLBACK)
        vs = set()
        for t in tags:
            try:
                vs.update(getInflection(w, tag=t, inflect_oov=True))
            except Exception:
                pass
        return {v.lower() for v in vs if v and v.lower() != w and len(v) > 1}

    db = json.load(open(db_path, encoding='utf-8'))
    os.makedirs(out_dir, exist_ok=True)

    words_sorted = sorted(w.strip().lower() for w in db if w.strip() and db[w])
    words_sorted = sorted(set(words_sorted))

    content_files = []
    buf = []
    file_idx = 0
    for i, w in enumerate(words_sorted):
        entries = db[w] if w in db else db.get(w.capitalize(), [])
        if not entries:
            continue
        defs = build_defs(entries)
        if not defs:
            continue
        poss = {e.get('pos_en') for e in entries if e.get('pos_en')}
        variants = variants_of(w, poss)
        buf.append(entry_xhtml(i, w, defs, variants))
        if len(buf) >= chunk:
            fn = f'content{file_idx}.html'
            write_content_file(os.path.join(out_dir, fn), buf, f'Tureng EN-TR {file_idx}')
            content_files.append(fn)
            buf = []
            file_idx += 1
    if buf:
        fn = f'content{file_idx}.html'
        write_content_file(os.path.join(out_dir, fn), buf, f'Tureng EN-TR {file_idx}')
        content_files.append(fn)

    write_opf(os.path.join(out_dir, 'dictionary.opf'), content_files, 'Tureng İngilizce-Türkçe Sözlük')

    # temel iyi-bicimlilik kontrolu (kindlegen'in kendisini calistirmadan
    # yapabilecegimiz en fazla kontrol bu)
    ok = True
    for fn in content_files:
        try:
            minidom.parse(os.path.join(out_dir, fn))
        except Exception as e:
            ok = False
            print(f'[!] {fn} XML olarak parse edilemedi: {e}')

    zip_path = f'{out_dir}.zip'
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for fn in os.listdir(out_dir):
            z.write(os.path.join(out_dir, fn), arcname=f'{out_dir}/{fn}')

    print(f'[✓] {zip_path}: {len(content_files)} icerik dosyasi, XML iyi-bicimlilik: '
          f'{"OK" if ok else "HATALI (yukarida detay var)"}')
    print('    Derlemek icin: kindlegen dictionary.opf  (Kindle Previewer 3 icinde gelir)')


if __name__ == '__main__':
    main()
