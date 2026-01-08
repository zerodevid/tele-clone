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
SENDER_API_ID = require_int_env("SENDER_API_ID")
SENDER_API_HASH = require_env("SENDER_API_HASH")
SENDER_SESSION = os.getenv("SENDER_SESSION_NAME", "sender_session")

TARGET_CHANNEL = require_int_env("TARGET_CHANNEL_ID")

DEFAULT_START_DATE = datetime.datetime(2025, 12, 1)

QUEUE_DIR = Path("message_queue")
DOWNLOAD_DIR = Path("downloads")
CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096

QUEUE_DIR.mkdir(exist_ok=True)
DOWNLOAD_DIR.mkdir(exist_ok=True)

LAST_ID_FILE = "last_id.json"
MESSAGE_MAP_FILE = "message_map.json"
RECEIVERS_CONFIG_FILE = Path("receivers.json")


def parse_start_date(raw_value, receiver_name):
    if raw_value in (None, "", "null"):
        return DEFAULT_START_DATE
    if isinstance(raw_value, (int, float)):
        return datetime.datetime.fromtimestamp(raw_value)
    if isinstance(raw_value, str):
        try:
            return datetime.datetime.fromisoformat(raw_value)
        except ValueError as exc:
            raise ValueError(
                f"Invalid start_date for receiver {receiver_name}. Use ISO format YYYY-MM-DD."
            ) from exc
    raise ValueError(f"start_date for receiver {receiver_name} must be string or timestamp.")


def parse_optional_int(raw_value, field_name, receiver_name):
    if raw_value in (None, "", "null"):
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} untuk receiver {receiver_name} harus berupa integer."
        ) from exc


def load_receivers_config():
    if not RECEIVERS_CONFIG_FILE.exists():
        raise FileNotFoundError(f"Tidak menemukan {RECEIVERS_CONFIG_FILE}.")

    try:
        data = json.load(open(RECEIVERS_CONFIG_FILE))
    except json.JSONDecodeError as exc:
        raise ValueError(f"receivers.json invalid: {exc}") from exc

    if not isinstance(data, list) or not data:
        raise ValueError("receivers.json harus berupa list minimal 1 receiver.")

    normalized = []
    for entry in data:
        name = entry.get("name")
        session = entry.get("session")
        api_id = entry.get("api_id")
        api_hash = entry.get("api_hash")
        source_channel = entry.get("source_channel")
        target_topic_id = entry.get("target_topic_id", entry.get("topic_id"))
        source_topic_id = entry.get("source_topic_id")
        target_channel_override = entry.get("target_channel_id")

        if not all([name, session, api_id, api_hash, source_channel, target_topic_id]):
            raise ValueError(f"Receiver config tidak lengkap: {entry}")

        normalized.append(
            {
                "name": str(name),
                "session": str(session),
                "api_id": int(api_id),
                "api_hash": str(api_hash),
                "source_channel": int(source_channel),
                "target_topic_id": int(target_topic_id),
                "source_topic_id": parse_optional_int(source_topic_id, "source_topic_id", name),
                "target_channel": int(target_channel_override)
                if target_channel_override
                else TARGET_CHANNEL,
                "start_date": parse_start_date(entry.get("start_date"), name),
            }
        )

    return normalized


def load_last_id_map():
    if os.path.exists(LAST_ID_FILE):
        try:
            data = json.load(open(LAST_ID_FILE))
        except Exception:
            return {}

        if isinstance(data, dict):
            if "last_message_id" in data and len(data) == 1:
                return {"default": data["last_message_id"]}
            return data

        if isinstance(data, (int, float)):
            return {"default": int(data)}

    return {}


def load_last_id(receiver_name):
    return int(load_last_id_map().get(receiver_name, 0))


def save_last_id(receiver_name, mid):
    data = load_last_id_map()
    data[receiver_name] = mid
    json.dump(data, open(LAST_ID_FILE, "w"))

# ---------------------------------------------------------
# LOAD/SAVE DATA
# ---------------------------------------------------------
def load_message_map():
    if os.path.exists(MESSAGE_MAP_FILE):
        try:
            return json.load(open(MESSAGE_MAP_FILE))
        except Exception:
            return {}
    return {}

def save_message_map(data):
    json.dump(data, open(MESSAGE_MAP_FILE, "w"))


def map_key(receiver_name, msg_id):
    return f"{receiver_name}:{msg_id}"


