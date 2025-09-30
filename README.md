---

# Telegram Price Alert Bot (Multi-Source)

A lightweight Telegram bot for crypto price alerts. It resolves assets across **Binance → Bybit → CoinGecko**, polls on a fixed interval, and when a threshold hits it sends a **burst** of messages (10 messages, 2s apart) and **repeats every 30s** until you **ACK** (confirm) in chat. Works in DMs or groups. Alerts are stored **per chat**. Includes **hysteresis** to avoid noisy triggers. Secrets live in `.env` (not committed).

> **No secrets in Git:** keep your real token in `.env`. Commit only `.env.example`.

---

## ✨ Features

* Multi-source price resolution: Binance, Bybit, CoinGecko (automatic fallback).
* Clean commands:

  * `/price <asset>` — quick price (e.g., `BTCUSDT`, `binance:EDENUSDT`, `cg:openeden`)
  * `/add <asset> >=|<= <price>` — create an alert
  * `/list` `/remove <id>` `/removeall`
  * `/find <query>` — find CoinGecko IDs
  * `/ack <id>` — acknowledge alert (stop repeats)
  * `/id`, `/ping`, `/help`
* **Burst alerts**: 10 messages per burst, 2 seconds apart; **re-burst every 30s** if not ACKed.
* **Hysteresis** (`REARM_GAP_PCT`) to prevent rapid toggling around thresholds.
* Per-chat storage (DMs and groups each have independent alert lists).
* Auto-migration from older alert formats.

---

## 📁 Suggested Repo Layout

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
# secrets & runtime
.env
alerts.json
*.log

# python cache & env
__pycache__/
*.pyc
.venv/
.venv*/
.env.*/
```

---

## 🔧 Requirements

* Python 3.10+ (tested with 3.12)
* `python-telegram-bot[job-queue]==20.7`
* `requests`
* `python-dotenv`

Install with:

```bash
pip install -r requirements.txt
```

`requirements.txt`:

```
python-telegram-bot[job-queue]==20.7
requests
python-dotenv
```

---

## ⚙️ Configuration

Create a `.env` next to the script. **Do not commit** your real `.env`. Use `.env.example` as a template.

**`.env.example`**

```dotenv
# === Telegram Price Alert Bot (.env) ===
BOT_TOKEN=PUT_YOUR_TOKEN_HERE

# Poll interval (seconds)
CHECK_INTERVAL_SEC=10

# “Decisive” alerting: 10 messages per burst, 2s apart; repeat every 30s if not ACKed
ALARM_REPEAT=10
ALARM_GAP_SEC=2
ALARM_COOLDOWN_SEC=30

# Hysteresis to re-arm (reduce false triggers around threshold). 0.002 = 0.2%
REARM_GAP_PCT=0.002

# (Optional) Restrict bot usage to these chat IDs (DMs or groups, comma-separated)
# ALLOWED_CHAT_IDS=123456789,-1001234567890
ALLOWED_CHAT_IDS=
```

> Get your `chat_id` by sending `/id` to the bot in a DM or in the target group.

---

## ▶️ Running

### A) Windows (Anaconda)

```bat
:: Anaconda Prompt
conda create -n pricebot python=3.12 -y
conda activate pricebot
pip install -r requirements.txt

copy .env.example .env   :: edit BOT_TOKEN in .env
python price_alert_bot_multi.py
```

Stop with **Ctrl+C**.

### B) Ubuntu VPS (venv + systemd recommended)

```bash
sudo apt update && sudo apt install -y python3-venv
cd ~/pricebot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env     # edit BOT_TOKEN
python price_alert_bot_multi.py   # test foreground (Ctrl+C to stop)
```

**Run as a service (auto-start on boot):**

`deploy/pricebot.service.example`:

```ini
[Unit]
Description=Telegram Price Alert Bot (multi-source)
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

Install & start:

```bash
sudo cp deploy/pricebot.service.example /etc/systemd/system/pricebot.service
sudo systemctl daemon-reload
sudo systemctl enable --now pricebot
sudo systemctl status pricebot
journalctl -u pricebot -f
```

Manage:

