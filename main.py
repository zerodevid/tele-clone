import json
import os
import asyncio
import datetime
from pathlib import Path
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError


def load_dotenv_file(path: str = ".env"):
    """Minimal .env loader to keep dependencies light."""
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Environment variable {name} is required.")
    return value


def require_int_env(name: str) -> int:
    value = require_env(name)
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer.") from exc


load_dotenv_file()

# ---------------------------------------------------------
# CONFIG SESSION
# ---------------------------------------------------------
RECEIVER_API_ID = require_int_env("RECEIVER_API_ID")
RECEIVER_API_HASH = require_env("RECEIVER_API_HASH")

# Ganti dengan API ID/hash milik akun kedua (pengirim)
SENDER_API_ID = require_int_env("SENDER_API_ID")
SENDER_API_HASH = require_env("SENDER_API_HASH")

if not SENDER_API_ID or not SENDER_API_HASH:
    raise ValueError("Isi SENDER_API_ID dan SENDER_API_HASH dengan credential API akun pengirim.")

# if RECEIVER_API_ID == SENDER_API_ID and RECEIVER_API_HASH == SENDER_API_HASH:
#     raise ValueError("Receiver dan sender harus memakai API ID/HASH yang berbeda.")

RECEIVER_SESSION = "user_receiver"
SENDER_SESSION = "sender_session"

SOURCE_CHANNEL = require_int_env("SOURCE_CHANNEL_ID")
TARGET_CHANNEL = require_int_env("TARGET_CHANNEL_ID")

START_DATE = datetime.datetime(2025, 12, 1)

QUEUE_DIR = Path("message_queue")
DOWNLOAD_DIR = Path("downloads")
CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096

QUEUE_DIR.mkdir(exist_ok=True)
DOWNLOAD_DIR.mkdir(exist_ok=True)

LAST_ID_FILE = "last_id.json"
MESSAGE_MAP_FILE = "message_map.json"

# ---------------------------------------------------------
# LOAD/SAVE DATA
# ---------------------------------------------------------
def load_last_id():
    if os.path.exists(LAST_ID_FILE):
        try:
            return json.load(open(LAST_ID_FILE)).get("last_message_id", 0)
        except Exception:
            return 0
    return 0

def save_last_id(mid):
    json.dump({"last_message_id": mid}, open(LAST_ID_FILE, "w"))

def load_message_map():
    if os.path.exists(MESSAGE_MAP_FILE):
        try:
            return json.load(open(MESSAGE_MAP_FILE))
        except Exception:
            return {}
    return {}

def save_message_map(data):
    json.dump(data, open(MESSAGE_MAP_FILE, "w"))

def split_text(text, limit):
    """Split text into chunks that respect Telegram limits."""
    if not text:
        return []
    return [text[i:i + limit] for i in range(0, len(text), limit)]

def detect_media_type(msg):
    """Identify media type for better resend behavior."""
    if getattr(msg, "photo", None):
        return "photo"

    video = getattr(msg, "video", None)
    if video:
        return "video"

    document = getattr(msg, "document", None)
    if document:
        mime = getattr(document, "mime_type", "") or ""
        if mime.startswith("video/"):
            return "video"
        if mime.startswith("image/"):
            return "photo"
        if mime.startswith("audio/"):
            return "audio"
        return "document"

    if getattr(msg, "audio", None):
        return "audio"

    if getattr(msg, "voice", None):
        return "voice"

    return None

def extract_reply_to_id(msg):
    """Handle reply resolution for groups/channel threads."""
    if msg.reply_to_msg_id:
        return msg.reply_to_msg_id

    header = getattr(msg, "reply_to", None)
    if header:
        return (
            getattr(header, "reply_to_msg_id", None)
            or getattr(header, "reply_to_top_id", None)
        )
    return None

