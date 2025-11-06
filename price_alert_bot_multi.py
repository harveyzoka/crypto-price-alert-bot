#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Telegram Price Alert Bot — Multi-exchange
# Binance, Binance Alpha, Bybit, MEXC, KuCoin, OKX, Gate, Bitget
# Burst mạnh (10 tin, cách 2s), lặp 30s tới khi ACK. Không dùng CoinGecko.

import os, json, time, asyncio, re
from typing import Dict, Any, List, Tuple, Optional
import requests

from dotenv import load_dotenv
from telegram import (
    Update, BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.error import TimedOut, RetryAfter, NetworkError

# ===== PTB (telegram.ext) =====
# Với PTB v20.x (môi trường của bạn), các import dưới đây đều có.
# Nếu bạn hạ cấp về v13 thì sẽ khác, nhưng hiện tại không cần.
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters, JobQueue,
    CallbackQueryHandler
)

# ===== Tùy phiên bản: Defaults có thể không tồn tại =====
try:
    from telegram import Defaults as _Defaults
    _HAS_DEFAULTS = True
except Exception:
    _HAS_DEFAULTS = False

# ===== Tùy phiên bản: HTTPXRequest có thể không tồn tại =====
try:
    from telegram.request import HTTPXRequest as _HTTPXRequest
    _HAS_HTTPX = True
except Exception:
    _HAS_HTTPX = False


# ===== ENV =====
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHECK_INTERVAL_SEC = int(os.getenv("CHECK_INTERVAL_SEC", "10"))
ALARM_REPEAT = int(os.getenv("ALARM_REPEAT", "10"))
ALARM_GAP_SEC = float(os.getenv("ALARM_GAP_SEC", "2"))
ALARM_COOLDOWN_SEC = int(os.getenv("ALARM_COOLDOWN_SEC", "30"))
REARM_GAP_PCT = float(os.getenv("REARM_GAP_PCT", "0.002"))
ALLOWED_CHAT_IDS = [int(x) for x in os.getenv("ALLOWED_CHAT_IDS", "").split(",") if x.strip().lstrip("-").isdigit()]

DATA_FILE = "alerts.json"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "price-alert-bot/2.3"})

# QUOTES dùng cho chuyển đổi định dạng (bao gồm BTC/ETH để hỗ trợ cặp chéo)
KNOWN_QUOTES = ["USDT", "USDC", "FDUSD", "BUSD", "BTC", "ETH"]
# QUOTES thực sự trên spot để quyết định "đã có quote chưa" & fallback
QUOTE_SUFFIXES = ["USDT", "USDC", "FDUSD", "BUSD", "USD", "TUSD"]
# Thứ tự ưu tiên khi tự nối
TRY_QUOTES = ["USDT", "USDC", "FDUSD"]

# ===== Cache =====
PRICE_CACHE_TTL = int(os.getenv("PRICE_CACHE_TTL", "120"))
PRICE_CACHE: Dict[Tuple[str,str], Tuple[float,float]] = {}

def cache_set(src: str, code: str, price: float):
    PRICE_CACHE[(src, code)] = (float(price), time.time())

def cache_get(src: str, code: str):
    v = PRICE_CACHE.get((src, code))
    if not v: return None, None
    price, ts = v
    if time.time() - ts <= PRICE_CACHE_TTL:
        return price, ts
    return None, None

# ===== Store =====
def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE): return {"alerts": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f: return json.load(f)

def save_data(d: Dict[str,Any]):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)

# ===== Symbol helpers =====
def undash_to_dash(sym: str) -> str:
    """EDENUSDT -> EDEN-USDT (KuCoin/OKX)."""
    s = sym.upper().replace("_", "-")
    if "-" in s:
        return s
    for q in sorted(KNOWN_QUOTES, key=len, reverse=True):
        if s.endswith(q):
            base = s[:-len(q)]
            if base:
                return f"{base}-{q}"
    return f"{s}-USDT"

def normalize_no_dash(sym: str) -> str:
    """BTCUSDT (Binance/Bybit/MEXC/Bitget/Binance Alpha)."""
    return sym.upper().replace("-", "").replace("_","")

