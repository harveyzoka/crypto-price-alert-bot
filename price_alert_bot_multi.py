#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Telegram Price Alert Bot — Multi-source (Binance → Bybit → CoinGecko)
# Lệnh:
#   /start /help /id /ping
#   /price <asset>     (vd: BTCUSDT | binance:EDENUSDT | bybit:EDENUSDT | cg:openeden)
#   /find <query>      (tìm CoinGecko ID)
#   /add <asset> >=|<= <price>
#   /list /remove <id> /removeall
#   /ack <id>          (xác nhận đã nhận cảnh báo để dừng lặp)
#
# .env (đặt cạnh file này):
#   BOT_TOKEN=...
#   CHECK_INTERVAL_SEC=10
#   ALARM_REPEAT=10
#   ALARM_GAP_SEC=2
#   ALARM_COOLDOWN_SEC=30
#   REARM_GAP_PCT=0.002
#   # ALLOWED_CHAT_IDS=123456789,-1001234567890   (tuỳ chọn)

import os, json, time, asyncio
from typing import Dict, Any, List, Tuple, Optional
import requests

from dotenv import load_dotenv
from telegram import (
    Update, BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters, JobQueue,
    CallbackQueryHandler
)

# ===== Load ENV =====
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHECK_INTERVAL_SEC = int(os.getenv("CHECK_INTERVAL_SEC", "10"))
ALARM_REPEAT = int(os.getenv("ALARM_REPEAT", "10"))              # số tin trong 1 đợt
ALARM_GAP_SEC = float(os.getenv("ALARM_GAP_SEC", "2"))           # giãn cách mỗi tin trong đợt (giây)
ALARM_COOLDOWN_SEC = int(os.getenv("ALARM_COOLDOWN_SEC", "30"))  # lặp lại đợt khi chưa ACK
REARM_GAP_PCT = float(os.getenv("REARM_GAP_PCT", "0.002"))       # 0.2% hysteresis để re-arm
ALLOWED_CHAT_IDS: List[int] = [int(x) for x in os.getenv("ALLOWED_CHAT_IDS", "").split(",") if x.strip().isdigit()]

DATA_FILE = "alerts.json"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "price-alert-bot/1.0"})

KNOWN_QUOTES = ["USDT", "USDC", "FDUSD", "BUSD", "BTC", "ETH"]

# ===== Persistent =====
def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        return {"alerts": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data: Dict[str, Any]):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)

# ===== Providers =====
def get_price_binance(symbol: str) -> float:
    r = SESSION.get("https://api.binance.com/api/v3/ticker/price",
                    params={"symbol": symbol.upper()}, timeout=6)
    r.raise_for_status()
    j = r.json()
    if "price" not in j: raise ValueError("Binance: invalid response")
    return float(j["price"])

def get_price_bybit(symbol: str) -> float:
    r = SESSION.get("https://api.bybit.com/v5/market/tickers",
                    params={"category": "spot", "symbol": symbol.upper()}, timeout=6)
    r.raise_for_status()
    j = r.json()
    if j.get("retCode") != 0 or not j.get("result") or not j["result"].get("list"):
        raise ValueError("Bybit: not found")
    price_str = j["result"]["list"][0].get("lastPrice")
    if not price_str: raise ValueError("Bybit: invalid price")
    return float(price_str)

def get_price_coingecko(coin_id: str) -> float:
    r = SESSION.get("https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": coin_id.lower(), "vs_currencies": "usd"}, timeout=8)
    r.raise_for_status()
    j = r.json()
    cid = coin_id.lower()
    if cid not in j or "usd" not in j[cid]: raise ValueError("CoinGecko: id not found or no usd")
    return float(j[cid]["usd"])

def search_coingecko(query: str) -> List[Dict[str, Any]]:
    r = SESSION.get("https://api.coingecko.com/api/v3/search", params={"query": query}, timeout=8)
    r.raise_for_status()
    coins = (r.json().get("coins") or [])[:10]
    return [{"id": c.get("id"), "name": c.get("name"), "symbol": c.get("symbol"), "market_cap_rank": c.get("market_cap_rank")} for c in coins]

# ===== Resolve helpers =====
def normalize_pair_base(symbol_raw: str) -> Optional[str]:
    """Nếu nhập 'EDEN' → thử EDENUSDT/USDC/FDUSD trên Binance/Bybit."""
    s = symbol_raw.upper()
    if any(s.endswith(q) for q in KNOWN_QUOTES): return s
    for q in ["USDT","USDC","FDUSD"]:
        cand = s + q
        try:
            _ = get_price_binance(cand); return cand
        except: pass
        try:
            _ = get_price_bybit(cand); return cand
        except: pass
    return None