async def resolve_sender_name(msg):
    """Return readable sender/post author info for groups."""
    if msg.post_author:
        return msg.post_author

    try:
        sender = await msg.get_sender()
    except Exception:
        sender = None

    if not sender:
        return None

    full_name_parts = [
        part for part in (getattr(sender, "first_name", None), getattr(sender, "last_name", None))
        if part
    ]
    full_name = " ".join(full_name_parts).strip()
    username = getattr(sender, "username", None)

    if full_name and username:
        return f"{full_name} (@{username})"
    if full_name:
        return full_name
    if username:
        return f"@{username}"

    return str(getattr(sender, "id", None)) if getattr(sender, "id", None) else None

# ---------------------------------------------------------
# INIT CLIENTS (gunakan credential berbeda)
# ---------------------------------------------------------
receiver = TelegramClient(RECEIVER_SESSION, RECEIVER_API_ID, RECEIVER_API_HASH)
sender = TelegramClient(SENDER_SESSION, SENDER_API_ID, SENDER_API_HASH)

# ---------------------------------------------------------
# SAVE MESSAGE TO QUEUE
# ---------------------------------------------------------
async def save_to_queue(msg, local_file=None):
    reply_to_id = extract_reply_to_id(msg)
    author_name = await resolve_sender_name(msg)
    media_type = detect_media_type(msg)

    data = {
        "msg_id": msg.id,
        "text": msg.text or msg.message,
        "reply_to": reply_to_id,
        "post_author": author_name,
        "fwd_info": None,
        "media_path": local_file,
        "media_type": media_type
    }

    if msg.fwd_from:
        if msg.fwd_from.from_name:
            data["fwd_info"] = msg.fwd_from.from_name
        elif msg.fwd_from.from_id:
            data["fwd_info"] = str(msg.fwd_from.from_id)

    queue_file = QUEUE_DIR / f"{msg.id}.json"
    json.dump(data, open(queue_file, "w"))
    print(f"📥 QUEUE: {queue_file}")

# ---------------------------------------------------------
# RECEIVER: PROCESS MESSAGE (download + queue)
# ---------------------------------------------------------
async def process_message(msg):
    local_file = None
    if msg.media:
        try:
            print(f"⬇️ Downloading media: {msg.id}")
            local_file = await msg.download_media(DOWNLOAD_DIR)
        except Exception as e:
            print(f"⚠️ Gagal download media {msg.id}: {e}")
            local_file = None

    await save_to_queue(msg, local_file)
    save_last_id(msg.id)

# ---------------------------------------------------------
# RECEIVER: CATCH UP OLD MESSAGES
# ---------------------------------------------------------
async def catch_up_receiver():
    last_id = load_last_id()
    entity = await receiver.get_entity(SOURCE_CHANNEL)

    if last_id > 0:
        print(f"⏪ Continue from ID {last_id}")
        # FIX: tambahkan reverse=True supaya urut dari lama ke baru
        async for msg in receiver.iter_messages(entity, min_id=last_id, reverse=True):
            await process_message(msg)
    else:
        print(f"📅 First run since: {START_DATE}")
        # Di first run memang sudah reverse=True (lama ke baru)
        async for msg in receiver.iter_messages(entity, offset_date=START_DATE, reverse=True):
            await process_message(msg)

# ---------------------------------------------------------
# RECEIVER HANDLER (LIVE FORWARD)
# ---------------------------------------------------------
@receiver.on(events.NewMessage(chats=SOURCE_CHANNEL))
async def receiver_handler(event):
    await process_message(event.message)