def to_gate_pair(sym: str) -> str:
    """BTC_USDT (Gate)."""
    s = sym.upper().replace("-", "_")
    if "_" in s:
        return s
    for q in sorted(KNOWN_QUOTES, key=len, reverse=True):
        if s.endswith(q):
            base = s[:-len(q)]
            if base:
                return f"{base}_{q}"
    return f"{s}_USDT"

# ===== Prefix normalization & typos =====
ALIAS_MAP = {
    "binance": {"binance","binace","bnance","binan","binanace","binnace","bin"},
    "bybit":   {"bybit","bybt","byb","bybitspot"},
    "mexc":    {"mexc","mex","mecx"},
    "kucoin":  {"kucoin","kuc","ku"},
    "okx":     {"okx","okex","ok"},
    "gate":    {"gate","gateio","gat"},
    "bitget":  {"bitget","bitgt","biget","bg"},
    "binance_alpha": {"binancealpha","binance alpha","alpha","bnalpha","binancea"}
}
CANONICALS = {alias: key for key, vals in ALIAS_MAP.items() for alias in vals}

def normalize_prefix(p: str) -> Optional[str]:
    s = re.sub(r"[^a-z]", "", p.lower())  # bỏ khoảng trắng, dấu
    return CANONICALS.get(s)

# ===== Providers =====
def get_price_binance(symbol: str) -> float:
    symbol = normalize_no_dash(symbol)
    r = SESSION.get("https://api.binance.com/api/v3/ticker/price",
                    params={"symbol": symbol}, timeout=6)
    r.raise_for_status()
    j = r.json()
    if "price" not in j: raise ValueError("Binance: invalid response")
    return float(j["price"])

def get_price_binance_alpha(symbol: str) -> float:
    symbol = normalize_no_dash(symbol)
    r = SESSION.get("https://api1.binance.com/api/v3/ticker/price",
                    params={"symbol": symbol}, timeout=6)
    r.raise_for_status()
    j = r.json()
    if "price" not in j: raise ValueError("Binance Alpha: invalid response")
    return float(j["price"])

def get_price_bybit(symbol: str) -> float:
    symbol = normalize_no_dash(symbol)
    r = SESSION.get("https://api.bybit.com/v5/market/tickers",
                    params={"category":"spot","symbol":symbol}, timeout=6)
    r.raise_for_status()
    j = r.json()
    if j.get("retCode")!=0 or not j.get("result") or not j["result"].get("list"):
        raise ValueError("Bybit: not found")
    price_str = j["result"]["list"][0].get("lastPrice")
    if not price_str: raise ValueError("Bybit: invalid price")
    return float(price_str)

def get_price_mexc(symbol: str) -> float:
    symbol = normalize_no_dash(symbol)
    r = SESSION.get("https://api.mexc.com/api/v3/ticker/price",
                    params={"symbol": symbol}, timeout=6)
    r.raise_for_status()
    j = r.json()
    if "price" not in j: raise ValueError("MEXC: invalid response")
    return float(j["price"])

def get_price_kucoin(symbol: str) -> float:
    symbol = undash_to_dash(symbol)
    r = SESSION.get("https://api.kucoin.com/api/v1/market/orderbook/level1",
                    params={"symbol": symbol}, timeout=6)
    r.raise_for_status()
    j = r.json()
    if j.get("code") != "200000" or not j.get("data"):
        raise ValueError("KuCoin: not found")
    price = j["data"].get("price")
    if not price: raise ValueError("KuCoin: invalid price")
    return float(price)

def get_price_okx(symbol: str) -> float:
    symbol = undash_to_dash(symbol)
    r = SESSION.get("https://www.okx.com/api/v5/market/ticker",
                    params={"instId": symbol}, timeout=6)
    r.raise_for_status()
    j = r.json()
    if j.get("code") != "0" or not j.get("data"):
        raise ValueError("OKX: not found")
    last = j["data"][0].get("last")
    if not last: raise ValueError("OKX: invalid price")
    return float(last)