```bash
sudo systemctl stop pricebot
sudo systemctl restart pricebot
```

---

## 💬 Commands

* `/start` – intro
* `/help` – quick guide
* `/id` – show current chat_id (DM or group)
* `/ping` – health check
* `/price <asset>`
  Examples:

  * `/price BTCUSDT`
  * `/price binance:EDENUSDT`
  * `/price bybit:EDENUSDT`
  * `/price cg:openeden`
* `/find <query>` — search CoinGecko IDs (e.g., `/find eden`)
* `/add <asset> >=|<= <price>`
  Examples:

  * `/add BTCUSDT >= 65000`
  * `/add binance:EDENUSDT <= 0.47`
  * `/add cg:openeden >= 0.48`
* `/list` — list alerts in this chat
* `/remove <id>` — remove by ID
* `/removeall` — clear all alerts in this chat
* `/ack <id>` — acknowledge alert (stop repeating bursts)

> No source prefix? The bot tries to normalize (adds USDT/USDC) and checks **Binance → Bybit → CoinGecko** in that order.

---

## 👥 Using in Groups

1. Add the bot to the group → send `/start` in the group.
2. (If you enabled `ALLOWED_CHAT_IDS`) run `/id` in the group and add the **negative** group ID (`-100…`) to `.env`.
3. Create alerts in the group: `/add BTCUSDT >= 60000`. All members see the bursts.

---

## 🔔 Make Notifications Hard to Miss

The bot sends messages with `disable_notification=False` to avoid silent delivery. For strong push behavior:

* **Android**:
  System Settings → Apps → Telegram → Notifications → **High/Urgent**, **Sound ON**, **Vibrate ON**, **Pop on screen**.
  Battery → Telegram = **Unrestricted**. In Telegram: Settings → Notifications → enable all; Keep-Alive (if available).
* **iOS**:
  Settings → Telegram → Notifications → **Allow** + Banners **Persistent** + Sound.
  Focus (DND) → add Telegram to **Allowed Apps**; enable **Time-Sensitive** if available.

If the group is set to “Mentions only”, change to **All messages** or rely on device settings to allow Telegram alerts.

---

## 📶 Data Usage

Typical REST ticker responses are small (~0.5–2 KB). The bot groups requests by `(source, symbol)` per cycle, so daily usage is roughly:

```
MB/day ≈ (86,400 / CHECK_INTERVAL_SEC) × unique_pairs × (kB_per_req) / 1024
```

Examples (1.2 kB/req):

* 3 pairs @ 10s → ~30 MB/day
* 10 pairs @ 30s → ~34 MB/day

Increase `CHECK_INTERVAL_SEC` to save bandwidth (20–30s is fine for most alerts).

---

## 🩺 Troubleshooting

* **No phone push but messages appear in chat**:
  Check device notification settings (Android/iOS) and group mute settings.
* **`ModuleNotFoundError: dotenv`**:
  `pip install -r requirements.txt` in your active environment/venv.
* **PEP 668 (externally-managed environment)**:
  Use a venv: `python3 -m venv .venv && source .venv/bin/activate`.
* **`KeyError: 'src'` after upgrading**:
  The bot auto-migrates; if needed, delete old `alerts.json`.
* **Stop the bot**:
  Foreground: **Ctrl+C**.
  systemd: `sudo systemctl stop pricebot`.

---

## 🔐 Security

* Never commit `.env`, `alerts.json`, or logs containing secrets.
* If a token leaked, rotate via **@BotFather → /revoke**, update your `.env`.
* Optional local guardrails:

  ```bash
  pip install pre-commit detect-secrets
  detect-secrets scan > .secrets.baseline
  echo 'repos:
    - repo: https://github.com/Yelp/detect-secrets
      rev: v1.4.0
      hooks: [{ id: detect-secrets, args: ["--baseline", ".secrets.baseline"] }]
  ' > .pre-commit-config.yaml
  pre-commit install
  ```

---

## 📄 License

MIT (or your preferred license).

---

**Keywords**: `telegram-bot` `crypto` `price-alerts` `binance` `bybit` `coingecko` `python` `asyncio` `job-queue`