def resolve_asset(raw: str) -> Tuple[str, str, str]:
    """
    Chuẩn hoá input về (src, code, display)
    src: 'binance' | 'bybit' | 'coingecko'
    code: symbol (binance/bybit) hoặc id (coingecko)
    """
    x = raw.strip()
    if ":" in x:
        pfx, body = x.split(":", 1)
        p = pfx.lower().strip(); b = body.strip()
        if p == "binance": _ = get_price_binance(b); return "binance", b.upper(), f"{b.upper()} (Binance)"
        if p == "bybit":   _ = get_price_bybit(b);   return "bybit",   b.upper(), f"{b.upper()} (Bybit)"
        if p in ("cg","coingecko"): _ = get_price_coingecko(b); return "coingecko", b.lower(), f"{b.lower()} (CoinGecko)"
        raise ValueError("Nguồn không hỗ trợ. Dùng binance: | bybit: | cg:")
    # Không prefix → thử Binance → Bybit → CoinGecko
    cand = normalize_pair_base(x)
    if cand:
        try:
            _ = get_price_binance(cand); return "binance", cand, f"{cand} (Binance)"
        except: pass
        _ = get_price_bybit(cand); return "bybit", cand, f"{cand} (Bybit)"
    cg_id = x.lower().replace(" ","-")
    _ = get_price_coingecko(cg_id)
    return "coingecko", cg_id, f"{cg_id} (CoinGecko)"

def get_price_resolved(src: str, code: str) -> float:
    if src == "binance":   return get_price_binance(code)
    if src == "bybit":     return get_price_bybit(code)
    if src == "coingecko": return get_price_coingecko(code)
    raise ValueError("Unknown source")

def parse_add(args: List[str]) -> Optional[Tuple[str,str,float]]:
    # /add <asset> >=|<= <value>
    if len(args)!=3 or args[1] not in (">=","<="): return None
    try: val = float(args[2])
    except: return None
    return args[0], args[1], val

def next_id(alerts: List[Dict[str,Any]]) -> int:
    return 1 + max([a["id"] for a in alerts], default=0)

def allowed(update: Update) -> bool:
    return not ALLOWED_CHAT_IDS or (update.effective_chat and update.effective_chat.id in ALLOWED_CHAT_IDS)

# ===== Migration (tự chuyển alerts cũ) =====
def migrate_alert(a: Dict[str,Any]) -> Optional[Dict[str,Any]]:
    if all(k in a for k in ("src","code","display","op","value")): return a
    raw = a.get("symbol") or a.get("display") or a.get("asset")
    if not raw: return None
    try:
        src, code, disp = resolve_asset(str(raw))
        a["src"], a["code"], a["display"] = src, code, disp
        a["op"] = a.get("op") or a.get("operator")
        a["value"] = a.get("value") or a.get("target")
        a.setdefault("triggered", False)
        a.setdefault("last_price", None)
        a.setdefault("last_fired", 0)
        a.setdefault("ack", False)
        for k in ("symbol","asset","operator","target"): a.pop(k, None)
        if a.get("op") not in (">=","<=") or not isinstance(a.get("value"), (int,float)): return None
        return a
    except: return None

def migrate_store():
    data = load_data(); changed = False
    for chat_id, alerts in list(data.get("alerts", {}).items()):
        newalerts = []
        for a in alerts:
            ma = migrate_alert(a)
            if ma: newalerts.append(ma); changed |= (ma is not a)
            else: changed = True
        data["alerts"][chat_id] = newalerts
    if changed: save_data(data)

# ===== Burst sender (10 tin, cách 2s; tin đầu có nút ACK) =====
async def send_burst(bot, chat_id: int, text: str, alert_id: int):
    try:
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"✅ Đã nhận cảnh báo #{alert_id}", callback_data=f"ack:{alert_id}")]]
        )
        await bot.send_message(chat_id=chat_id, text=text, disable_notification=False, reply_markup=kb)
    except Exception:
        pass

    for _ in range(max(0, ALARM_REPEAT - 1)):
        await asyncio.sleep(ALARM_GAP_SEC)
        try:
            await bot.send_message(chat_id=chat_id, text=text, disable_notification=False)
        except Exception:
            pass

