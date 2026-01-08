# Tele Clone Forwarder

A Python-based Telegram bot system designed to forward messages from multiple source channels/groups to a single target channel/supergroup. It supports topic mapping (forums), media forwarding, and uses `Telethon` for MTProto communication.

## 📋 Features

- **Multi-Source Support**: Listen to multiple source channels simultaneously.
- **Topic Mapping**: Forward messages from specific source topics to specific destination topics (for Telegram Forums).
- **Session Management**: Supports multiple Telegram user accounts/sessions.
- **Queue System**: Handles messages in a queue to prevent flooding and ensure order.
- **ID Helper**: Includes tools to easily discover Chat IDs and Topic IDs.
- **Webhook Notifications**: Send message data to external webhooks (n8n, Zapier, Make, etc.) with Basic Auth support.

## 🛠 Prerequisites

- Python 3.8 or higher.
- Telegram API credentials (`API_ID` and `API_HASH`). You can get these from [https://my.telegram.org](https://my.telegram.org).

## 🚀 Installation

1.  **Clone the repository** (if applicable) or download the source code.
2.  **Create a virtual environment** (recommended):
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Linux/macOS
    # venv\Scripts\activate   # On Windows
    ```
3.  **Install dependencies**:
    ```bash
    pip install telethon aiohttp
    ```
    > **Note**: `aiohttp` is optional but required for webhook notifications.

## ⚙️ Configuration

### 1. Environment Variables (`.env`)
Create a `.env` file in the root directory. This configures the **SENDER** account (the account that will post the messages to your target channel).

```env
SENDER_API_ID=12345678
SENDER_API_HASH=your_api_hash_here
SENDER_SESSION_NAME=sender_session
TARGET_CHANNEL_ID=-100xxxxxxxxx
```

*   `SENDER_API_ID` / `SENDER_API_HASH`: Your Telegram API credentials.
*   `TARGET_CHANNEL_ID`: The ID of the channel/group where messages will be sent.

### 2. Webhook Configuration (Optional)

To enable webhook notifications, add the following to your `.env` file:

```env
# Webhook URL (n8n, Zapier, Make, etc.)
WEBHOOK_URL=https://your-webhook-url.com/endpoint

# Basic Auth credentials (optional)
WEBHOOK_AUTH_USERNAME=your_username
WEBHOOK_AUTH_PASSWORD=your_password
```

*   `WEBHOOK_URL`: The endpoint to send POST requests to. Leave empty to disable.
*   `WEBHOOK_AUTH_USERNAME` / `WEBHOOK_AUTH_PASSWORD`: Basic Auth credentials (optional).

#### Webhook Payload Structure

When a message is successfully forwarded, the following JSON payload is sent:

```json
{
  "event_type": "message_forwarded",
  "timestamp": "2026-01-08T21:40:00+07:00",
  "source": {
    "channel_id": -1001234567890,
    "message_id": 12345,
    "topic_id": null
  },
  "destination": {
    "channel_id": -1009876543210,
    "message_id": 54321,
    "topic_id": 123
  },
  "message": {
    "text": "The message content...",
    "author": "John Doe (@johndoe)",
    "forwarded_from": "Channel ABC",
    "has_media": true,
    "media_type": "photo"
  },
  "receiver": {
    "name": "Source Name"
  }
}
```

| Field | Description |
|-------|-------------|
| `event_type` | Always `"message_forwarded"` |
| `timestamp` | ISO 8601 timestamp with timezone |
| `source.channel_id` | Original channel ID |
| `source.message_id` | Original message ID |
| `destination.channel_id` | Target channel ID |
| `destination.message_id` | New message ID in target |
| `message.text` | Message text content |
| `message.has_media` | `true` if message contains media |
| `message.media_type` | `photo`, `video`, `document`, `audio`, `voice`, or `null` |

> **Note**: Media files are NOT sent to the webhook, only metadata.

### 3. Receiver Configuration (`receivers.json`)
Create or edit `receivers.json` to define where to grab messages *from*. This file is a JSON array of objects.

```json
[
  {
    "name": "Source Name",
    "session": "session_filename_without_extension",
    "api_id": 12345678,
    "api_hash": "your_api_hash_here",
    "source_channel": -100xxxxxxxx,
    "source_topic_id": null,
    "target_topic_id": 123,
    "start_date": "2025-01-01"
  }
]
```

*   `session`: The name of the session file to use for listening (e.g., `akun_monitor`).
*   `source_channel`: The ID of the channel to listen to.
*   `source_topic_id`: Set to `null` to listen to all topics, or a specific ID to filter.
*   `target_topic_id`: The topic ID in the `TARGET_CHANNEL` where messages should be sent.
*   `start_date`: ISO format date. Messages older than this will be ignored (useful for history catch-up logic if implemented).

## 🏃 Usage

### Setting up Sessions
Before running the main bot, you may need to log in to create the session files.
1.  Run the bot or a helper script.
2.  Enter your phone number and OTP when prompted.
3.  The `.session` file will be created.

### Getting IDs (`get_id.py`)
Use this helper script to find the IDs of groups/channels and topics.

1.  Edit `get_id.py` and set your `API_ID` and `API_HASH` at the top.
2.  Run the script:
    ```bash
    python get_id.py
    ```
3.  **List Groups**: The script exports your joined groups to `group_list.json`.
4.  **Detect IDs**: Send a message to the bot account (or in a group it's in) to print the `chat_id` and `topic_id` in the console.

### Running the Forwarder
Once configured:

```bash
python main.py
```

- The bot will initialize the `Sender` client.
- It will iterate through `receivers.json` and start a client for each configuration.
- It begins listening for new messages and forwards them according to your rules.

## 🔄 System Flow

1.  **Initialization**:
    - `main.py` loads `.env` for the Sender.
    - It loads `receivers.json` for Source definitions.
2.  **Listeners Start**:
    - For each entry in `receivers.json`, a `TelegramClient` is started.
    - These clients listen to `NewMessage` events on their configured `source_channel`.
3.  **Message Processing**:
    - When a message arrives, it is saved to a queue (`message_queue/`).
    - Media files are downloaded if present.
4.  **Forwarding**:
    - The Sender client monitors the queue.
    - It picks up messages and sends them to the `TARGET_CHANNEL_ID` (and specific `target_topic_id`).
    - It maintains mapped message IDs in `message_map.json` to handle replies correctly.
5.  **Webhook Notification** (Optional):
    - After a message is successfully sent, a webhook POST request is fired.
    - The request is non-blocking (fire-and-forget) and won't affect the main flow.
    - Errors are logged but ignored to ensure uninterrupted forwarding.

## 📂 File Structure

- `main.py`: Main application entry point.
- `get_id.py`: Utility tool for ID discovery.
- `receivers.json`: Configuration for source channels.
- `.env`: Configuration for the sender/target and webhook.
- `.env.example`: Template for environment variables.
- `message_queue/`: Temporary storage for incoming messages.
- `downloads/`: Temporary storage for media files.
- `*.session`: Telegram session files (do not share/commit these!).

## 🔌 Webhook Integration Examples

### n8n

1. Create a new workflow with a **Webhook** trigger node.
2. Copy the webhook URL and add it to your `.env`.
3. Use the incoming JSON data in subsequent nodes.

### Zapier / Make

1. Create a **Webhooks by Zapier** or **Custom Webhook** trigger.
2. Copy the webhook URL to your `.env`.
3. Map the JSON fields to your desired actions.

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| `aiohttp not installed` warning | Run `pip install aiohttp` |
| Webhook not firing | Check `WEBHOOK_URL` is set correctly in `.env` |
| `FloodWaitError` | The bot is rate-limited. Wait and retry. |
| Session expired | Delete the `.session` file and re-authenticate. |

## 📜 License

MIT License - feel free to use and modify.