# ---------------------------------------------------------
# SENDER: SEND FROM QUEUE
# ---------------------------------------------------------
async def send_from_queue():
    print("🚀 Sender started")
    message_map = load_message_map()

    while True:
        queue_files = list(QUEUE_DIR.glob("*.json"))

        if not queue_files:
            await asyncio.sleep(2)
            continue

        # FIX: urutkan berdasarkan numeric msg_id dari nama file
        try:
            queue_files = sorted(
                queue_files,
                key=lambda p: int(p.stem)  # "12345.json" → 12345
            )
        except ValueError:
            # fallback kalau ada file aneh
            queue_files = sorted(queue_files, key=lambda p: p.stat().st_mtime)

        for q in queue_files:
            try:
                data = json.load(open(q))
            except Exception as e:
                print(f"⚠️ Gagal baca queue file {q}: {e}")
                os.remove(q)
                continue

            msg_id = data["msg_id"]
            reply_to = None

            # map reply id
            if data["reply_to"]:
                orig = str(data["reply_to"])
                if orig in message_map:
                    reply_to = message_map[orig]

            # prepare final text
            author = f"\n\n✍️ : {data['post_author']}" if data["post_author"] else ""
            forwarded = f"\n🔁 Diteruskan dari: {data['fwd_info']}" if data["fwd_info"] else ""
            caption = ((data["text"] or "") + author + forwarded).rstrip("\n")

            try:
                primary_sent = None
                last_sent = None

                # send media or text
                if data["media_path"]:
                    media_type = data.get("media_type")
                    is_photo = media_type == "photo"
                    is_video = media_type == "video"
                    force_document = not (is_photo or is_video)

                    caption_chunks = split_text(caption, CAPTION_LIMIT)
                    media_caption = caption_chunks[0] if caption_chunks else ""

                    sent = await sender.send_file(
                        TARGET_CHANNEL,
                        data["media_path"],
                        caption=media_caption,
                        reply_to=reply_to,
                        force_document=force_document,
                        supports_streaming=is_video
                    )
                    primary_sent = sent
                    last_sent = sent

                    remaining_text = caption[len(media_caption):] if caption else ""
                    if remaining_text.strip():
                        for chunk in split_text(remaining_text, TEXT_LIMIT):
                            sent_extra = await sender.send_message(
                                TARGET_CHANNEL,
                                chunk,
                                reply_to=primary_sent.id,
                                link_preview=True
                            )
                            last_sent = sent_extra
                else:
                    text_body = caption if caption.strip() else ""
                    if not text_body:
                        text_body = f"[Pesan kosong/tidak didukung - ID {msg_id}]"

                    text_chunks = split_text(text_body, TEXT_LIMIT) or [text_body]

                    for idx, chunk in enumerate(text_chunks):
                        current_reply = reply_to if idx == 0 else primary_sent.id
                        sent_msg = await sender.send_message(
                            TARGET_CHANNEL,
                            chunk,
                            reply_to=current_reply,
                            link_preview=True
                        )
                        if primary_sent is None:
                            primary_sent = sent_msg
                        last_sent = sent_msg

                if not primary_sent:
                    raise RuntimeError("Gagal mengirim pesan: tidak ada message yang dikirim.")

                message_map[str(msg_id)] = primary_sent.id
                save_message_map(message_map)

                print(f"✅ SENT: {msg_id} → {last_sent.id}")

                # remove local media after successful send
                if data.get("media_path") and os.path.exists(data["media_path"]):
                    try:
                        os.remove(data["media_path"])
                        print(f"🧹 Deleted media: {data['media_path']}")
                    except OSError as err:
                        print(f"⚠️ Gagal hapus media {data['media_path']}: {err}")
            except Exception as e:
                if isinstance(e, FloodWaitError):
                    wait_time = max(int(getattr(e, "seconds", 5)) + 1, 5)
                    print(f"⏳ Flood wait {wait_time}s untuk pesan {msg_id}: {e}")
                    await asyncio.sleep(wait_time)
                    continue

                print(f"❌ Gagal kirim pesan {msg_id}: {e}")
                # kalau error, jangan hapus file dulu, biar bisa coba lagi nanti
                await asyncio.sleep(2)
                continue

            # kalau sukses kirim → hapus queue
            os.remove(q)

# ---------------------------------------------------------
# MAIN: RUN BOTH SESSION IN PARALLEL
# ---------------------------------------------------------
async def main():
    await receiver.start()
    await sender.start()

    # catch up old messages but allow sender to drain queue simultaneously
    catch_up_task = asyncio.create_task(catch_up_receiver())

    print("🚀 Both sessions running...")

    await asyncio.gather(
        receiver.run_until_disconnected(),
        send_from_queue(),
        catch_up_task
    )

asyncio.get_event_loop().run_until_complete(main())