# ===== Commands =====
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    await update.message.reply_text(
        "Bot cảnh báo giá đa nguồn 📈\n\n"
        "/help — hướng dẫn\n/id — chat_id\n"
        "/price <asset> (BTCUSDT | binance:EDENUSDT | cg:openeden)\n"
        "/find <tên> — tìm CoinGecko ID\n"
        "/add <asset> >=|<= <giá>\n/list — liệt kê\n/remove <id> — xoá\n/removeall — xoá hết\n"
        "/ack <id> — xác nhận đã nhận cảnh báo để dừng lặp"
    )

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    await update.message.reply_text(
        "📘 Hướng dẫn\n"
        "• /price BTCUSDT | binance:EDENUSDT | cg:openeden\n"
        "• /find eden → gợi ý CoinGecko ID\n"
        "• /add <asset> >=|<= <giá>  (vd: /add BTCUSDT >= 65000 | /add cg:openeden <= 0.47)\n"
        "• /list, /remove <id>, /removeall\n"
        "• /ack <id> để dừng lặp cảnh báo đang nổ\n"
        "Mặc định thêm biên REARM_GAP_PCT để tránh rung ngưỡng."
    )

async def cmd_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"chat_id: {update.effective_chat.id}")

async def cmd_ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    await update.message.reply_text("✅ Bot đang chạy")

