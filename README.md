---

# Telegram Crypto Price Alert Bot (Multi-Exchange)

A lightweight Telegram bot for **price alerts across multiple exchanges**:
**Binance / Binance Alpha / Bybit / MEXC / KuCoin / OKX / Gate / Bitget**

The bot polls prices periodically and triggers **burst notifications** when an alert condition is met:
→ **10 messages, 2s apart**, and **repeats every 30s** until you **ACK**.
Works in **private chats** and **groups**, stores alerts **per chat**, includes **hysteresis** to avoid repeated triggers, and uses a lightweight **price cache** to reduce API calls.

> **Do not commit real secrets.** Keep your `.env` local. Only commit `.env.example`.

---

## ✨ Features

* **Multi-exchange price resolution** with fallback:

  | Exchange                                        | Format     | Example                         |
  | ----------------------------------------------- | ---------- | ------------------------------- |
  | Binance / Binance Alpha / Bybit / MEXC / Bitget | `BTCUSDT`  | `binance:BTC`, `bitget:BTCUSDT` |
  | KuCoin / OKX                                    | `BTC-USDT` | `kucoin:BTC-USDT`               |
  | Gate                                            | `BTC_USDT` | `gate:BTC_USDT`                 |

* **Auto-quote expansion** (if user types just `BTC`):
  Tries: `USDT → USDC → FDUSD`.

* **Typo-tolerant exchange prefixes**, e.g.:
  `binance alpha`, `binace`, `gateio`, `bg`

* `/find <asset>` → scan **all supported exchanges**, sorted by price.

* `/unack <id>` + UI **inline buttons**: `ACK` / `UNACK`.

* Burst alerts with cooldown and **re-arm hysteresis** (`REARM_GAP_PCT`) to avoid noise.

* Alerts stored **per chat** (DM or group).

* **Price cache** (`PRICE_CACHE_TTL`) to reduce request volume.

---

## 🧱 Recommended Project Structure

```
price-alert-bot/
├─ price_alert_bot_multi.py
├─ requirements.txt
├─ .env.example
├─ .gitignore
├─ README.md
└─ deploy/
   └─ pricebot.service.example
```

**`.gitignore`**

```
.env
alerts.json
*.log
__pycache__/
*.pyc
.venv/
```

---

## 🔧 Requirements

```
python-telegram-bot[job-queue]==20.7
requests
python-dotenv
```

Install:

```bash
pip install -r requirements.txt
```

---

## ⚙️ Configuration (`.env`)

```dotenv
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN

CHECK_INTERVAL_SEC=20
ALARM_REPEAT=10
ALARM_GAP_SEC=2
ALARM_COOLDOWN_SEC=30

REARM_GAP_PCT=0.002       # 0.2% hysteresis
PRICE_CACHE_TTL=120

ALLOWED_CHAT_IDS=         # optional comma-separated whitelist
```

Get your chat ID by sending `/id` to the bot.

---

## ▶️ Running

### Windows (Anaconda)

```bat
conda create -n pricebot python=3.12 -y
conda activate pricebot
pip install -r requirements.txt
copy .env.example .env  &  edit .env
python price_alert_bot_multi.py
```

Stop with **Ctrl+C**.

### Ubuntu VPS (recommended)

```bash
sudo apt update && sudo apt install -y python3-venv
cd ~/pricebot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env     # edit BOT_TOKEN
python price_alert_bot_multi.py
```

#### Run as systemd service

`deploy/pricebot.service.example`:

```ini
[Unit]
Description=Telegram Price Alert Bot (multi-exchange)
After=network-online.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/pricebot
EnvironmentFile=/home/ubuntu/pricebot/.env
ExecStart=/home/ubuntu/pricebot/.venv/bin/python /home/ubuntu/pricebot/price_alert_bot_multi.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo cp deploy/pricebot.service.example /etc/systemd/system/pricebot.service
sudo systemctl daemon-reload
sudo systemctl enable --now pricebot
sudo systemctl status pricebot
journalctl -u pricebot -f
```

---

## 💬 Commands

| Command          | Description                     |           |
| ---------------- | ------------------------------- | --------- |
| `/price <asset>` | Quick price lookup              |           |
| `/find <asset>`  | Compare prices across exchanges |           |
| `/add <asset> >= | <= <value>`                     | Add alert |
| `/list`          | View alerts in this chat        |           |
| `/remove <id>`   | Delete alert by ID              |           |
| `/removeall`     | Clear all alerts                |           |
| `/ack <id>`      | Stop repeated alerts            |           |
| `/unack <id>`    | Re-enable repeated alerts       |           |
| `/ping`          | Check bot health                |           |
| `/id`            | Show chat ID                    |           |

**Examples:**

```
/price BTC
/price binance:BTC
/price kucoin:BTC-USDT
/price gate:BTC_USDT
/find BTC
/add BTC >= 70000
/add binance alpha: BTC <= 68000
/add bitget:BTC >= 70500
```

---

## 👥 Group Usage

1. Add bot to group
2. Send `/start` in group
3. Run `/id` → If using ALLOWED_CHAT_IDS, include the **negative group ID** (`-100...`)
4. Create alerts normally → everyone sees bursts

---

## 🔐 Security

* Never commit **`.env`** or **bot tokens**.
* If token leaks: **BotFather → /revoke → update `.env`**.
* Optional secret scanning recommended: `detect-secrets`, `pre-commit`.

---

## 📄 License

MIT / Open Use

---