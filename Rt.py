import asyncio
import logging
import os
import re
import requests
import httpx
from pyrogram import Client, filters
from pyrogram.types import Message

# ============================
BOT_TOKEN = "8038919105:AAE2Rw9KcING0I3Q4jOTw5FwwxaZmqy4ivs"
API_ID = 24461319
API_HASH = "bfee9f2d599eb92dbe32867e20538140"
# ============================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TERABOX_API = "https://terabox.anshapi.workers.dev/api/terabox-down?url="
MAX_SIZE = 1 * 1024 * 1024 * 1024  # 1 GB

app = Client("Box", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


def format_size(size_bytes):
    if size_bytes >= 1024**3:
        return f"{size_bytes / 1024**3:.2f} GB"
    elif size_bytes >= 1024**2:
        return f"{size_bytes / 1024**2:.2f} MB"
    else:
        return f"{size_bytes / 1024:.2f} KB"


async def download_file_async(url, path, status_msg):
    """Async stream download with progress"""
    async with httpx.AsyncClient(timeout=600, follow_redirects=True) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            downloaded = 0
            last_percent = -10

            with open(path, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            percent = int(downloaded / total * 100)
                            if percent - last_percent >= 10:
                                last_percent = percent
                                bars = "▓" * (percent // 10) + "░" * (10 - percent // 10)
                                try:
                                    await status_msg.edit_text(
                                        f"📥 Downloading...\n"
                                        f"{format_size(downloaded)} / {format_size(total)}\n\n"
                                        f"{bars} {percent}%"
                                    )
                                except Exception:
                                    pass
    return downloaded


@app.on_message(filters.command("start"))
async def start(client, message: Message):
    await message.reply_text(
        "👋 **TeraBox Video Downloader Bot**\n\n"
        "📌 **Kaise use karein:**\n"
        "TeraBox ya TerashareLink ka link bhejo\n"
        "Main video download karke dunga! ✅\n\n"
        "📦 **Supported size:** Up to 1 GB\n\n"
        "Example:\n`https://terasharelink.com/s/xxxxxx`"
    )


@app.on_message(filters.text & ~filters.command(["start"]))
async def handle_link(client, message: Message):
    user_message = message.text.strip()

    if "terabox" not in user_message.lower() and "terashare" not in user_message.lower():
        await message.reply_text("❌ Please ek valid TeraBox ya TerashareLink bhejo!")
        return

    status_msg = await message.reply_text("⏳ Link process ho raha hai...")

    temp_path = None
    try:
        # Call API
        api_url = TERABOX_API + user_message
        response = requests.get(api_url, timeout=30)
        data = response.json()
        logger.info(f"API Response: {data}")

        # Extract download URL
        download_url = None
        filename_from_api = None
        file_size_from_api = 0

        try:
            file_info = data["data"]["list"][0]
            download_url = file_info.get("direct_link") or file_info.get("dlink")
            filename_from_api = file_info.get("server_filename", "")
            file_size_from_api = int(file_info.get("size", 0))
            logger.info(f"URL: {download_url}, File: {filename_from_api}, Size: {file_size_from_api}")
        except (KeyError, IndexError, TypeError) as e:
            logger.warning(f"Fallback parsing: {e}")
            if isinstance(data, dict):
                download_url = (
                    data.get("direct_link") or data.get("dlink") or
                    data.get("download_url") or data.get("url")
                )
                if not download_url and "data" in data:
                    inner = data["data"]
                    if isinstance(inner, dict):
                        download_url = (
                            inner.get("direct_link") or inner.get("dlink") or
                            inner.get("download_url") or inner.get("url")
                        )

        if not download_url:
            await status_msg.edit_text(
                f"⚠️ Download link nahi mila!\n\nAPI Response:\n`{str(data)[:500]}`"
            )
            return

        # File size
        file_size = file_size_from_api
        if file_size == 0:
            try:
                head = requests.head(download_url, timeout=15, allow_redirects=True)
                file_size = int(head.headers.get("content-length", 0))
            except Exception:
                pass

        if file_size > MAX_SIZE:
            await status_msg.edit_text(
                f"❌ File bahut badi hai!\n"
                f"Size: **{format_size(file_size)}**\n"
                f"Max allowed: **1 GB**\n\n"
                f"📎 Direct link:\n{download_url}"
            )
            return

        size_text = format_size(file_size) if file_size else "Unknown"
        await status_msg.edit_text(f"📥 Download shuru ho rahi hai...\nSize: {size_text}")

        # Filename
        filename = filename_from_api or ""
        if not filename:
            filename = download_url.split("/")[-1].split("?")[0] or "video.mp4"
        if "." not in filename:
            filename += ".mp4"
        filename = re.sub(r"[^\w\s\-_\.]", "_", filename).strip() or "video.mp4"

        temp_path = f"/tmp/{filename}"

        # Download (async)
        await download_file_async(download_url, temp_path, status_msg)

        actual_size = os.path.getsize(temp_path)
        await status_msg.edit_text(
            f"📤 Uploading to Telegram...\n"
            f"Size: **{format_size(actual_size)}**\n\n"
            f"▓▓▓▓▓▓▓▓▓▓ Please wait..."
        )

        # Upload progress
        last_up_percent = [-10]

        async def upload_progress(current, total):
            percent = int(current / total * 100)
            if percent - last_up_percent[0] >= 10:
                last_up_percent[0] = percent
                bars = "▓" * (percent // 10) + "░" * (10 - percent // 10)
                try:
                    await status_msg.edit_text(
                        f"📤 Uploading...\n"
                        f"{format_size(current)} / {format_size(total)}\n\n"
                        f"{bars} {percent}%"
                    )
                except Exception:
                    pass

        # Send video
        await message.reply_video(
            video=temp_path,
            caption=f"🎬 {filename}",
            supports_streaming=True,
            progress=upload_progress
        )

        await status_msg.delete()

    except requests.exceptions.Timeout:
        await status_msg.edit_text("⏰ Request timeout ho gayi! Dobara try karo.")
    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit_text(f"❌ Error aa gaya:\n`{str(e)}`")
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


if __name__ == "__main__":
    print("🤖 Bot chal raha hai... (1GB support enabled)")
    app.run()