receiver_configs = load_receivers_config()
receiver_sessions = {}

for conf in receiver_configs:
    session_name = conf["session"]
    session_entry = receiver_sessions.get(session_name)
    if not session_entry:
        client = TelegramClient(session_name, conf["api_id"], conf["api_hash"])
        session_entry = {
            "client": client,
            "api_id": conf["api_id"],
            "api_hash": conf["api_hash"],
            "configs": []
        }
        receiver_sessions[session_name] = session_entry
    else:
        if session_entry["api_id"] != conf["api_id"] or session_entry["api_hash"] != conf["api_hash"]:
            raise ValueError(
                f"Session {session_name} dipakai beberapa API ID/hash. Harus konsisten."
            )
    session_entry["configs"].append(conf)

receiver_client_pairs = [
    (conf, session_entry["client"])
    for session_entry in receiver_sessions.values()
    for conf in session_entry["configs"]
]

sender = TelegramClient(SENDER_SESSION, SENDER_API_ID, SENDER_API_HASH)

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


def extract_topic_thread_id(msg):
    """Return topic thread ID (top message id) if message belongs to a forum topic."""
    header = getattr(msg, "reply_to", None)
    if not header:
        return None
    return (
        getattr(header, "reply_to_top_id", None)
        or getattr(header, "reply_to_msg_id", None)
    )


def message_matches_source_topic(msg, topic_id):
    """Check if message belongs to desired source topic (or allow all if None)."""
    if topic_id is None:
        return True
    topic = extract_topic_thread_id(msg)
    if topic is None:
        return False
    return topic == topic_id or msg.id == topic_id

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
# SAVE MESSAGE TO QUEUE
# ---------------------------------------------------------
async def save_to_queue(receiver_conf, msg, local_file=None):
    reply_to_id = extract_reply_to_id(msg)
    author_name = await resolve_sender_name(msg)
    media_type = detect_media_type(msg)
    receiver_name = receiver_conf["name"]
    target_channel = receiver_conf["target_channel"]

    data = {
        "msg_id": msg.id,
        "text": msg.text or msg.message,
        "reply_to": reply_to_id,
        "post_author": author_name,
        "fwd_info": None,
        "media_path": local_file,
        "media_type": media_type,
        "receiver": receiver_name,
        "target_channel_id": target_channel,
        "target_topic_id": receiver_conf["target_topic_id"],
        "source_channel_id": receiver_conf["source_channel"]
    }

    if msg.fwd_from:
        if msg.fwd_from.from_name:
            data["fwd_info"] = msg.fwd_from.from_name
        elif msg.fwd_from.from_id:
            data["fwd_info"] = str(msg.fwd_from.from_id)

    queue_file = QUEUE_DIR / f"{receiver_name}__{msg.id}.json"
    json.dump(data, open(queue_file, "w"))
    print(f"📥 QUEUE [{receiver_name}]: {queue_file}")

# ---------------------------------------------------------
# RECEIVER: PROCESS MESSAGE (download + queue)
# ---------------------------------------------------------
async def process_message(receiver_conf, msg):
    local_file = None
    if msg.media:
        try:
            print(f"⬇️ Downloading media [{receiver_conf['name']}]: {msg.id}")
            local_file = await msg.download_media(DOWNLOAD_DIR)
        except Exception as e:
            print(f"⚠️ Gagal download media {msg.id}: {e}")
            local_file = None

    await save_to_queue(receiver_conf, msg, local_file)
    save_last_id(receiver_conf["name"], msg.id)

# ---------------------------------------------------------
# RECEIVER: CATCH UP OLD MESSAGES
# ---------------------------------------------------------
async def catch_up_receiver(receiver_conf, client):
    last_id = load_last_id(receiver_conf["name"])
    entity = await client.get_entity(receiver_conf["source_channel"])
    source_topic_id = receiver_conf["source_topic_id"]

    if last_id > 0:
        print(f"[{receiver_conf['name']}] ⏪ Continue from ID {last_id}")
        async for msg in client.iter_messages(entity, min_id=last_id, reverse=True):
            if not message_matches_source_topic(msg, source_topic_id):
                continue
            await process_message(receiver_conf, msg)
    else:
        start_date = receiver_conf["start_date"]
        print(f"[{receiver_conf['name']}] 📅 First run since: {start_date}")
        async for msg in client.iter_messages(entity, offset_date=start_date, reverse=True):
            if not message_matches_source_topic(msg, source_topic_id):
                continue
            await process_message(receiver_conf, msg)

