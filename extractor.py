import os
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    import cloudscraper
except Exception:  # pragma: no cover
    cloudscraper = None


M3U8_PATTERNS = [
    r'https?://[^\"\'\s>]+\.m3u8(?:\?[^\"\'\s>]*)?',
    r'"(\/[^\"]+\.m3u8(?:\?[^\"]*)?)"',
    r"'(\/[^']+\.m3u8(?:\?[^']*)?)'",
]

VIDEO_PATTERNS = [
    r'https?://[^\"\'\s>]+\.mp4(?:\?[^\"\'\s>]*)?',
    r'"(\/[^\"]+\.mp4(?:\?[^\"]*)?)"',
    r"'(\/[^']+\.mp4(?:\?[^']*)?)'",
]

SUB_PATTERNS = [
    r'https?://[^\"\'\s>]+\.(?:vtt|srt|ass)(?:\?[^\"\'\s>]*)?',
    r'"(\/[^\"]+\.(?:vtt|srt|ass)(?:\?[^\"]*)?)"',
    r"'(\/[^']+\.(?:vtt|srt|ass)(?:\?[^']*)?)'",
]


LANG_HINTS = {
    'en': ['english', 'eng', 'en'],
    'bn': ['bangla', 'bengali', 'bn'],
}


def _make_session(cookie_path=None):
    if cloudscraper is not None:
        session = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
    else:
        session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'
    })
    if cookie_path and os.path.exists(cookie_path):
        with open(cookie_path, 'r', encoding='utf-8', errors='ignore') as f:
            raw = f.read().strip()
            if raw:
                session.headers['Cookie'] = raw
    return session


def _normalize(url, base_url):
    return urljoin(base_url, url)


def _guess_lang(text):
    t = (text or '').lower()
    for code, hints in LANG_HINTS.items():
        if any(h in t for h in hints):
            return code
    return 'unknown'


def _collect_from_html(html, base_url):
    found_video = []
    found_subs = []
    soup = BeautifulSoup(html, 'lxml')

    for tag in soup.find_all(['track', 'source', 'video', 'a']):
        for attr in ['src', 'href']:
            val = tag.get(attr)
            if not val:
                continue
            full = _normalize(val, base_url)
            lower = full.lower()
            if '.m3u8' in lower or '.mp4' in lower:
                found_video.append(full)
            if any(ext in lower for ext in ['.vtt', '.srt', '.ass']):
                found_subs.append({'url': full, 'lang': _guess_lang(str(tag)), 'label': tag.get('label', '')})

    for patterns, bucket in [(M3U8_PATTERNS + VIDEO_PATTERNS, found_video), (SUB_PATTERNS, found_subs)]:
        for pat in patterns:
            for match in re.findall(pat, html, flags=re.I):
                val = match if isinstance(match, str) else match[0]
                full = _normalize(val, base_url)
                if bucket is found_video:
                    bucket.append(full)
                else:
                    bucket.append({'url': full, 'lang': _guess_lang(full), 'label': ''})

    iframes = []
    for iframe in soup.find_all('iframe'):
        src = iframe.get('src')
        if src:
            iframes.append(_normalize(src, base_url))

    dedup_video = []
    seen = set()
    for url in found_video:
        if url not in seen:
            seen.add(url)
            dedup_video.append(url)

    dedup_subs = []
    seen = set()
    for sub in found_subs:
        if sub['url'] not in seen:
            seen.add(sub['url'])
            dedup_subs.append(sub)

    return dedup_video, dedup_subs, iframes


def extract_sources(url, cookie_path=None, max_iframe_depth=1):
    session = _make_session(cookie_path)
    errors = []

    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    html = resp.text

    videos, subtitles, iframes = _collect_from_html(html, url)

    depth = 0
    while not videos and iframes and depth < max_iframe_depth:
        next_iframes = []
        for iframe_url in iframes:
            try:
                iresp = session.get(iframe_url, timeout=30)
                iresp.raise_for_status()
                v2, s2, sub_iframes = _collect_from_html(iresp.text, iframe_url)
                videos.extend(v2)
                subtitles.extend(s2)
                next_iframes.extend(sub_iframes)
            except Exception as exc:  # pragma: no cover
                errors.append(f'iframe fetch failed: {iframe_url} -> {exc}')
        iframes = next_iframes
        depth += 1

    chosen_video = ''
    for candidate in videos:
        if '.m3u8' in candidate.lower():
            chosen_video = candidate
            break
    if not chosen_video and videos:
        chosen_video = videos[0]

    return {
        'm3u8_url': chosen_video,
        'video_url': chosen_video,
        'subtitles': subtitles,
        'errors': errors,
    }
