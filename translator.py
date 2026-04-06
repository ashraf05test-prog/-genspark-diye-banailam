import json
import os
import re
import time

import requests
from deep_translator import GoogleTranslator

try:
    import google.generativeai as genai
except Exception:  # pragma: no cover
    genai = None


XAI_API_BASE = 'https://api.x.ai'


def convert_vtt_to_srt(vtt_text: str) -> str:
    lines = vtt_text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    out = []
    index = 1
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line == 'WEBVTT' or line.startswith('NOTE') or line.startswith('Kind:') or line.startswith('Language:'):
            i += 1
            continue
        if '-->' in line:
            out.append(str(index))
            out.append(line.replace('.', ','))
            i += 1
            text_buf = []
            while i < len(lines) and lines[i].strip():
                cleaned = re.sub(r'<[^>]+>', '', lines[i]).strip()
                if cleaned:
                    text_buf.append(cleaned)
                i += 1
            out.append('\n'.join(text_buf))
            out.append('')
            index += 1
        else:
            i += 1
    return '\n'.join(out)


def parse_srt(srt_text: str):
    blocks = re.split(r'\n\s*\n', srt_text.strip(), flags=re.M)
    items = []
    for block in blocks:
        lines = [x.rstrip() for x in block.splitlines() if x.strip()]
        if len(lines) < 3:
            continue
        if re.fullmatch(r'\d+', lines[0].strip()):
            idx = lines[0].strip()
            times = lines[1].strip()
            text = '\n'.join(lines[2:]).strip()
        else:
            idx = ''
            times = lines[0].strip()
            text = '\n'.join(lines[1:]).strip()
        items.append({'index': idx, 'times': times, 'text': text})
    return items


def build_srt(items):
    chunks = []
    for n, item in enumerate(items, start=1):
        idx = item.get('index') or str(n)
        chunks.append(f"{idx}\n{item['times']}\n{item['text']}")
    return '\n\n'.join(chunks) + '\n'


def _clean(text: str) -> str:
    text = re.sub(r'<[^>]+>', '', text or '')
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _parse_json_array(text: str):
    text = text.strip()
    text = re.sub(r'^```json\s*', '', text)
    text = re.sub(r'^```\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError('Expected JSON array')
    return data


def translate_google(lines, target_lang='bn'):
    translator = GoogleTranslator(source='auto', target=target_lang)
    output = []
    for line in lines:
        clean = _clean(line)
        if not clean:
            output.append('')
            continue
        try:
            output.append(translator.translate(clean))
        except Exception:
            output.append(clean)
    return output


def translate_gemini(lines, api_key, model='gemini-1.5-flash'):
    if not api_key:
        raise ValueError('Missing Gemini API key')
    if genai is None:
        raise RuntimeError('google-generativeai not available')
    genai.configure(api_key=api_key)
    model_obj = genai.GenerativeModel(model)
    numbered = '\n'.join(f'{i+1}. {_clean(x)}' for i, x in enumerate(lines))
    prompt = (
        'You are a professional anime subtitle translator. Translate English subtitle lines into natural Bangla. '
        'Return ONLY a valid JSON array of strings with exactly the same number of items. '
        'Use proper Bengali script, preserve tone, and do not add explanations.\n\n'
        f'Lines:\n{numbered}'
    )
    resp = model_obj.generate_content(prompt)
    data = _parse_json_array((resp.text or '').strip())
    if len(data) != len(lines):
        raise ValueError('Gemini returned wrong number of lines')
    return [str(x).strip() for x in data]


def translate_grok(lines, api_key, model='grok-3-mini-fast', timeout=90):
    if not api_key:
        raise ValueError('Missing Grok API key')
    numbered = '\n'.join(f'{i+1}. {_clean(x)}' for i, x in enumerate(lines))
    system_prompt = (
        'You are a professional anime subtitle translator. Translate English subtitle lines into natural Bangla. '
        'Return ONLY a valid JSON array of strings in the same order and same count.'
    )
    user_prompt = (
        'Translate the following subtitle lines into Bangla. Use proper conjunct letters and natural wording. '\
        'No explanations. JSON array only.\n\n'
        f'{numbered}'
    )
    response = requests.post(
        f'{XAI_API_BASE}/v1/chat/completions',
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        json={
            'model': model,
            'temperature': 0.2,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    content = data['choices'][0]['message']['content']
    parsed = _parse_json_array(content)
    if len(parsed) != len(lines):
        raise ValueError('Grok returned wrong number of lines')
    return [str(x).strip() for x in parsed]


def translate_srt_text(srt_text: str, gemini_api_key=None, grok_api_key=None, batch_size=20, sleep_sec=0.2):
    items = parse_srt(srt_text)
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        src_lines = [x['text'] for x in batch]
        translated = None
        if gemini_api_key:
            try:
                translated = translate_gemini(src_lines, gemini_api_key)
            except Exception:
                translated = None
        if translated is None and grok_api_key:
            try:
                translated = translate_grok(src_lines, grok_api_key)
            except Exception:
                translated = None
        if translated is None:
            translated = translate_google(src_lines)
        for item, line in zip(batch, translated):
            item['text'] = line
        time.sleep(sleep_sec)
    return build_srt(items)
