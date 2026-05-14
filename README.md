# Fund Watcher

A Telegram bot that monitors Chinese mutual fund (基金) purchase quota changes on [Eastmoney](https://fund.eastmoney.com) and sends real-time alerts.

**Live bot: [@fundlimit_watcher_bot](https://t.me/fundlimit_watcher_bot)**

## What it does

- Tracks per-user watchlists of funds by 6-digit code
- Polls Eastmoney every ~7 hours for quota changes
- Sends a Telegram message when a fund's status changes:
  - 🟢 Purchase reopened
  - 🚀 Fully unrestricted
  - 📈 Quota raised
  - ⚠️ Quota reduced

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

## Setup

```bash
# Install dependencies
uv sync

# Set your bot token
export BOT_TOKEN=your_token_here

# Run
uv run fund_watcher.py
```

State is persisted to `fund_state.json` in the working directory.

## Commands

| Command | Description |
|---|---|
| `/add 018147` | Add a fund to your watchlist |
| `/addall 018147 019455` | Add multiple funds at once |
| `/remove 018147` | Remove a fund from your watchlist |
| `/list` | Show your watchlist with current quotas and last-updated time |
| `/help` | Show command reference |

## Quota display

| Symbol | Meaning |
|---|---|
| 🟢 | Open / fully unrestricted |
| 🟡 | Open with a purchase cap |
| 🔴 | Suspended |
| ❓ | Status unknown |
