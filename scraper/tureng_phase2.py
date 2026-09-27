#!/usr/bin/env python3
"""Faz 2: TR→EN keşif taraması.

Amaç: Tureng'de VAR olup words.json listenizde OLMAYAN İngilizce başlıkları
bulup listeye eklemek. Yöntem: db.json'daki Türkçe anlamlardan tek-kelime
tohumlar çıkar, Tureng'in TR→EN tablolarını sorgula, İngilizce kolonundaki
başlıkları topla. Her bulunan başlık garantili Tureng kaydıdır.

Kullanım (İndirilenler klasöründe, ana scraper KAPALIYKEN):
    python3 tureng_phase2.py             # keşif + words.json'a ekleme
    python3 tureng_phase2.py --dry 200   # sadece ölçüm, hiçbir dosyaya yazmaz

Devamlılık: sorgulanan tohumlar 'phase2_queried.json' dosyasına 5000'de bir
kaydedilir. Ctrl+C ile durdurup yeniden çalıştırırsan kaldığı yerden devam
eder; en fazla son ~2 dakikalık iş yeniden yapılır. Baştan başlamak için
phase2_queried.json dosyasını sil.

Sonra: ana koşuyu yeniden başlat -> yeni başlıklar çekilir.
"""
import asyncio
import json
import os
import random
import re
import subprocess
import sys
import time
from urllib.parse import quote

from curl_cffi.requests import AsyncSession
import lxml.html

BASE = 'https://tureng.com/tr/turkce-ingilizce/'
TR_PAT = re.compile(r'^[a-zçğıöşüâîû]+$', re.I)
TOK = re.compile(r"^[a-z][a-z\-']*$")
CONC = 30
CHECKPOINT_EVERY = 5000
HEADERS = {'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'}


def _data_dir() -> str:
    """Repo yerlesiminde script_dir/../data; yoksa calisma dizini (eski davranis)."""
    d = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    return d if os.path.isdir(d) else '.'


STATE_FILE = os.path.join(_data_dir(), 'phase2_queried.json')


def extract_en_headwords(html) -> set:
    """Tablonun th.c2 başlığından kolon yönünü tespit eder, tek-kelime
    İngilizce başlıkları toplar; [obsolete] gibi etiketleri kırpar."""
    try:
        tree = lxml.html.fromstring(html)
    except lxml.etree.ParserError:
        return set()
    out = set()
    for tbl in tree.xpath('//table[@id="englishResultsTable"]'):
        th = tbl.xpath('.//th[contains(@class,"c2")]')
        if not th:
            continue
        head = th[0].text_content().strip()
        col = 2 if 'ngilizce' in head else (3 if 'ürkçe' in head else None)
        if col is None:
            continue
        for tr in tbl.xpath('.//tr[./td]'):
            tds = tr.xpath('./td')
            if len(tds) < 4:
                continue
            cell = tds[col]
            a = cell.find('a')
            txt = (a.text_content() if a is not None else cell.text_content()).strip()
            txt = re.sub(r'\s*\[.*?\]\s*', ' ', txt).strip().lower()
            if ' ' in txt:  # bileşik cümleler sözlük başlığı değildir
                continue
            if TOK.match(txt) and 2 <= len(txt) <= 25:
                out.add(txt)
    return out


def load_seeds(db) -> list:
    seeds = set()
    for entries in db.values():
        for e in entries:
            for tok in re.split(r'[\s,;()]+', e.get('tr') or ''):
                if 3 <= len(tok) <= 18 and TR_PAT.match(tok):
                    seeds.add(tok.lower())
    return sorted(seeds)


def load_state() -> set:
    try:
        return set(json.load(open(STATE_FILE, encoding='utf-8')))
    except Exception:
        return set()


def save_state(queried: set):
    tmp = STATE_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(sorted(queried), f)
    os.replace(tmp, STATE_FILE)


def scraper_running() -> bool:
    try:
        out = subprocess.run(['pgrep', '-f', 'python.*tureng_dictionary'],
                             capture_output=True, text=True)
        return out.returncode == 0
    except Exception:
        return False


