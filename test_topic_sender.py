import argparse
import asyncio
import json
import os
from pathlib import Path

from telethon import TelegramClient


def load_dotenv_file(path: str = ".env"):
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
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
        raise ValueError(f"{name} must be an integer.") from exc


def load_receivers_config(path: str = "receivers.json"):
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Tidak menemukan {cfg_path}.")

    try:
        data = json.load(open(cfg_path))
    except json.JSONDecodeError as exc:
        raise ValueError(f"receivers.json invalid: {exc}") from exc

    if not isinstance(data, list) or not data:
        raise ValueError("receivers.json harus berupa list minimal 1 receiver.")
    return data


async def send_test_message(receiver_name: str, message: str):
    load_dotenv_file()

    sender_api_id = require_int_env("SENDER_API_ID")
    sender_api_hash = require_env("SENDER_API_HASH")
    sender_session = os.getenv("SENDER_SESSION_NAME", "sender_session")
    default_target = require_int_env("TARGET_CHANNEL_ID")

    receivers = load_receivers_config()
    selected = next((item for item in receivers if item.get("name") == receiver_name), None)
    if not selected:
        raise ValueError(f"Tidak menemukan receiver bernama '{receiver_name}'.")

    topic_id = selected.get("topic_id")
    if topic_id is None:
        raise ValueError(f"Receiver '{receiver_name}' tidak memiliki topic_id.")

    try:
        topic_id = int(topic_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"topic_id receiver '{receiver_name}' harus integer.") from exc

    target_channel = selected.get("target_channel_id", default_target)
    try:
        target_channel = int(target_channel)
    except (TypeError, ValueError) as exc:
        raise ValueError("target_channel_id harus integer.") from exc

    client = TelegramClient(sender_session, sender_api_id, sender_api_hash)
    await client.start()

    try:
        sent = await client.send_message(
            target_channel,
            message,
            reply_to=topic_id,
            link_preview=False
        )
        print(f"✅ Test message terkirim ke {target_channel} (topic {topic_id}) → ID {sent.id}")
    finally:
        await client.disconnect()


def main():
    parser = argparse.ArgumentParser(
        description="Kirim pesan test ke channel target dengan topic ID sesuai receiver."
    )
    parser.add_argument(
        "-r", "--receiver",
        required=True,
        help="Nama receiver di receivers.json yang ingin diuji."
    )
    parser.add_argument(
        "-m", "--message",
        default="Test pesan dari test_topic_sender.py",
        help="Pesan yang akan dikirim."
    )
    args = parser.parse_args()

    asyncio.run(send_test_message(args.receiver, args.message))


if __name__ == "__main__":
    main()