def get_price_gate(symbol: str) -> float:
    pair = to_gate_pair(symbol)
    r = SESSION.get("https://api.gateio.ws/api/v4/spot/tickers",
                    params={"currency_pair": pair}, timeout=6)
    r.raise_for_status()
    j = r.json()
    if not isinstance(j, list) or not j:
        raise ValueError("Gate: not found")
    last = j[0].get("last")
    if not last: raise ValueError("Gate: invalid price")
    return float(last)

def get_price_bitget(symbol: str) -> float:
    # Bitget yêu cầu dạng BTCUSDT; nếu thiếu quote -> mặc định USDT
    sym = normalize_no_dash(symbol)
    if not any(sym.endswith(q) for q in QUOTE_SUFFIXES):
        sym = sym + "USDT"

    # Thử 2 endpoint; khi nhận list thì lọc đúng symbol
    url_try = [
        ("https://api.bitget.com/api/spot/v1/market/ticker", {"symbol": sym}, False),
        ("https://api.bitget.com/api/spot/v1/market/tickers", {"symbol": sym}, True),
    ]
    last_err = None
    for url, params, is_list in url_try:
        try:
            r = SESSION.get(url, params=params, timeout=6)
            r.raise_for_status()
            j = r.json()
            data = j.get("data")
            if not data:
                continue
            if is_list:
                if isinstance(data, list):
                    for it in data:
                        s = (it.get("symbol") or it.get("instId") or "").upper()
                        if s == sym:
                            px = it.get("close") or it.get("lastPr")
                            if px: return float(px)
                continue
            else:
                if isinstance(data, dict):
                    s = (data.get("symbol") or data.get("instId") or "").upper()
                    if s != sym:
                        continue
                    px = data.get("close") or data.get("lastPr")
                    if px: return float(px)
        except Exception as e:
            last_err = e
            continue
    raise ValueError(f"Bitget: not found for {sym} ({last_err})")

# dispatch
PROVIDERS = {
    "binance": get_price_binance,
    "binance_alpha": get_price_binance_alpha,
    "bybit": get_price_bybit,
    "mexc": get_price_mexc,
    "kucoin": get_price_kucoin,
    "okx": get_price_okx,
    "gate": get_price_gate,
    "bitget": get_price_bitget,
}

def provider_display_name(src: str) -> str:
    return {
        "binance": "Binance",
        "binance_alpha": "Binance Alpha",
        "bybit": "Bybit",
        "mexc": "MEXC",
        "kucoin": "KuCoin",
        "okx": "OKX",
        "gate": "Gate",
        "bitget": "Bitget",
    }.get(src, src.capitalize())

def get_price_resolved(src: str, code: str) -> float:
    cp, ts = cache_get(src, code)
    if cp is not None:
        return cp
    if src not in PROVIDERS:
        raise ValueError("Unknown source")
    price = PROVIDERS[src](code)
    cache_set(src, code, price)
    return price

def format_symbol_for_display(src: str, code: str) -> str:
    if src in ("kucoin","okx"):
        return undash_to_dash(code)
    if src=="gate":
        return to_gate_pair(code)
    return normalize_no_dash(code)

# ===== Fallback symbol builder for a specific exchange =====
def _codes_for_src_with_fallback(src: str, body: str) -> List[str]:
    """Sinh dãy symbol cho 1 sàn khi người dùng có thể thiếu quote."""
    body = (body or "").strip()
    if not body:
        body = "BTC"

    def has_quote(s: str) -> bool:
        s2 = s.upper().replace("-", "").replace("_", "")
        return any(s2.endswith(q) for q in QUOTE_SUFFIXES)

    codes: List[str] = []
    if src in ("binance","bybit","mexc","bitget","binance_alpha"):
        if has_quote(body): codes = [normalize_no_dash(body)]
        else: codes = [normalize_no_dash(body + q) for q in TRY_QUOTES]
    elif src in ("kucoin","okx"):
        if has_quote(body): codes = [undash_to_dash(body)]
        else: codes = [undash_to_dash(body + q) for q in TRY_QUOTES]
    elif src == "gate":
        if has_quote(body): codes = [to_gate_pair(body)]
        else: codes = [to_gate_pair(body + q) for q in TRY_QUOTES]
    else:
        raise ValueError("Nguồn không hỗ trợ")

    seen=set(); out=[]
    for c in codes:
        if c not in seen:
            out.append(c); seen.add(c)
    return out

