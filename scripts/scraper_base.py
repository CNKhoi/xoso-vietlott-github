from __future__ import annotations

import asyncio
import os
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Iterable

import httpx
from bs4 import BeautifulSoup

PROVINCES = [
    'An Giang','Bạc Liêu','Bến Tre','Bình Dương','Bình Phước','Bình Thuận','Cà Mau','Cần Thơ',
    'Đà Lạt','Đồng Nai','Đồng Tháp','Hậu Giang','Kiên Giang','Long An','Sóc Trăng','Tây Ninh',
    'Tiền Giang','TP. HCM','Trà Vinh','Vĩnh Long','Vũng Tàu'
]
PROVINCE_ALIASES = {
    'TP.HCM': 'TP. HCM', 'TP HCM': 'TP. HCM', 'TP. HCM': 'TP. HCM',
}
PRIZE_SPECS = {
    '100N': (2, 1), '200N': (3, 1), '400N': (4, 3), '1TR': (4, 1),
    '3TR': (5, 7), '10TR': (5, 2), '15TR': (5, 1), '30TR': (5, 1), '2TỶ': (6, 1),
}
DATE_RE = re.compile(r'^(\d{1,2})/(\d{1,2})/?(\d{4})$')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/154 Safari/537.36',
    'Accept-Language': 'vi-VN,vi;q=0.9,en;q=0.7',
}


def normalize_province(s: str) -> str | None:
    s = re.sub(r'\s+', ' ', s.strip())
    if s in PROVINCE_ALIASES:
        return PROVINCE_ALIASES[s]
    for p in PROVINCES:
        if s.casefold() == p.casefold():
            return p
    return None


def normalize_date_token(token: str) -> str | None:
    m = DATE_RE.match(token.strip())
    if not m:
        return None
    d, mo, y = map(int, m.groups())
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def _next_label_index(tokens: list[str], start: int, labels: set[str], max_look=120):
    for i in range(start, min(len(tokens), start + max_look)):
        if tokens[i].strip() in labels:
            return i
    return None


def parse_xsmn_html(html: str, source_url: str = '') -> list[dict]:
    soup = BeautifulSoup(html, 'html.parser')
    tokens = [re.sub(r'\s+', ' ', x.strip()) for x in soup.stripped_strings if x.strip()]
    labels = set(PRIZE_SPECS)
    all_rows: list[dict] = []
    seen_blocks = set()

    for i, token in enumerate(tokens):
        draw_date = normalize_date_token(token)
        if not draw_date:
            continue
        # A real result block has province names then 100N shortly after the date.
        p100 = _next_label_index(tokens, i + 1, {'100N'}, max_look=25)
        if p100 is None:
            continue
        provinces = []
        for t in tokens[i + 1:p100]:
            p = normalize_province(t)
            if p and p not in provinces:
                provinces.append(p)
        if len(provinces) < 3:
            continue
        block_key = (draw_date, tuple(provinces))
        if block_key in seen_blocks:
            continue
        seen_blocks.add(block_key)

        cursor = p100
        ok_prizes = 0
        for label, (digits, per_province) in PRIZE_SPECS.items():
            # Find the requested label after current cursor.
            try:
                li = next(j for j in range(cursor, min(len(tokens), cursor + 150)) if tokens[j].strip() == label)
            except StopIteration:
                continue
            # Find next prize label, or stop after a conservative window.
            next_i = min(len(tokens), li + 80)
            for j in range(li + 1, min(len(tokens), li + 100)):
                if tokens[j].strip() in labels:
                    next_i = j
                    break
            segment = ' '.join(tokens[li + 1:next_i])
            nums = re.findall(rf'(?<!\d)\d{{{digits}}}(?!\d)', segment)
            need = len(provinces) * per_province
            if len(nums) < need:
                continue
            nums = nums[:need]
            ok_prizes += 1
            for pi, province in enumerate(provinces):
                chunk = nums[pi * per_province:(pi + 1) * per_province]
                for idx, value in enumerate(chunk):
                    all_rows.append({
                        'draw_date': draw_date,
                        'province': province,
                        'prize': label,
                        'item_index': idx,
                        'value': value.zfill(digits),
                        'source': source_url,
                    })
            cursor = next_i
        if ok_prizes < 7:
            # Remove partially parsed suspicious block.
            all_rows = [r for r in all_rows if not (r['draw_date'] == draw_date and r['province'] in provinces)]

    unique = {}
    for r in all_rows:
        unique[(r['draw_date'], r['province'], r['prize'], r['item_index'])] = r
    return list(unique.values())


VIET_RE = re.compile(
    r'Kết quả QSMT kỳ\s*#(\d+)\s*ngày\s*(\d{1,2}/\d{1,2}/\d{4})\s*'
    r'((?:\d{2}[\s|]+){5,6}\d{2})', re.I
)


