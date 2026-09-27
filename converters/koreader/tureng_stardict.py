#!/usr/bin/env python3
"""db.json -> StarDict paketi (KOReader icin).

KOReader sozluk aramasi StarDict formatini native destekler; harici bir
donusturucu (kindlegen vb.) gerektirmez. Uretilen klasoru
koreader/data/dict/ altina kopyalamak yeterli.

Kullanim: python3 tureng_stardict.py [db.json] [cikti_adi]
Gereksinim: pip install lemminflect
Format referansi: https://raw.githubusercontent.com/huzheng001/stardict-3/master/dict/doc/StarDictFileFormat
"""
import html
import json
import os
import shutil
import struct
import subprocess
import sys
import zipfile
from datetime import date

from lemminflect import getInflection

NOISE_CATS = {'yaygın kullanım', 'genel', ''}

POS_TAGS = {
    'noun': ['NNS'],
    'verb': ['VBD', 'VBG', 'VBZ', 'VBN'],
    'adjective': ['JJR', 'JJS'],
    'adverb': ['RBR', 'RBS'],
}
FALLBACK_TAGS = ['NNS', 'VBD', 'VBG', 'VBZ', 'VBN']


def variants_of(w: str, poss: set) -> set:
    tags = set()
    for p in poss or ():
        tags.update(POS_TAGS.get(p, []))
    if not tags:
        tags = set(FALLBACK_TAGS)
    vs = set()
    for t in tags:
        try:
            vs.update(getInflection(w, tag=t, inflect_oov=True))
        except Exception:
            pass
    return {v.lower() for v in vs if v and v.lower() != w and len(v) > 1}


def build_defs(entries: list, include_examples: bool = True) -> str:
    """Kobo converter'daki (tureng_kobo.py) build_defs ile ayni mantik --
    burada da HTML gövde üretiyoruz (sametypesequence=h)."""
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
            parts.append(f'<span style="color:#555">[{html.escape(cat)}]</span>')
        parts.append(f'<b>{html.escape(tr)}</b>')
        ex_en = (e.get('example_en') or '').strip()
        ex_tr = (e.get('example_tr') or '').strip()
        if include_examples and ex_en:
            parts.append(f'<br/><span style="color:#666">&#8220;{html.escape(ex_en)}&#8221;</span>')
            if ex_tr:
                parts.append(f'<br/><span style="color:#888">&#8594; {html.escape(ex_tr)}</span>')
        ps.append('<p>' + ' '.join(parts) + '</p>')
    return ''.join(ps)


def main():
    args = sys.argv[1:]
    db_path = args[0] if args else 'db.json'
    out_name = args[1] if len(args) > 1 else 'stardict-en-tr'

    db = json.load(open(db_path, encoding='utf-8'))

    # 1) her başlık için HTML gövdesini üret, boş olanları ele
    bodies = {}
    plans = {}
    for word, entries in db.items():
        w = word.strip().lower()
        if not w or not entries:
            continue
        body = build_defs(entries)
        if not body:
            continue
        bodies[w] = body
        poss = {e.get('pos_en') for e in entries if e.get('pos_en')}
        plans[w] = poss

    # 2) .idx sırası: StarDict sözlükleri byte-sıralı (C strcmp) bekler
    words_sorted = sorted(bodies)
    word_pos = {w: i for i, w in enumerate(words_sorted)}

    # 3) .dict + .idx binary üret
    dict_blob = bytearray()
    idx_blob = bytearray()
    for w in words_sorted:
        body_bytes = bodies[w].encode('utf-8')
        offset = len(dict_blob)
        size = len(body_bytes)
        dict_blob.extend(body_bytes)
        idx_blob.extend(w.encode('utf-8') + b'\x00')
        idx_blob.extend(struct.pack('>I', offset))
        idx_blob.extend(struct.pack('>I', size))

    # 4) .syn: çekimli formlar -> ana kelimenin .idx sıradaki pozisyonu
    lemma_map = {}
    for w, poss in plans.items():
        for v in variants_of(w, poss):
            if v not in bodies:  # zaten kendi başlığı yoksa sadece o zaman syn ekle
                lemma_map.setdefault(v, word_pos[w])
    syn_blob = bytearray()
    for v in sorted(lemma_map):
        syn_blob.extend(v.encode('utf-8') + b'\x00')
        syn_blob.extend(struct.pack('>I', lemma_map[v]))

    # 5) .ifo
    ifo = (
        'StarDict\'s dict ifo file\n'
        'version=2.4.2\n'
        f'wordcount={len(words_sorted)}\n'
        f'synwordcount={len(lemma_map)}\n'
        f'idxfilesize={len(idx_blob)}\n'
        'bookname=Tureng İngilizce-Türkçe\n'
        f'date={date.today().isoformat()}\n'
        'sametypesequence=h\n'
    )

    os.makedirs(out_name, exist_ok=True)
    with open(f'{out_name}/{out_name}.ifo', 'w', encoding='utf-8') as f:
        f.write(ifo)
    with open(f'{out_name}/{out_name}.idx', 'wb') as f:
        f.write(idx_blob)
    dict_path = f'{out_name}/{out_name}.dict'
    with open(dict_path, 'wb') as f:
        f.write(dict_blob)

    # dictzip varsa .dict'i .dict.dz'ye sıkıştır (KOReader ikisini de okur,
    # .dict.dz ~%75-80 daha küçük olur, kurulumu kolaylaştırır)
    dz_ok = False
    if shutil.which('dictzip'):
        r = subprocess.run(['dictzip', '-f', dict_path], capture_output=True)
        # dictzip -f orijinali kendisi siler (gzip gibi); ayrıca silmeye gerek yok
        if r.returncode == 0 and os.path.exists(dict_path + '.dz'):
            dz_ok = True

    if lemma_map:
        with open(f'{out_name}/{out_name}.syn', 'wb') as f:
            f.write(syn_blob)

    zip_path = f'{out_name}.zip'
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for fn in os.listdir(out_name):
            z.write(f'{out_name}/{fn}', arcname=f'{out_name}/{fn}')

    print(f'[✓] {zip_path}: {len(words_sorted):,} başlık | {len(lemma_map):,} çekim (syn) | '
          f'{"dict.dz sıkıştırılmış" if dz_ok else "dict SIKIŞTIRILMADI (dictzip bulunamadı)"} | '
          f'{len(idx_blob)/1e6:.1f} MB idx')
    print(f'    KOReader\'a kurmak için: {zip_path} içindeki "{out_name}/" klasörünü '
          f'koreader/data/dict/ altına kopyala.')


if __name__ == '__main__':
    main()
