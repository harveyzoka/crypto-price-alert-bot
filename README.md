---

# Telegram Price Alert Bot (Multi-Exchange)

A lightweight Telegram bot for crypto price alerts across **Binance → Bybit → MEXC → KuCoin → OKX**.
It polls at a fixed interval and, when a threshold is hit, sends a **burst** of messages (**10 msgs, 2s apart**) and **repeats every 30s** until you **ACK** in chat. Works in DMs or groups, stores alerts **per chat**, includes **hysteresis** to avoid noisy triggers, and uses a small **price cache** to reduce API calls.

> **No secrets in Git:** keep your real token in `.env`. Commit only `.env.example`.

---

## ✨ Features

* **Multi-exchange** price resolution (automatic fallback):

  1. Binance (REST)
  2. Bybit (REST)
  3. MEXC (REST)
  4. KuCoin (REST)
  5. OKX (REST)
* Commands:

  * `/price <asset>` — quick price
    e.g. `BTCUSDT`, `binance:EDENUSDT`, `kucoin:EDEN-USDT`, `okx:BTC-USDT`
  * `/add <asset> >=|<= <price>` — create an alert
  * `/list`, `/remove <id>`, `/removeall`
  * `/ack <id>` — acknowledge alert (stops repeat bursts)
  * `/id`, `/ping`, `/help`
* **Burst alerts**: 10 messages per burst, 2 seconds apart; **re-burst every 30s** if not ACKed.
* **Hysteresis** (`REARM_GAP_PCT`) to prevent rapid toggling around thresholds.
* **Per-chat storage** (DMs and groups each have independent alert lists).
* **Price cache** (`PRICE_CACHE_TTL`) to reduce API usage.
* Job queue tuned to avoid “skipped” runs (burst is sent in background tasks).

---

## 🧱 Suggested Repo Layout

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

Create a `.env` next to the script. **Do not commit** your real `.env`.

**`.env.example`**

```dotenv
# === Telegram Price Alert Bot (.env) — No CoinGecko ===
BOT_TOKEN=PUT_YOUR_TOKEN_HERE

# Poll interval (seconds)
CHECK_INTERVAL_SEC=20

# “Decisive” alerting: 10 messages per burst, 2s apart; repeat every 30s if not ACKed
ALARM_REPEAT=10
ALARM_GAP_SEC=2
ALARM_COOLDOWN_SEC=30

# Hysteresis to re-arm (reduce false triggers around threshold). 0.002 = 0.2%
REARM_GAP_PCT=0.002

# Price cache TTL (seconds) to reduce API calls
PRICE_CACHE_TTL=120

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
  **Formats by exchange**

  * **Binance / Bybit / MEXC**: `BASEQUOTE` (no dash), e.g. `BTCUSDT`, `EDENUSDT`
  * **KuCoin / OKX**: `BASE-QUOTE` (with dash), e.g. `BTC-USDT`, `EDEN-USDT`
    **Examples**:
  * `/price BTCUSDT`
  * `/price binance:EDENUSDT`
  * `/price bybit:EDENUSDT`
  * `/price mexc:EDENUSDT`
  * `/price kucoin:EDEN-USDT`
  * `/price okx:BTC-USDT`
* `/add <asset> >=|<= <price>`
  Examples:

  * `/add binance:BTCUSDT >= 65000`
  * `/add kucoin:EDEN-USDT <= 0.47`
* `/list` — list alerts in this chat
* `/remove <id>` — remove by ID
* `/removeall` — clear all alerts in this chat
* `/ack <id>` — acknowledge alert (stop repeating bursts)

> No prefix? The bot tries to normalize the pair and checks **Binance → Bybit → MEXC → KuCoin → OKX** in that order.

---

## 👥 Using in Groups

1. Add the bot to the group → send `/start` in the group.
2. (If you enabled `ALLOWED_CHAT_IDS`) run `/id` in the group and add the **negative** group ID (`-100…`) to `.env`.
3. Create alerts in the group: `/add binance:BTCUSDT >= 60000`. All members see the bursts.

---

## 🔔 Make Notifications Hard to Miss

The bot sends messages with `disable_notification=False` to avoid silent delivery. For strong push behavior:

* **Android**:
  System Settings → Apps → Telegram → Notifications → **High/Urgent**, **Sound ON**, **Vibrate ON**, **Pop on screen**.
  Battery → Telegram = **Unrestricted**. In Telegram: Settings → Notifications → enable all; Keep-Alive (if available).
* **iOS**:
  Settings → Telegram → Notifications → **Allow** + Banners **Persistent** + Sound.
  Focus (DND) → add Telegram to **Allowed Apps**; enable **Time-Sensitive** if available.

If the group is set to “Mentions only”, change to **All messages** or adjust device settings.

---

## 📶 Data Usage

Approximation (small REST JSON responses ~0.5–2 KB). The bot groups requests per unique `(source, symbol)` per cycle:

```
MB/day ≈ (86,400 / CHECK_INTERVAL_SEC) × unique_pairs × (kB_per_req) / 1024
```

Examples (1.2 kB/req):

* 3 pairs @ 20s → ~15 MB/day
* 10 pairs @ 30s → ~34 MB/day

Increase `CHECK_INTERVAL_SEC` or `PRICE_CACHE_TTL` to save bandwidth.

---

## 🩺 Troubleshooting

* **Symbol format errors**:

  * Binance/Bybit/MEXC: `BTCUSDT` (no dash)
  * KuCoin/OKX: `BTC-USDT` (with dash)
* **No push but messages appear in chat**:
  Check device notification settings (Android/iOS) and group mute settings.
* **PEP 668 (externally-managed environment)**:
  Use a venv: `python3 -m venv .venv && source .venv/bin/activate`.
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

**Keywords**: `telegram-bot` `crypto` `price-alerts` `binance` `bybit` `mexc` `kucoin` `okx` `python` `asyncio` `job-queue`
