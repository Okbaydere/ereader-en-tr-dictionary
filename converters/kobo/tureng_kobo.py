#!/usr/bin/env python3
"""db.json -> Kobo sözlük paketi (dicthtml-*.zip). v7 — anchor düzeltmesi.

Kullanım: python3 tureng_kobo.py [çıktı.zip] [--no-examples]
Gereksinim: pip install marisa-trie lemminflect
Referanslar:
  https://pgaskin.net/dictutil/dicthtml/format.html
  https://github.com/ilius/pyglossary (ebook_kobo/writer.py)
"""
import gzip
import html
import json
import os
import sys
import tempfile
import unicodedata
import zipfile
from collections import defaultdict

import marisa_trie
from lemminflect import getInflection

NOISE_CATS = {'yaygın kullanım', 'genel', ''}
HTML_HEADER = '<?xml version="1.0" encoding="utf-8"?><html>\n'


def word_prefix(w: str) -> str:
    """Kobo DictionaryParser::htmlForWord algoritması (= PyGlossary get_prefix)."""
    s = w[:2].lower().strip()
    if not s:
        return '11'
    if '\u0400' <= s[0] <= '\u04FF':  # Kiril: padsiz
        return s
    if len(s) == 1:
        s += 'a'
    if not (unicodedata.category(s[0]).startswith('L')
            and unicodedata.category(s[1]).startswith('L')):
        return '11'
    return s


POS_TAGS = {
    'noun': ['NNS'],
    'verb': ['VBD', 'VBG', 'VBZ', 'VBN'],
    'adjective': ['JJR', 'JJS'],
    'adverb': ['RBR', 'RBS'],
}
FALLBACK_TAGS = ['NNS', 'VBD', 'VBG', 'VBZ', 'VBN']


def variants_of(w: str, poss: set) -> set:
    """lemminflect ile çekimli formlar (düzensizler exception tablosundan)."""
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


def build_defs(entries: list, include_examples: bool) -> str:
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
        # kategori etiketi girişte bir kez (caught'ta 3x "Irregular Verb" oluyordu)
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


def build_entry(anchor_word: str, main_word: str, entries: list, variants: set,
                include_examples: bool, roots: list = None) -> str:
    """anchor_word: bu HTML kopyasının <a name> değeri — bu kopyanın YAZILDIĞI
    prefix'e sahip gerçek terim (ana kelime ya da bir çekim) olmalı, sabit
    ana kelime DEĞİL. Aksi halde ilk iki harfi değişen çekimlerde (run/ran
    gibi) Kobo o çekimi hiç bulamaz.
    main_word: kelimenin lemma/ana hâli — başlıkta gösterim için.
    roots: bu kelime başka bir kelimenin çekimi ise kök(ler) — girişin en
    başında 'kök: catch' satırı olarak gösterilir (caught/gone/ran gibi
    Tureng'in kendi başlığı olan çekimli formlar için)."""
    defs = build_defs(entries, include_examples)
    if not defs:
        return ''
    a = html.escape(anchor_word)
    disp = html.escape(main_word) if main_word == anchor_word else \
        f'{html.escape(main_word)}, {html.escape(anchor_word)}'
    var_block = ('<var>'
                 + ''.join(f'<variant name="{html.escape(v)}"/>' for v in sorted(variants))
                 + '</var>') if variants else '<var></var>'
    root_line = ''
    if main_word == anchor_word and roots:
        rl = ', '.join(f'<b>{html.escape(r)}</b>' for r in roots)
        root_line = f'<p><span style="color:#888">kök: {rl}</span></p>'
    # Resmi format: anchor <w>'nin doğrudan çocuğu, tanım tek <div> içinde
    return f'<w><a name="{a}" /><div><b>{disp}</b>{var_block}<br/>{root_line}{defs}</div></w>'


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    include_examples = '--no-examples' not in sys.argv
    out = args[0] if args else 'dicthtml-en.zip'

    # repo yerlesiminde data/db.json; yoksa CWD (eski davranis)
    data_dir = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data'))
    if not os.path.isdir(data_dir):
        data_dir = '.'
    db = json.load(open(os.path.join(data_dir, 'db.json'), encoding='utf-8'))

    plans = {}
    for word, entries in db.items():
        w = word.strip().lower()
        if not w or not entries:
            continue
        poss = {e.get('pos_en') for e in entries if e.get('pos_en')}
        plans[w] = (entries, variants_of(w, poss))

    # kök haritası: çekimli form -> asıl kelime (caught -> catch, gone -> go)
    lemma_map = defaultdict(list)
    for w, (entries, variants) in plans.items():
        for v in variants:
            lemma_map[v].append(w)

    # Her kelime için, HER prefix kopyası kendi doğru anchor'ıyla ayrı ayrı üretilir.
    buckets = defaultdict(list)
    index_keys = set()
    skipped = 0
    for w, (entries, variants) in plans.items():
        base_entry = build_entry(w, w, entries, variants, include_examples,
                                 roots=lemma_map.get(w))
        if not base_entry:
            skipped += 1
            continue
        index_keys.add(w)
        index_keys.update(variants)

        # ana kelimenin kendi prefix'i -> anchor = w
        buckets[word_prefix(w)].append((w, base_entry))

        # her çekimin kendi prefix'i -> anchor = o çekimin adı (farklıysa yeniden üret)
        for v in variants:
            vp = word_prefix(v)
            if vp == word_prefix(w):
                continue  # zaten base_entry ile aynı dosyada, tekrar eklemeye gerek yok
            v_entry = build_entry(v, w, entries, variants, include_examples)
            buckets[vp].append((v, v_entry))

    # words indeksi: düz marisa trie (gzip DEĞİL)
    with tempfile.NamedTemporaryFile(suffix='.marisa', delete=False) as tf:
        tmpname = tf.name
    trie = marisa_trie.Trie(sorted(index_keys))
    trie.save(tmpname)
    with open(tmpname, 'rb') as f:
        words_blob = f.read()
    os.unlink(tmpname)

    total_copies = 0
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_STORED) as z:  # içlerde gzip var; zip STORED
        z.writestr('words', words_blob)
        for prefix, items in sorted(buckets.items()):
            items.sort(key=lambda x: (len(x[0]), x[0]))  # kısa -> uzun alfabetik
            body = ''.join(e for _, e in items)
            blob = gzip.compress(f'{HTML_HEADER}{body}</html>'.encode('utf-8'))
            z.writestr(f'{prefix}.html', blob)
            total_copies += len(items)

    print(f'[✓] {out}: {len(plans)-skipped:,} başlık | {len(index_keys):,} indeks anahtarı | '
          f'{total_copies:,} gzip dosya girişi | {len(words_blob)/1e6:.1f} MB words | '
          f'{os.path.getsize(out)/1e6:.1f} MB toplam | boş geçilen: {skipped}')


if __name__ == '__main__':
    main()
