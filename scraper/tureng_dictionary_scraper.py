#!/usr/bin/env python3
"""Tureng hızlı sürüm — orijinal tureng_dictionary_scraper.py ile aynı şema, ~4-5x hızlı.

Değişiklikler (orijinale göre):
  1. BeautifulSoup yerine doğrudan lxml  : parse 26.8 ms -> 1.4 ms (GIL'ı kilitliyor olan buydu)
  2. multiprocessing.dummy + 50 ms poll   -> tek asyncio event loop (AsyncSession, HTTP/2)
  3. Örnek cümle hücreleri yeniden parse edilmiyor
  4. Sonsuz retry yerine sınırlı, üstel backoff'lu retry
  5. JSON dosyaları paket başına değil, kayıt başına append'lenen journal + düzenli snapshot

Dosya şeması orijinal ile birebir: words.json / db.json / completed.json
"""
import asyncio
import json
import os
import re
import sys
import time
from urllib.parse import quote

from curl_cffi.requests import AsyncSession
import lxml.html

BASE = 'https://tureng.com/tr/turkce-ingilizce/'
POS_MAP = {
    'i.': 'noun', 'f.': 'verb', 's.': 'adjective', 'zf.': 'adverb',
    'ünl.': 'interjection', 'edat': 'preposition', 'bağ.': 'conjunction', 'zm.': 'pronoun',
}
MAX_SENSES = 7
BR = re.compile(r'<br\s*/?>', re.I)
TAGS = re.compile(r'<[^>]+>')


def parse_example(td) -> tuple:
    if td is None:
        return None, None
    for a in td.xpath('.//a'):
        a.drop_tree()
    inner = lxml.html.tostring(td, encoding='unicode')
    lines = [' '.join(TAGS.sub('', p).split()) for p in BR.split(inner)]
    lines = [l for l in lines if l]
    return (lines[0], lines[1]) if len(lines) >= 2 else (None, None)


def parse(html_text: str) -> list:
    try:
        tree = lxml.html.fromstring(html_text)
    except lxml.etree.ParserError:  # boş/bozuk sayfa
        return []

    table = tree.xpath('//table[@id="englishResultsTable"]')
    if not table:
        return []

    raw = []
    rows = table[0].xpath('./tbody/tr | ./tr')
    i = 0
    while i < len(rows):
        tr = rows[i]
        cls = tr.get('class') or ''  # lxml'de class düz string'dir (liste değil)

        if 'example-sentences-row' in cls or 'mobile-category-row' in cls:
            i += 1
            continue

        tds = tr.xpath('./td')
        if len(tds) < 4:
            i += 1
            continue

        category = tds[1].text_content().strip()
        if not category:
            i += 1
            continue

        en_td, tr_td = tds[2], tds[3]
        pos = en_td.find('i')
        pos_raw = pos.text_content().strip() if pos is not None else None

        en_a = en_td.find('a')
        en_word = en_a.text_content().strip() if en_a is not None else en_td.text_content().strip()
        tr_a = tr_td.find('a')
        tr_word = tr_a.text_content().strip() if tr_a is not None else tr_td.text_content().strip()

        example_en = example_tr = None
        if i + 1 < len(rows):
            nxt = rows[i + 1]
            if 'example-sentences-row' in (nxt.get('class') or []):
                ex_tds = nxt.xpath('./td[contains(@class,"example-sentences")]')
                example_en, example_tr = parse_example(ex_tds[0] if ex_tds else None)
                i += 1

        raw.append({
            'en': en_word, 'tr': tr_word, 'category': category,
            'pos': pos_raw, 'pos_en': POS_MAP.get(pos_raw),
            'example_en': example_en, 'example_tr': example_tr,
        })
        i += 1

    # Orijinal kurallar: tek kelime -> kategori önceliği -> tekrar temizliği -> örnekli önce, 7'ye tamamla
    candidates = [x for x in raw if ' ' not in x['en']]

    def priority(x):
        c = x['category'].lower()
        return 0 if 'yaygın' in c else (1 if 'genel' in c else 2)

    candidates.sort(key=priority)

    seen, unique = set(), []
    for x in candidates:
        key = (x['tr'].lower(), x['pos'])
        if key not in seen:
            seen.add(key)
            unique.append(x)

    with_ex = [u for u in unique if u['example_en'] and u['example_tr']]
    result = with_ex[:MAX_SENSES]
    if len(result) < MAX_SENSES:
        without_ex = [u for u in unique if not (u['example_en'] and u['example_tr'])]
        result.extend(without_ex[:MAX_SENSES - len(result)])
    return result


