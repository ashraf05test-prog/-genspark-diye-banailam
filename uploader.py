import asyncio
import os

from pyrogram import Client


def upload_to_telegram(file_path, title, caption, progress_callback=None):
    if os.environ.get('MOCK_TELEGRAM_UPLOAD') == '1':
        if progress_callback:
            progress_callback(100)
        return 'https://t.me/mock_channel/123'

    api_id = os.environ.get('TG_API_ID')
    api_hash = os.environ.get('TG_API_HASH')
    bot_token = os.environ.get('TG_BOT_TOKEN')
    chat_id = os.environ.get('TG_CHAT_ID')

    if not all([api_id, api_hash, bot_token, chat_id]):
        raise RuntimeError('Missing TG_API_ID / TG_API_HASH / TG_BOT_TOKEN / TG_CHAT_ID')

    # chat_id numeric হলে int এ convert করো
    try:
        chat_id = int(chat_id)
    except (ValueError, TypeError):
        pass  # username string হলে এমনিই থাকবে

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        async def _upload():
            async with Client(
                'anisub_bot',
                api_id=int(api_id),
                api_hash=api_hash,
                bot_token=bot_token,
                in_memory=True,
            ) as app:
                def _progress(current, total):
                    if progress_callback and total:
                        progress_callback(int(current / total * 100))

                caption_text = f'**{title}**\n\n{caption}'.strip() if caption else f'**{title}**'

                msg = await app.send_video(
                    chat_id=chat_id,
                    video=file_path,
                    caption=caption_text,
                    supports_streaming=True,
                    progress=_progress,
                )
                return msg.link

        return loop.run_until_complete(_upload())
    finally:
        loop.close()