# ===== Resolve asset =====
def try_first_available(cands: List[Tuple[str, str]]) -> Tuple[str,str,str]:
    for src, code in cands:
        try:
            _ = get_price_resolved(src, code)
            name = provider_display_name(src)
            disp = f"{format_symbol_for_display(src, code)} ({name})"
            return src, code, disp
        except Exception:
            continue
    raise ValueError("Không tìm thấy cặp trên các sàn hỗ trợ (Binance/Bybit/MEXC/KuCoin/OKX/Gate/Bitget)")

def resolve_asset(raw: str) -> Tuple[str,str,str]:
    x = raw.strip()
    # Cho phép "prefix: body" hoặc "prefix body"
    if ":" in x or re.search(r"\s+\S+", x):
        if ":" in x:
            pfx, body = x.split(":",1)
        else:
            parts = x.split()
            if len(parts)>=2:
                pfx, body = parts[0], " ".join(parts[1:])
            else:
                pfx, body = x, ""
        p = normalize_prefix(pfx)
        b = body.strip()
        if p:
            codes = _codes_for_src_with_fallback(p, b)
            last_err = None
            for code in codes:
                try:
                    _ = get_price_resolved(p, code)
                    return p, code, f"{format_symbol_for_display(p, code)} ({provider_display_name(p)})"
                except Exception as e:
                    last_err = e
                    continue
            raise ValueError(f"{provider_display_name(p)}: symbol không hợp lệ ({last_err})")
        raise ValueError("Nguồn không hỗ trợ. Dùng: binance | bybit | mexc | kucoin | okx | gate | bitget | binance alpha")

    # Không prefix: dò tự động
    base = x.upper().replace("-", "").replace("_","").strip()
    if not base:
        raise ValueError("Thiếu mã tài sản.")
    if any(base.endswith(q) for q in QUOTE_SUFFIXES):
        cands = [
            ("binance", base),
            ("binance_alpha", base),
            ("bybit",   base),
            ("mexc",    base),
            ("bitget",  base),
            ("kucoin",  undash_to_dash(base)),
            ("okx",     undash_to_dash(base)),
            ("gate",    to_gate_pair(base)),
        ]
        return try_first_available(cands)

    for q in TRY_QUOTES:
        cand = base + q
        cands = [
            ("binance", cand),
            ("binance_alpha", cand),
            ("bybit",   cand),
            ("mexc",    cand),
            ("bitget",  cand),
            ("kucoin",  undash_to_dash(cand)),
            ("okx",     undash_to_dash(cand)),
            ("gate",    to_gate_pair(cand)),
        ]
        try:
            return try_first_available(cands)
        except Exception:
            continue
    raise ValueError("Không tự động nhận diện được cặp. Ví dụ: binance:EDENUSDT | kucoin:EDEN-USDT | gate:EDEN_USDT")

# ===== Utils: Telegram safe send =====
async def send_safe(bot, chat_id: int, text: str, reply_markup=None) -> bool:
    """Gửi 1 tin với retry khi gặp TimedOut/RetryAfter/NetworkError."""
    for _ in range(4):  # tối đa 4 lần
        try:
            await bot.send_message(chat_id=chat_id, text=text, disable_notification=False, reply_markup=reply_markup)
            return True
        except RetryAfter as e:
            await asyncio.sleep(float(getattr(e, "retry_after", 1)) + 0.7)
        except (TimedOut, NetworkError):
            await asyncio.sleep(1.5)
        except Exception:
            break
    return False

async def safe_reply(message, text):
    try:
        await message.reply_text(text)
    except RetryAfter as e:
        await asyncio.sleep(float(getattr(e, "retry_after", 1)) + 0.7)
        try: await message.reply_text(text)
        except Exception: pass
    except (TimedOut, NetworkError):
        pass
    except Exception:
        pass

