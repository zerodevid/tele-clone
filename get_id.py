import json
from pathlib import Path
from telethon import TelegramClient, events

API_ID = 39140065
API_HASH = '929779a46119c86a7f74f7c4c6ddabd3'

client = TelegramClient("akun_rozi_rizky", API_ID, API_HASH)
SOURCE_CHANNEL = None  # tidak tahu di awal
SOURCE_CHANNEL_FILE = Path("source_channel.json")
GROUP_LIST_FILE = Path("group_list.json")

async def export_group_list():
    groups = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        is_group = dialog.is_group
        is_megagroup = dialog.is_channel and getattr(entity, "megagroup", False)

        if not (is_group or is_megagroup):
            continue

        groups.append({
            "name": dialog.name,
            "chat_id": dialog.id
        })

    GROUP_LIST_FILE.write_text(json.dumps(groups, indent=2))
    print(f"📝 Saved {len(groups)} groups to {GROUP_LIST_FILE.name}")

@client.on(events.NewMessage())
async def detect_handler(event):
    global SOURCE_CHANNEL

    msg = event.message
    chat_id = msg.chat_id

    # kalau pesan dari PM, bot, atau channel yang tidak ingin kamu gunakan → skip
    if chat_id > 0:
        return  

    if SOURCE_CHANNEL is None:
        SOURCE_CHANNEL = chat_id
        print("🎯 Detected SOURCE_CHANNEL:", SOURCE_CHANNEL)

        # simpan ke file biar permanen
        SOURCE_CHANNEL_FILE.write_text(str(SOURCE_CHANNEL))

    print(f"📩 New message from {chat_id}: {msg.text}")

async def main():
    await client.start()
    await export_group_list()
    print("✅ Group list exported. Listening for new messages...")
    await client.run_until_disconnected()

client.loop.run_until_complete(main())