# ---------------------------------------------------------
# RECEIVER HANDLER (LIVE FORWARD)
# ---------------------------------------------------------
for session_entry in receiver_sessions.values():
    client = session_entry["client"]
    for rc_conf in session_entry["configs"]:
        @client.on(events.NewMessage(chats=rc_conf["source_channel"]))
        async def receiver_handler(event, receiver_conf=rc_conf):
            if not message_matches_source_topic(event.message, receiver_conf["source_topic_id"]):
                return
            await process_message(receiver_conf, event.message)

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

        # urutkan berdasarkan numeric msg_id dari nama file (receiver__1234.json)
        def queue_sort_key(path_obj):
            stem = path_obj.stem.rsplit("__", 1)[-1]
            try:
                return (0, int(stem))
            except ValueError:
                return (1, path_obj.stat().st_mtime)

        queue_files = sorted(queue_files, key=queue_sort_key)

        for q in queue_files:
            try:
                data = json.load(open(q))
            except Exception as e:
                print(f"⚠️ Gagal baca queue file {q}: {e}")
                os.remove(q)
                continue

            msg_id = data["msg_id"]
            receiver_name = data.get("receiver", "default")
            reply_to = None
            topic_id = data.get("target_topic_id")
            target_channel_id = data.get("target_channel_id", TARGET_CHANNEL)

            try:
                topic_id = int(topic_id) if topic_id is not None else None
            except (TypeError, ValueError):
                topic_id = None

            try:
                target_channel_id = int(target_channel_id)
            except (TypeError, ValueError):
                target_channel_id = TARGET_CHANNEL

            # map reply id
            if data["reply_to"]:
                orig = map_key(receiver_name, data["reply_to"])
                reply_to = message_map.get(orig)
                if not reply_to:
                    reply_to = message_map.get(str(data["reply_to"]))

            base_reply_target = reply_to or topic_id
            if base_reply_target is None:
                print(f"⚠️ Queue {q.name} tidak memiliki topic_id, pesan akan dikirim tanpa topic.")

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
                        target_channel_id,
                        data["media_path"],
                        caption=media_caption,
                        reply_to=base_reply_target,
                        force_document=force_document,
                        supports_streaming=is_video
                    )
                    primary_sent = sent
                    last_sent = sent

                    remaining_text = caption[len(media_caption):] if caption else ""
                    if remaining_text.strip():
                        for chunk in split_text(remaining_text, TEXT_LIMIT):
                            sent_extra = await sender.send_message(
                                target_channel_id,
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
                        current_reply = base_reply_target if idx == 0 else primary_sent.id
                        sent_msg = await sender.send_message(
                            target_channel_id,
                            chunk,
                            reply_to=current_reply,
                            link_preview=True
                        )
                        if primary_sent is None:
                            primary_sent = sent_msg
                        last_sent = sent_msg

                if not primary_sent:
                    raise RuntimeError("Gagal mengirim pesan: tidak ada message yang dikirim.")

                message_map[map_key(receiver_name, msg_id)] = primary_sent.id
                save_message_map(message_map)

                print(f"✅ SENT [{receiver_name}]: {msg_id} → {last_sent.id}")

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

                print(f"❌ Gagal kirim pesan [{receiver_name}] {msg_id}: {e}")
                # kalau error, jangan hapus file dulu, biar bisa coba lagi nanti
                await asyncio.sleep(2)
                continue

            # kalau sukses kirim → hapus queue
            os.remove(q)

# ---------------------------------------------------------
# MAIN: RUN BOTH SESSION IN PARALLEL
# ---------------------------------------------------------
async def main():
    if not receiver_client_pairs:
        raise ValueError("Minimal harus ada 1 receiver di receivers.json.")

    for session_entry in receiver_sessions.values():
        await session_entry["client"].start()

    await sender.start()

    catch_up_tasks = [
        asyncio.create_task(catch_up_receiver(rc_conf, rc_client))
        for rc_conf, rc_client in receiver_client_pairs
    ]

    receiver_loop_tasks = [
        asyncio.create_task(session_entry["client"].run_until_disconnected())
        for session_entry in receiver_sessions.values()
    ]

    print("🚀 All sessions running...")

    await asyncio.gather(
        send_from_queue(),
        *catch_up_tasks,
        *receiver_loop_tasks
    )


asyncio.run(main())