async def cmd_find(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    if not ctx.args: return await update.message.reply_text("Dùng: /find <tên hoặc symbol>")
    try:
        rows = search_coingecko(" ".join(ctx.args))
        if not rows: return await update.message.reply_text("Không thấy trên CoinGecko.")
        s = "\n".join([f"- {r['id']} | {r['symbol'].upper()} | {r['name']} (rank={r['market_cap_rank']})" for r in rows])
        await update.message.reply_text("Gợi ý CoinGecko ID:\n"+s)
    except Exception as e:
        await update.message.reply_text(f"Lỗi CoinGecko: {e}")

async def cmd_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    if not ctx.args: return await update.message.reply_text("Dùng: /price <asset>")
    try:
        src, code, disp = resolve_asset(" ".join(ctx.args))
        price = get_price_resolved(src, code)
        await update.message.reply_text(f"💱 {disp} = {price}")
    except Exception as e:
        await update.message.reply_text(f"❌ Không lấy được giá: {e}\nThử binance:<symbol> | bybit:<symbol> | cg:<id> hoặc /find <tên>.")

async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    p = parse_add(ctx.args)
    if not p: return await update.message.reply_text("Cú pháp: /add <asset> >=|<= <giá>")
    asset, op, val = p
    try:
        src, code, disp = resolve_asset(asset)
        _ = get_price_resolved(src, code)  # validate
    except Exception as e:
        return await update.message.reply_text(f"❌ Không thêm được: {e}\nDùng /price để kiểm tra trước, hoặc /find để lấy id.")

    chat_id = str(update.effective_chat.id)
    data = load_data(); data["alerts"].setdefault(chat_id, [])
    new = {"id": next_id(data["alerts"][chat_id]), "src": src, "code": code, "display": disp,
           "op": op, "value": val, "triggered": False, "last_price": None, "last_fired": 0, "ack": False}
    data["alerts"][chat_id].append(new); save_data(data)
    await update.message.reply_text(f"✅ Đã thêm #{new['id']}: {disp} {op} {val}")

async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    data = load_data(); alerts = data["alerts"].get(str(update.effective_chat.id), [])
    if not alerts: return await update.message.reply_text("Chưa có cảnh báo nào.")
    s = "\n".join([
        f"#{a['id']}: {a['display']} {a['op']} {a['value']} (fired={a['triggered']}, ack={a.get('ack', False)})"
        for a in alerts
    ])
    await update.message.reply_text("Danh sách cảnh báo:\n"+s)

async def cmd_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    if not ctx.args: return await update.message.reply_text("Dùng: /remove <id>")
    try: rid = int(ctx.args[0])
    except: return await update.message.reply_text("ID phải là số.")
    data = load_data(); cid = str(update.effective_chat.id)
    alerts = data["alerts"].get(cid, []); newalerts = [a for a in alerts if a["id"] != rid]
    if len(newalerts)==len(alerts): return await update.message.reply_text(f"Không thấy ID #{rid}.")
    data["alerts"][cid] = newalerts; save_data(data)
    await update.message.reply_text(f"🗑️ Đã xoá #{rid}.")

async def cmd_removeall(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): return
    cid = str(update.effective_chat.id)
    data = load_data(); data["alerts"][cid] = []; save_data(data)
    await update.message.reply_text("🧹 Đã xoá tất cả cảnh báo.")

async def cmd_ack(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Dùng: /ack <id>")
    try:
        rid = int(ctx.args[0])
    except:
        return await update.message.reply_text("ID phải là số.")
    chat_id = str(update.effective_chat.id)
    data = load_data()
    alerts = data["alerts"].get(chat_id, [])
    for a in alerts:
        if a.get("id") == rid:
            a["ack"] = True
            save_data(data)
            return await update.message.reply_text(f"🛑 Đã nhận cảnh báo #{rid}. Dừng lặp.")
    await update.message.reply_text(f"Không thấy ID #{rid}.")

async def on_ack_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        rid = int(q.data.split(":")[1])  # ack:<id>
    except Exception:
        return
    chat_id = str(q.message.chat.id)
    data = load_data()
    alerts = data["alerts"].get(chat_id, [])
    for a in alerts:
        if a.get("id") == rid:
            a["ack"] = True
            save_data(data)
            try:
                await q.edit_message_text(f"🛑 Đã nhận cảnh báo #{rid}. Dừng lặp.")
            except Exception:
                pass
            return

# ===== Price job =====
async def price_job(context: ContextTypes.DEFAULT_TYPE):
    now = time.time()
    data = load_data()

    # Gom theo (src, code) để giảm số request
    groups: Dict[Tuple[str,str], List[Dict[str,Any]]] = {}
    for chat_id, alerts in data.get("alerts", {}).items():
        for a in alerts:
            if not all(k in a for k in ("src","code","op","value")): continue
            key = (a["src"], a["code"])
            groups.setdefault(key, []).append({"chat_id": chat_id, "alert": a})

    for (src, code), items in groups.items():
        try:
            price = get_price_resolved(src, code)
        except Exception:
            continue

        for item in items:
            chat_id = item["chat_id"]; a = item["alert"]
            a["last_price"] = price

            # điều kiện + hysteresis để re-arm
            cond = (price >= a["value"]) if a["op"] == ">=" else (price <= a["value"])
            if a["op"] == ">=":
                back = price <= a["value"] * (1 - REARM_GAP_PCT)
            else:
                back = price >= a["value"] * (1 + REARM_GAP_PCT)
            if back:
                a["triggered"] = False
                a["ack"] = False  # reset ACK khi giá quay về phía ngược

            should_fire = False
            # 1) Lần đầu vượt mốc & chưa ACK → bắn ngay
            if cond and not a["triggered"] and not a.get("ack", False):
                should_fire = True
            # 2) Vẫn đang thỏa & chưa ACK → lặp lại sau cooldown
            elif cond and not a.get("ack", False) and (now - a.get("last_fired", 0) >= ALARM_COOLDOWN_SEC):
                should_fire = True

            if should_fire:
                a["triggered"] = True
                a["last_fired"] = now
                save_data(data)
                text = f"🚨 {a['display']} {a['op']} {a['value']} — Giá: {price}"
                await send_burst(context.bot, int(chat_id), text, a["id"])

    save_data(data)

# ===== Post-init: commands hint =====
async def post_init(app: Application):
    cmds_private = [
        BotCommand("help","Hướng dẫn"), BotCommand("id","Lấy chat_id"),
        BotCommand("price","Xem giá nhanh"), BotCommand("find","Tìm CoinGecko ID"),
        BotCommand("add","Thêm cảnh báo"), BotCommand("list","Liệt kê cảnh báo"),
        BotCommand("remove","Xoá theo ID"), BotCommand("removeall","Xoá tất cả"),
        BotCommand("ack","Dừng lặp cảnh báo"), BotCommand("ping","Kiểm tra bot"),
    ]
    await app.bot.set_my_commands(cmds_private, scope=BotCommandScopeAllPrivateChats())

    cmds_group = [
        BotCommand("price","Xem giá"), BotCommand("add","Thêm cảnh báo"),
        BotCommand("list","Liệt kê"), BotCommand("remove","Xoá ID"),
        BotCommand("removeall","Xoá hết"), BotCommand("ack","Dừng lặp"),
        BotCommand("ping","Kiểm tra"),
    ]
    await app.bot.set_my_commands(cmds_group, scope=BotCommandScopeAllGroupChats())

async def unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text and update.message.text.startswith("/"):
        await update.message.reply_text("❓ Lệnh không hợp lệ. Gõ /help để xem hướng dẫn.")

# ===== Main =====
def main():
    if not BOT_TOKEN:
        raise SystemExit("⚠️ BOT_TOKEN trống. Điền vào .env.")

    migrate_store()  # chuyển dữ liệu cũ (nếu có)

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("find", cmd_find))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("removeall", cmd_removeall))
    app.add_handler(CommandHandler("ack", cmd_ack))
    app.add_handler(CallbackQueryHandler(on_ack_button, pattern=r"^ack:\d+$"))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    if app.job_queue is None:
        jq = JobQueue(); jq.set_application(app); jq.start()
        jq.run_repeating(price_job, interval=CHECK_INTERVAL_SEC, first=3)
    else:
        app.job_queue.run_repeating(price_job, interval=CHECK_INTERVAL_SEC, first=3)

    app.run_polling()

if __name__ == "__main__":
    main()