def parse_vietlott_html(html: str, product: str, source_url: str = '') -> list[dict]:
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text(' ', strip=True)
    text = re.sub(r'\s+', ' ', text)
    out = []
    max_n = 45 if product == 'mega645' else 55
    for m in VIET_RE.finditer(text):
        draw_id = int(m.group(1))
        dt = datetime.strptime(m.group(2), '%d/%m/%Y').date().isoformat()
        vals = [int(x) for x in re.findall(r'\d{2}', m.group(3))]
        if product == 'mega645':
            if len(vals) < 6:
                continue
            numbers, special = vals[:6], None
        else:
            if len(vals) < 7:
                continue
            numbers, special = vals[:6], vals[6]
        if len(set(numbers)) != 6 or any(n < 1 or n > max_n for n in numbers):
            continue
        out.append({
            'product': product,
            'draw_id': draw_id,
            'draw_date': dt,
            'numbers': sorted(numbers),
            'special': special,
            'source': source_url,
        })
    unique = {(r['product'], r['draw_id']): r for r in out}
    return list(unique.values())


class Scraper:
    def __init__(self, timeout: float | None = None, concurrency: int = 8):
        self.timeout = timeout or float(os.getenv('HTTP_TIMEOUT', '20'))
        self.sem = asyncio.Semaphore(concurrency)

    async def fetch(self, client: httpx.AsyncClient, url: str) -> str:
        async with self.sem:
            last_exc = None
            for delay in (0, 0.8, 2.0):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    r = await client.get(url, headers=HEADERS, timeout=self.timeout, follow_redirects=True)
                    r.raise_for_status()
                    return r.text
                except Exception as e:
                    last_exc = e
            raise last_exc

    async def fetch_xsmn_anchor(self, client: httpx.AsyncClient, anchor: date):
        url = f'https://www.minhchinh.com/ket-qua-xo-so-mien-nam/{anchor:%d-%m-%Y}.html'
        html = await self.fetch(client, url)
        return parse_xsmn_html(html, url)

    async def fetch_viet_anchor(self, client: httpx.AsyncClient, product: str, anchor: date):
        if product == 'mega645':
            slug = 'xs-mega-645-ket-qua-mega-645-ngay'
        else:
            slug = 'xs-power-655-ket-qua-power-655-ngay'
        url = f'https://www.minhchinh.com/{slug}-{anchor:%d-%m-%Y}.html'
        html = await self.fetch(client, url)
        return parse_vietlott_html(html, product, url)

    @staticmethod
    def product_draw_dates(product: str, start: date, end: date) -> list[date]:
        # Python weekday: Mon=0. Mega: Wed/Fri/Sun. Power: Tue/Thu/Sat.
        allowed = {2, 4, 6} if product == 'mega645' else {1, 3, 5}
        cur = start
        out = []
        while cur <= end:
            if cur.weekday() in allowed:
                out.append(cur)
            cur += timedelta(days=1)
        return out

    async def sync_history(self, store, days: int = 365, incremental: bool = False):
        today = datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).date()
        start = today - timedelta(days=(21 if incremental else days))
        stats = {'xsmn_pages': 0, 'xsmn_rows': 0, 'mega_pages': 0, 'mega_draws': 0, 'power_pages': 0, 'power_draws': 0, 'errors': []}

        async with httpx.AsyncClient() as client:
            # Each XSMN page exposes roughly one week, so anchor every 7 days.
            xanchors = []
            d = today
            while d >= start:
                xanchors.append(d)
                d -= timedelta(days=7)
            x_tasks = [self.fetch_xsmn_anchor(client, d) for d in xanchors]
            x_results = await asyncio.gather(*x_tasks, return_exceptions=True)
            for anchor, result in zip(xanchors, x_results):
                stats['xsmn_pages'] += 1
                if isinstance(result, Exception):
                    stats['errors'].append(f'XSMN {anchor}: {type(result).__name__}: {result}')
                else:
                    stats['xsmn_rows'] += store.upsert_xsmn(result)

            # Vietlott pages expose several prior draws. Anchor roughly every 12 days.
            for product, key in [('mega645', 'mega'), ('power655', 'power')]:
                draw_dates = self.product_draw_dates(product, start, today)
                anchors = list(reversed(draw_dates))[::5]  # about five draws per source page
                v_tasks = [self.fetch_viet_anchor(client, product, d) for d in anchors]
                v_results = await asyncio.gather(*v_tasks, return_exceptions=True)
                for anchor, result in zip(anchors, v_results):
                    stats[f'{key}_pages'] += 1
                    if isinstance(result, Exception):
                        stats['errors'].append(f'{product} {anchor}: {type(result).__name__}: {result}')
                    else:
                        stats[f'{key}_draws'] += store.upsert_vietlott(result)

        return stats
