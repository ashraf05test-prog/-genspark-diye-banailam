import os

import requests


FB_GRAPH_BASE = 'https://graph.facebook.com/v25.0'


def upload_to_facebook(file_path, title, caption, page_id, page_access_token, progress_callback=None):
    if os.environ.get('MOCK_FACEBOOK_UPLOAD') == '1':
        if progress_callback:
            progress_callback(100)
        return f'https://www.facebook.com/{page_id}/videos/mock_video_id'

    description = f'{title}\n\n{caption}'.strip() if caption else title
    url = f'{FB_GRAPH_BASE}/{page_id}/videos'
    file_size = os.path.getsize(file_path)

    start_resp = requests.post(
        url,
        data={
            'upload_phase': 'start',
            'file_size': file_size,
            'access_token': page_access_token,
        },
        timeout=120,
    )
    start_resp.raise_for_status()
    start_data = start_resp.json()
    upload_session_id = start_data.get('upload_session_id')
    video_id = start_data.get('video_id')
    start_offset = int(start_data.get('start_offset', 0))
    if not upload_session_id:
        raise RuntimeError(f'Facebook did not return upload_session_id: {start_data}')

    chunk_size = 8 * 1024 * 1024
    with open(file_path, 'rb') as f:
        while start_offset < file_size:
            f.seek(start_offset)
            chunk = f.read(chunk_size)
            if not chunk:
                break
            transfer_resp = requests.post(
                url,
                data={
                    'upload_phase': 'transfer',
                    'upload_session_id': upload_session_id,
                    'start_offset': start_offset,
                    'access_token': page_access_token,
                },
                files={'video_file_chunk': ('chunk.mp4', chunk, 'video/mp4')},
                timeout=300,
            )
            transfer_resp.raise_for_status()
            transfer_data = transfer_resp.json()
            start_offset = int(transfer_data.get('start_offset', start_offset + len(chunk)))
            if progress_callback:
                progress_callback(min(int((start_offset / file_size) * 100), 100))

    finish_resp = requests.post(
        url,
        data={
            'upload_phase': 'finish',
            'upload_session_id': upload_session_id,
            'access_token': page_access_token,
            'title': title,
            'description': description,
            'published': 'true',
        },
        timeout=120,
    )
    finish_resp.raise_for_status()
    finish_data = finish_resp.json()
    video_id = video_id or finish_data.get('video_id') or finish_data.get('id')
    if not video_id:
        raise RuntimeError(f'Facebook did not return video_id: {finish_data}')
    return f'https://www.facebook.com/{page_id}/videos/{video_id}'