# ===== Burst sender =====
async def send_burst(bot, chat_id: int, text: str, alert_id: int):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Đã nhận #{alert_id}", callback_data=f"ack:{alert_id}")],
        [InlineKeyboardButton(f"🔁 Unack #{alert_id}", callback_data=f"unack:{alert_id}")]
    ])
    await send_safe(bot, chat_id, text, reply_markup=kb)
    for _ in range(max(0, ALARM_REPEAT-1)):
        await asyncio.sleep(ALARM_GAP_SEC)
        await send_safe(bot, chat_id, text)

# ===== Commands =====
def allowed(update: Update) -> bool:
    return not ALLOWED_CHAT_IDS or (update.effective_chat and update.effective_chat.id in ALLOWED_CHAT_IDS)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    await safe_reply(update.message,
        "Price alert bot (Binance/Bybit/MEXC/KuCoin/OKX/Gate/Bitget/Binance Alpha)\n"
        "/help /id /ping\n"
        "/price <asset>\n"
        "/find <asset>\n"
        "/add <asset> >=|<= <price>\n/list /remove <id> /removeall\n/ack <id> /unack <id>\n"
        "Ví dụ: /price EDENUSDT | /price kucoin:EDEN-USDT | /price gate EDEN_USDT | /add binance: BTC >= 70000"
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    await safe_reply(update.message,
        "Lệnh sử dụng:\n"
        "• /price <asset> — xem giá nhanh\n"
        "• /find <asset> — xem giá trên tất cả sàn\n"
        "• /add <asset> >=|<= <giá> — tạo cảnh báo giá\n"
        "• /list, /remove <id>, /removeall\n"
        "• /ack <id>, /unack <id>\n\n"
        "Ví dụ (để bot tự chọn sàn):\n"
        "  /add BTC >= 70000\n"
        "  /add SOL <= 140\n\n"
        "Ví dụ (chỉ định sàn, có thể thiếu quote):\n"
        "  /add binance:BTC >= 70000      (thử BTCUSDT → BTCUSDC → BTCFDUSD)\n"
        "  /add binance alpha: BTC >= 70000\n"
        "  /add bybit:ETHUSDT <= 2400\n"
        "  /add kucoin:BTC-USDT >= 70000\n"
        "  /add okx:SOL-USDT <= 140\n"
        "  /add bitget:BTC >= 69000       (mặc định BTCUSDT nếu thiếu)\n"
        "  /add gate:BTC_USDT <= 69000\n\n"
        "Lưu ý: KuCoin/OKX dùng '-'; Gate dùng '_'; còn lại dùng BTCUSDT."
    )

async def cmd_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await safe_reply(update.message, f"chat_id: {update.effective_chat.id}")

async def cmd_ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    await safe_reply(update.message, "✅ Bot is running")

async def cmd_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    if not ctx.args: return await safe_reply(update.message, "Usage: /price <asset>")
    query = " ".join(ctx.args)
    try:
        src, code, disp = resolve_asset(query)
        price = get_price_resolved(src, code)
        await safe_reply(update.message, f"💱 {disp} = {price}")
    except Exception as e:
        await safe_reply(update.message,
            "❌ Không lấy được giá: {err}\nThử: binance:<symbol> | bybit:<symbol> | mexc:<symbol> | "
            "kucoin:<base-quote> | okx:<base-quote> | gate:<base_quote> | bitget:<symbol> | binance alpha:<symbol>."
            .format(err=e)
        )

async def cmd_find(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    if not ctx.args: return await safe_reply(update.message, "Usage: /find <asset>")
    raw = " ".join(ctx.args).strip()

    base = raw
    if ":" in raw:
        base = raw.split(":",1)[1].strip()
    else:
        parts = raw.split()
        if len(parts) >= 2 and normalize_prefix(parts[0]):
            base = " ".join(parts[1:]).strip()

    sym_nodash = normalize_no_dash(base)
    candidates: List[Tuple[str,str]] = []

    def has_quote(s: str) -> bool:
        return any(s.upper().endswith(q) for q in QUOTE_SUFFIXES)

    def add_block(sym_core: str):
        candidates.extend([
            ("binance", sym_core),
            ("binance_alpha", sym_core),
            ("bybit", sym_core),
            ("mexc", sym_core),
            ("bitget", sym_core),
            ("kucoin", undash_to_dash(sym_core)),
            ("okx",    undash_to_dash(sym_core)),
            ("gate",   to_gate_pair(sym_core)),
        ])

    if has_quote(sym_nodash):
        add_block(sym_nodash)
    else:
        for q in TRY_QUOTES:
            add_block(sym_nodash + q)

    # Gate extra
    candidates.append(("gate", to_gate_pair(base)))

    # Unique
    seen=set(); uniq=[]
    for c in candidates:
        if c not in seen:
            uniq.append(c); seen.add(c)

    results=[]
    for src, code in uniq:
        try:
            px = get_price_resolved(src, code)
            results.append((provider_display_name(src), format_symbol_for_display(src, code), px))
        except Exception:
            continue

    if not results:
        return await safe_reply(update.message, "❌ Không tìm thấy giá trên các sàn.")

    results.sort(key=lambda x: float(x[2]))
    lines = ["🔎 Kết quả /find:"]
    for name, disp, px in results:
        lines.append(f"• {name:<14} {disp:<18} = {px}")
    await safe_reply(update.message, "\n".join(lines))

def parse_add(args: List[str]) -> Optional[Tuple[str,str,float]]:
    # Cho phép: <asset> >= <price> ; asset có thể gồm 1-2 phần (prefix + symbol)
    if len(args) < 3: return None
    op_idx = 1
    if len(args) >= 4 and args[1] not in (">=","<="):
        op_idx = 2
    asset = " ".join(args[:op_idx])
    op = args[op_idx]
    if op not in (">=","<="): return None
    try:
        val = float(args[op_idx+1])
    except:
        return None
    return asset, op, val

def next_id(alerts: List[Dict[str,Any]]) -> int:
    return 1 + max([a["id"] for a in alerts], default=0)

def migrate_store():
    d = load_data(); changed=False
    for cid, arr in list(d.get("alerts", {}).items()):
        new=[]
        for a in arr:
            ma=migrate_alert(a)
            if ma: new.append(ma); changed|=(ma is not a)
            else: changed=True
        d["alerts"][cid]=new
    if changed: save_data(d)

def migrate_alert(a: Dict[str,Any]) -> Optional[Dict[str,Any]]:
    # Nếu thiếu src/code... loại bỏ
    if not all(k in a for k in ("src","code","op","value")):
        return None
    # bỏ các cảnh báo từ nguồn cũ (CoinGecko)
    if a.get("src") == "coingecko":
        return None
    a.setdefault("display", f"{a['code']} ({a['src'].capitalize()})")
    a.setdefault("triggered", False)
    a.setdefault("last_price", None)
    a.setdefault("last_fired", 0)
    a.setdefault("last_call", 0)
    a.setdefault("ack", False)
    return a


async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    p = parse_add(ctx.args)
    if not p:
        return await safe_reply(update.message,
            "Cú pháp:\n"
            "  /add <asset> >=|<= <giá>\n\n"
            "Ví dụ (tự tìm sàn):\n"
            "  /add BTC >= 70000\n\n"
            "Ví dụ (chỉ định sàn):\n"
            "  /add binance:BTC >= 70000\n"
            "  /add binance alpha: BTC >= 70000\n"
            "  /add bitget:BTC <= 68000\n"
            "  /add kucoin:BTC-USDT >= 70000\n"
            "  /add gate:BTC_USDT >= 70000"
        )
    asset, op, val = p

    try:
        src, code, disp = resolve_asset(asset)
        _ = get_price_resolved(src, code)  # validate sớm
    except Exception as e:
        return await safe_reply(update.message, f"❌ Không thêm được: {e}\nDùng /price để kiểm tra trước.")

    cid = str(update.effective_chat.id)
    d = load_data(); d["alerts"].setdefault(cid, [])
    new = {"id": next_id(d["alerts"][cid]), "src": src, "code": code, "display": disp,
           "op": op, "value": val, "triggered": False, "last_price": None,
           "last_fired": 0, "last_call": 0, "ack": False}
    d["alerts"][cid].append(new); save_data(d)
    await safe_reply(update.message, f"✅ Đã thêm #{new['id']}: {disp} {op} {val}")

async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    d = load_data(); arr = d["alerts"].get(str(update.effective_chat.id), [])
    if not arr: return await safe_reply(update.message, "Chưa có cảnh báo nào.")
    s = "\n".join([f"#{a['id']}: {a['display']} {a['op']} {a['value']} (fired={a['triggered']}, ack={a.get('ack',False)})" for a in arr])
    await safe_reply(update.message, "Danh sách cảnh báo:\n"+s)

async def cmd_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    if not ctx.args: return await safe_reply(update.message, "Dùng: /remove <id>")
    try: rid=int(ctx.args[0])
    except: return await safe_reply(update.message, "ID phải là số.")
    d=load_data(); cid=str(update.effective_chat.id); arr=d["alerts"].get(cid,[])
    new=[a for a in arr if a["id"]!=rid]
    if len(new)==len(arr): return await safe_reply(update.message, f"Không thấy ID #{rid}.")
    d["alerts"][cid]=new; save_data(d)
    await safe_reply(update.message, f"🗑️ Đã xoá #{rid}.")

async def cmd_removeall(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    cid=str(update.effective_chat.id); d=load_data(); d["alerts"][cid]=[]; save_data(d)
    await safe_reply(update.message, "🧹 Đã xoá tất cả cảnh báo.")

async def cmd_ack(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: return await safe_reply(update.message, "Dùng: /ack <id>")
    try: rid=int(ctx.args[0])
    except: return await safe_reply(update.message, "ID phải là số.")
    cid=str(update.effective_chat.id); d=load_data(); arr=d["alerts"].get(cid,[])
    for a in arr:
        if a["id"]==rid:
            a["ack"]=True; save_data(d)
            return await safe_reply(update.message, f"🛑 Đã nhận cảnh báo #{rid}. Dừng lặp.")
    await safe_reply(update.message, f"Không thấy ID #{rid}.")

async def cmd_unack(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args: return await safe_reply(update.message, "Dùng: /unack <id>")
    try: rid=int(ctx.args[0])
    except: return await safe_reply(update.message, "ID phải là số.")
    cid=str(update.effective_chat.id); d=load_data(); arr=d["alerts"].get(cid,[])
    for a in arr:
        if a["id"]==rid:
            a["ack"]=False; a["triggered"]=False; save_data(d)
            return await safe_reply(update.message, f"🔁 Đã unack #{rid}.")
    await safe_reply(update.message, f"Không thấy ID #{rid}.")

async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    data = q.data
    cid=str(q.message.chat.id); d=load_data(); arr=d["alerts"].get(cid,[])
    if data.startswith("ack:"):
        try: rid=int(data.split(":")[1])
        except: return
        for a in arr:
            if a["id"]==rid:
                a["ack"]=True; save_data(d)
                try: await q.edit_message_text(f"🛑 Đã nhận cảnh báo #{rid}. Dừng lặp.")
                except Exception: pass
                return
    elif data.startswith("unack:"):
        try: rid=int(data.split(":")[1])
        except: return
        for a in arr:
            if a["id"]==rid:
                a["ack"]=False; a["triggered"]=False; save_data(d)
                try: await q.edit_message_text(f"🔁 Đã unack #{rid}.")
                except Exception: pass
                return

# ===== Job =====
async def price_job(context: ContextTypes.DEFAULT_TYPE):
    now=time.time(); d=load_data()
    groups: Dict[Tuple[str,str], List[Dict[str,Any]]] = {}
    for chat_id, arr in d.get("alerts", {}).items():
        for a in arr:
            if not all(k in a for k in ("src","code","op","value")): continue
            groups.setdefault((a["src"], a["code"]), []).append({"chat_id": chat_id, "alert": a})

    for (src, code), items in groups.items():
        try:
            price = get_price_resolved(src, code)
        except Exception:
            continue

        for item in items:
            chat_id = item["chat_id"]; a=item["alert"]
            a["last_price"]=price

            cond = (price >= a["value"]) if a["op"]==">=" else (price <= a["value"])
            back = (price <= a["value"]*(1-REARM_GAP_PCT)) if a["op"]==">=" else (price >= a["value"]*(1+REARM_GAP_PCT))
            if back:
                a["triggered"]=False

            should_fire=False
            if cond and not a["triggered"] and not a.get("ack",False):
                should_fire=True
            elif cond and not a.get("ack",False) and (now - a.get("last_fired",0) >= ALARM_COOLDOWN_SEC):
                should_fire=True

            if should_fire:
                a["triggered"]=True
                a["last_fired"]=now
                save_data(d)
                text=f"🚨 {a['display']} {a['op']} {a['value']} — Giá: {price}"
                context.application.create_task(
                    send_burst(context.bot, int(chat_id), text, a["id"])
                )

    save_data(d)

# ===== Post-init =====
async def post_init(app: Application):
    cmds_private = [
        BotCommand("help","Help"), BotCommand("id","Show chat_id"),
        BotCommand("price","Quick price"), BotCommand("find","Find across exchanges"),
        BotCommand("add","Add alert"), BotCommand("list","List alerts"),
        BotCommand("remove","Remove by ID"), BotCommand("removeall","Remove all"),
        BotCommand("ack","Acknowledge"), BotCommand("unack","Un-acknowledge"),
        BotCommand("ping","Health check"),
    ]
    await app.bot.set_my_commands(cmds_private, scope=BotCommandScopeAllPrivateChats())
    cmds_group = [
        BotCommand("price","Quick price"), BotCommand("find","Find across exchanges"),
        BotCommand("add","Add alert"),
        BotCommand("list","List alerts"), BotCommand("remove","Remove"),
        BotCommand("removeall","Remove all"), BotCommand("ack","Acknowledge"),
        BotCommand("unack","Un-acknowledge"), BotCommand("ping","Health check"),
    ]
    await app.bot.set_my_commands(cmds_group, scope=BotCommandScopeAllGroupChats())

async def unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text and update.message.text.startswith("/"):
        await safe_reply(update.message, "❓ Lệnh không hợp lệ. Gõ /help để xem hướng dẫn.")

# ===== Main =====
def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is empty (.env)")

    # Tạo request với timeout nếu có HTTPXRequest (PTB >= v20)
    request = None
    if _HAS_HTTPX:
        request = _HTTPXRequest(
            read_timeout=30.0,
            connect_timeout=10.0,
            write_timeout=30.0,
            pool_timeout=5.0,
        )

    # Defaults (timeout chung) nếu phiên bản hỗ trợ
    defaults = _Defaults(timeout=30) if _HAS_DEFAULTS else None

    migrate_store()
    builder = Application.builder().token(BOT_TOKEN)
    if request is not None:
        builder = builder.request(request)
    if defaults is not None:
        builder = builder.defaults(defaults)

    app = builder.post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("find", cmd_find))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("removeall", cmd_removeall))
    app.add_handler(CommandHandler("ack", cmd_ack))
    app.add_handler(CommandHandler("unack", cmd_unack))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^(ack|unack):\d+$"))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Job queue
    if app.job_queue is None:
        jq = JobQueue(); jq.set_application(app); jq.start()
        jq.run_repeating(price_job, interval=CHECK_INTERVAL_SEC, first=3,
                         name="price_job",
                         job_kwargs={"max_instances":5,"coalesce":True,"misfire_grace_time":10})
    else:
        app.job_queue.run_repeating(price_job, interval=CHECK_INTERVAL_SEC, first=3,
                                    name="price_job",
                                    job_kwargs={"max_instances":5,"coalesce":True,"misfire_grace_time":10})
    app.run_polling()

if __name__ == "__main__":
    main()