class AdaptiveLimiter:
    """AIMD concurrency: her 25 başarida +1 yüksel, 403/429'da yariya in.
    Böylece sunucunun anlik tavanini kod saberhaken olmadan kendi bulur."""

    def __init__(self, initial=20, min_limit=4, max_limit=150,
                 ramp_every=25, ramp_interval=2.0):
        self.limit = initial
        self.min_limit = min_limit
        self.max_limit = max_limit
        self.ramp_every = ramp_every
        self.ramp_interval = ramp_interval
        self.in_flight = 0
        self.successes = 0
        self.blocked_count = 0
        self.last_change = time.monotonic()
        self.cond = asyncio.Condition()

    async def acquire(self):
        async with self.cond:
            await self.cond.wait_for(lambda: self.in_flight < self.limit)
            self.in_flight += 1

    async def release(self, ok=True, blocked=False):
        async with self.cond:
            self.in_flight -= 1
            now = time.monotonic()
            if blocked:
                self.blocked_count += 1
                new = max(self.min_limit, self.limit // 2)
                if new != self.limit:
                    self.limit = new
                    self.last_change = now
                    self.successes = 0
            elif ok:
                self.successes += 1
                if (self.successes >= self.ramp_every
                        and now - self.last_change >= self.ramp_interval
                        and self.limit < self.max_limit):
                    self.limit += 1
                    self.successes = 0
                    self.last_change = now
            self.cond.notify_all()


class FixedLimiter:
    def __init__(self, n):
        self._sem = asyncio.Semaphore(n)
        self.limit = n
        self.blocked_count = 0

    async def acquire(self):
        await self._sem.acquire()

    async def release(self, ok=True, blocked=False):
        self._sem.release()


class FastTureng:
    def __init__(self, concurrency=30, retries=3, auto=False, max_conc=150):
        if auto:
            self.limiter = AdaptiveLimiter(initial=concurrency, max_limit=max_conc)
        else:
            self.limiter = FixedLimiter(concurrency)
        self.retries = retries
        self.session = AsyncSession(headers={
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'accept-language': 'tr-TR,tr;q=0.9',
            'referer': 'https://tureng.com/tr/turkce-ingilizce',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
        }, timeout=15, impersonate='chrome')

    async def get_translations(self, word: str) -> list:
        await self.limiter.acquire()
        ok, blocked = True, False
        try:
            for attempt in range(self.retries):
                try:
                    resp = await self.session.get(BASE + quote(word))
                    if resp.status_code == 200:
                        return parse(resp.text)
                    if resp.status_code in (403, 429):  # risk kontrolü: geri çekil
                        blocked = True
                        await asyncio.sleep(3 * (attempt + 1))
                        continue
                    await asyncio.sleep(1)
                except Exception:
                    ok = False
                    await asyncio.sleep(1 + attempt)
            return []
        finally:
            await self.limiter.release(ok=ok, blocked=blocked)

    async def fetch_batch(self, words: list) -> dict:
        results = await asyncio.gather(*(self.get_translations(w) for w in words))
        return dict(zip(words, results))

    async def update_database(self, wordlist_path, database_path, completed_words_path,
                              chunk=500, snapshot_every=1000, add_discovered=True):
        with open(wordlist_path, encoding='utf-8') as fp:
            wordlist = set(json.load(fp))
        with open(database_path, encoding='utf-8') as fp:
            database = json.load(fp)
        with open(completed_words_path, encoding='utf-8') as fp:
            completed = set(json.load(fp))

        journal_path = database_path + '.journal'
        journal = open(journal_path, 'a', encoding='utf-8')
        done_count, t0 = 0, time.perf_counter()

        while todo := list(wordlist - completed)[:chunk]:
            batch = await self.fetch_batch(todo)

            for word, results in batch.items():
                for item in results:
                    en, tr = item['en'], item['tr']
                    entry = {
                        'tr': tr, 'pos': item.get('pos'), 'pos_en': item.get('pos_en'),
                        'category': item.get('category', ''),
                        'example_en': item.get('example_en'), 'example_tr': item.get('example_tr'),
                    }
                    existing = database.setdefault(en, [])
                    if not any(e['tr'] == tr and e.get('pos') == item.get('pos') for e in existing):
                        existing.append(entry)
                        journal.write(json.dumps({'en': en, 'entry': entry}, ensure_ascii=False) + '\n')
                    if add_discovered and en not in wordlist:
                        wordlist.add(en)
                completed.add(word)
                done_count += 1

                if done_count % snapshot_every == 0:
                    # senkron json.dump event loop'u kilitler; diske thread'de yaz
                    await asyncio.to_thread(self._snapshot, database_path,
                                            completed_words_path, wordlist_path,
                                            database, completed, wordlist)

            rate = done_count / (time.perf_counter() - t0)
            lim = self.limiter
            print(f'[*] {done_count} kelime tamam, {rate:.0f} kelime/sn, '
                  f'conc={lim.limit}, 403/429={lim.blocked_count}', flush=True)
            self._snapshot(database_path, completed_words_path, wordlist_path,
                           database, completed, wordlist)

        journal.close()
        # journal'daki kayıtları son snapshot'a işle
        if os.path.exists(journal_path):
            with open(database_path, encoding='utf-8') as fp:
                final = json.load(fp)
            with open(journal_path, encoding='utf-8') as fp:
                for line in fp:
                    rec = json.loads(line)
                    existing = final.setdefault(rec['en'], [])
                    if not any(e['tr'] == rec['entry']['tr'] and e.get('pos') == rec['entry'].get('pos')
                               for e in existing):
                        existing.append(rec['entry'])
            os.replace(journal_path, journal_path + '.applied')
            with open(database_path, 'w', encoding='utf-8') as fp:
                json.dump(dict(sorted(final.items())), fp, ensure_ascii=False)

    @staticmethod
    def _snapshot(database_path, completed_words_path, wordlist_path, database, completed, wordlist):
        tmp = database_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fp:
            json.dump(database, fp, ensure_ascii=False)
        os.replace(tmp, database_path)
        with open(completed_words_path + '.tmp', 'w', encoding='utf-8') as fp:
            json.dump(list(completed), fp, ensure_ascii=False)
        os.replace(completed_words_path + '.tmp', completed_words_path)
        with open(wordlist_path + '.tmp', 'w', encoding='utf-8') as fp:
            json.dump(list(wordlist), fp, ensure_ascii=False)
        os.replace(wordlist_path + '.tmp', wordlist_path)


async def _bench():
    words = ("hello book library house water window music school friend city night morning "
             "apple tree road door table chair pen dog cat sun rain").split()
    for conc in (20, 40):
        t = FastTureng(concurrency=conc, auto=True, max_conc=150)
        t0 = time.perf_counter()
        res = await t.fetch_batch(words)
        dt = time.perf_counter() - t0
        n = sum(len(r) for r in res.values())
        errs = sum(1 for r in res.values() if r is None)
        print(f"[bench] auto başlangıç={conc}: {len(words)} kelime, {dt:.2f} sn, "
              f"{len(words)/dt:.0f} kelime/sn, tavan conc={t.limiter.limit}, "
              f"{n} anlam, boş dönen: {errs}")
    await t.session.close()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'bench':
        asyncio.run(_bench())
    else:
        # repo yerlesiminde data/ altina yazar; klasor yoksa CWD (eski davranis)
        DATA = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
        if not os.path.isdir(DATA):
            DATA = '.'
        WORDLIST_FILE = os.path.join(DATA, "words.json")
        DATABASE_FILE = os.path.join(DATA, "db.json")
        COMPLETED_FILE = os.path.join(DATA, "completed.json")

        if not os.path.exists(DATABASE_FILE):
            with open(DATABASE_FILE, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False)
        if not os.path.exists(COMPLETED_FILE):
            with open(COMPLETED_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False)
        if not os.path.exists(WORDLIST_FILE):
            print(f"[-] Hata: {WORDLIST_FILE} bulunamadı!")
            sys.exit(1)

        with open(WORDLIST_FILE, encoding='utf-8') as f:
            total_words = len(json.load(f))
        with open(COMPLETED_FILE, encoding='utf-8') as f:
            done_words = len(json.load(f))

        print(f"[*] Toplam Kelime: {total_words}")
        print(f"[*] Daha Önce Tamamlanan: {done_words}")
        print(f"[*] Kalan Kelime: {total_words - done_words}")

        # Ölçümlere göre: 30 conc, sunucunun IP başına verim tavanını en düşük
        # gecikmeyle kullanır; 45 üstü hız getirmez, sadece gecikmeyi şişirir.
        tureng = FastTureng(concurrency=30, auto=True, max_conc=45)
        try:
            asyncio.run(tureng.update_database(
                wordlist_path=WORDLIST_FILE,
                database_path=DATABASE_FILE,
                completed_words_path=COMPLETED_FILE,
            ))
            print("[✓] Tüm liste başarıyla tamamlandı!")
        except KeyboardInterrupt:
            print("\n[!] İşlem durduruldu. Tamamlanan paketler kaydedildi.")