async def crawl(session, seeds: list, known: set, queried: set, persist: bool = True) -> set:
    """Tohumları sorgula; listende olmayan EN başlıkları döndür.
    queried seti canlı güncellenir, CHECKPOINT_EVERY'de bir diske yazılır."""
    sem = asyncio.Semaphore(CONC)
    prog = {'done': 0, 'ok': 0}
    new = set()
    t0 = time.perf_counter()

    async def one(w):
        async with sem:
            for attempt in range(3):
                try:
                    r = await session.get(BASE + quote(w))
                    if r.status_code == 200:
                        en = extract_en_headwords(r.text)
                        new.update(x for x in en if x not in known)
                        queried.add(w)  # sadece başarılı sorgu "tamam" sayılır
                        prog['ok'] += 1
                        break
                    await asyncio.sleep(2 * (attempt + 1))
                except Exception:
                    await asyncio.sleep(1 + attempt)
            prog['done'] += 1  # hata edenler checkpoint'e girmez, sonraki koşuda denenir
            if persist and prog['done'] % CHECKPOINT_EVERY == 0:
                await asyncio.to_thread(save_state, queried)

    async def reporter():
        while True:
            await asyncio.sleep(10)
            d, dt = prog['done'], time.perf_counter() - t0
            rate = d / dt if dt > 0 else 0
            eta = (len(seeds) - d) / rate / 60 if rate > 0 else 0
            print(f'[*] {d:,}/{len(seeds):,} (%{100*d/len(seeds):.1f}) | '
                  f'{rate:.0f} kelime/sn | ETA ~{eta:.0f} dk | '
                  f'keşfedilen: {len(new):,}', flush=True)

    rep = asyncio.create_task(reporter())
    try:
        await asyncio.gather(*(one(w) for w in seeds))
    finally:
        rep.cancel()
        if persist:
            save_state(queried)
    return new


async def run(dry: bool, sample_size):
    if not dry and scraper_running():
        print("[!] Ana scraper çalışıyor gibi görünüyor. Önce onu durdur (Ctrl+C),")
        print("    çünkü iki süreç de words.json'ı yazıyor.")
        sys.exit(1)

    DATA = _data_dir()
    db = json.load(open(os.path.join(DATA, 'db.json'), encoding='utf-8'))
    wordlist = set(json.load(open(os.path.join(DATA, 'words.json'), encoding='utf-8')))
    known = wordlist | set(db)
    seeds = load_seeds(db)
    queried = set() if dry else load_state()
    remaining = [s for s in seeds if s not in queried]
    print(f"[*] Türkçe tohum: {len(seeds):,} | liste: {len(wordlist):,} | db: {len(db):,}")
    if not dry:
        print(f"[*] Checkpoint: {len(queried):,} tohum daha önce sorgulanmış, "
              f"bu koşuda {len(remaining):,} tohum kalıyor")

    session = AsyncSession(impersonate='chrome', timeout=15, headers=HEADERS)
    try:
        if dry:
            sample = random.sample(seeds, min(sample_size or 200, len(seeds)))
            new = await crawl(session, sample, known, queried, persist=False)
            est = len(new) * len(seeds) / len(sample)
            print(f"[dry] {len(sample)} tohum -> {len(new):,} yeni başlık; "
                  f"kaba projeksiyon: ~{est:,.0f} (tekrarlarla düşer)")
            print("[dry] örnek:", sorted(new)[:20])
            return

        rnd = 0
        while remaining:
            rnd += 1
            print(f"[*] Tur {rnd}: {len(remaining):,} tohum sorgulanıyor...")
            t0 = time.perf_counter()
            new = await crawl(session, remaining, known, queried)
            print(f"[*] Tur {rnd} bitti: {len(new):,} yeni EN başlık "
                  f"({time.perf_counter()-t0:.0f} sn)", flush=True)
            if not new:
                break
            wordlist |= new
            with open(os.path.join(DATA, 'words.json.tmp'), 'w', encoding='utf-8') as f:
                json.dump(sorted(wordlist), f, ensure_ascii=False)
            os.replace(os.path.join(DATA, 'words.json.tmp'), os.path.join(DATA, 'words.json'))
            print(f"[*] words.json güncellendi -> {len(wordlist):,} kelime", flush=True)
            # yeni db kayıtları yeni tohum üretmiş olabilir; turda devam et
            db = json.load(open(os.path.join(DATA, 'db.json'), encoding='utf-8'))
            seeds = load_seeds(db)
            known = wordlist | set(db)
            remaining = [s for s in seeds if s not in queried]

        print(f"[✓] Keşif bitti. Liste: {len(wordlist):,} kelime. "
              "Şimdi ana koşuyu yeniden başlat, yeni başlıklar çekilsin.")
    finally:
        await session.close()


if __name__ == '__main__':
    dry = '--dry' in sys.argv
    n = None
    if dry:
        i = sys.argv.index('--dry')
        n = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else None
    asyncio.run(run(dry=dry, sample_size=n))
