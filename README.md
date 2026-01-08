# Tele Clone Saham Forwarder

A Python-based Telegram bot system designed to forward messages from multiple source channels/groups to a single target channel/supergroup. It supports topic mapping (forums), media forwarding, and uses `Telethon` for MTProto communication.

## 📋 Features

- **Multi-Source Support**: Listen to multiple source channels simultaneously.
- **Topic Mapping**: Forward messages from specific source topics to specific destination topics (for Telegram Forums).
- **Session Management**: Supports multiple Telegram user accounts/sessions.
- **Queue System**: Handles messages in a queue to prevent flooding and ensure order.
- **ID Helper**: Includes tools to easily discover Chat IDs and Topic IDs.

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
    pip install telethon
    ```

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

### 2. Receiver Configuration (`receivers.json`)
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

## 📂 File Structure

- `main.py`: Main application entry point.
- `get_id.py`: Utility tool for ID discovery.
- `receivers.json`: Configuration for source channels.
- `.env`: Configuration for the sender/target.
- `message_queue/`: Temporary storage for incoming messages.
- `downloads/`: Temporary storage for media files.
- `*.session`: Telegram session files (do not share/commit these!).
