import os
import sqlite3
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# =========================
# Config (ENV VARS)
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "").strip()  # ex: -1001234567890

# Checkout links (crie no painel do SyncPay)
MENSAL_URL = os.getenv("MENSAL_URL", "").strip()
ANUAL_URL = os.getenv("ANUAL_URL", "").strip()

# SyncPay Partner API (para evoluir a automação por webhook)
SYNC_CLIENT_ID = os.getenv("SYNC_CLIENT_ID", "").strip()
SYNC_CLIENT_SECRET = os.getenv("SYNC_CLIENT_SECRET", "").strip()

# Segredo simples para proteger seu endpoint de webhook
SYNC_WEBHOOK_SECRET = os.getenv("SYNC_WEBHOOK_SECRET", "").strip()

DB_PATH = os.getenv("DB_PATH", "data.sqlite3").strip()

# =========================
# SQLite (bem simples)
# =========================
def _conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER NOT NULL,
            plan TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            created_at TEXT NOT NULL,
            paid_at TEXT,
            sync_transaction_id TEXT
        )
        """
    )
    conn.commit()
    return conn

CONN = _conn()

def create_order(telegram_user_id: int, plan: str) -> int:
    cur = CONN.cursor()
    cur.execute(
        "INSERT INTO orders (telegram_user_id, plan, status, created_at) VALUES (?, ?, 'PENDING', datetime('now'))",
        (telegram_user_id, plan),
    )
    CONN.commit()
    return int(cur.lastrowid)

def is_paid(order_id: int) -> bool:
    row = CONN.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()
    return bool(row and row[0] == "PAID")

def mark_paid(order_id: int, sync_tx_id: str = "") -> None:
    CONN.execute(
        "UPDATE orders SET status='PAID', paid_at=datetime('now'), sync_transaction_id=? WHERE id=?",
        (sync_tx_id, order_id),
    )
    CONN.commit()

# =========================
# SyncPay token helper (docs: POST /api/partner/v1/auth-token)
# =========================
async def sync_bearer_token() -> str:
    if not (SYNC_CLIENT_ID and SYNC_CLIENT_SECRET):
        raise RuntimeError("Faltou SYNC_CLIENT_ID / SYNC_CLIENT_SECRET")
    url = "https://syncpay.apidog.io/api/partner/v1/auth-token"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, json={"client_id": SYNC_CLIENT_ID, "client_secret": SYNC_CLIENT_SECRET})
        r.raise_for_status()
        data = r.json()
        token = data.get("token") or data.get("access_token") or data.get("data", {}).get("token")
        if not token:
            raise RuntimeError(f"Token não encontrado: {data}")
        return token

# =========================
# Telegram bot
# =========================
def plan_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 Mensal — R$ 19,99", callback_data="plan:mensal")],
        [InlineKeyboardButton("👑 Anual — R$ 197,00", callback_data="plan:anual")],
        [InlineKeyboardButton("📩 Já paguei (chamar suporte)", callback_data="support")]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        "🔥 *Bem-vindo ao Anônimo Prime* 🔥\n\n"
        "Escolha um plano abaixo. Após a confirmação do pagamento, o acesso ao grupo VIP é liberado automaticamente."
    )
    await update.effective_message.reply_text(msg, parse_mode="Markdown", reply_markup=plan_keyboard())

async def support_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    await q.message.reply_text("🆘 Suporte: fale com @SEUUSUARIO (troque aqui).")

async def plan_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    plan = q.data.split(":", 1)[1]

    if plan == "mensal":
        order_id = create_order(user_id, "MENSAL")
        pay_url = MENSAL_URL
        label = "MENSAL"
        price = "R$ 19,99"
    else:
        order_id = create_order(user_id, "ANUAL")
        pay_url = ANUAL_URL
        label = "ANUAL"
        price = "R$ 197,00"

    if not pay_url:
        await q.message.reply_text("⚠️ Link de pagamento não configurado no servidor (MENSAL_URL / ANUAL_URL).")
        return


    await q.message.reply_text(
        f"✅ Plano *{label}* selecionado.\n\n"
        "1) Clique em *Pagar* e conclua o checkout.\n"
        "2) Volte aqui e toque em *Já paguei (verificar)*.\n\n"
        f"Pedido: `#{order_id}`",
        parse_mode="Markdown",
        reply_markup=kb
    )

async def check_payment_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()

    order_id = q.data.split(":")[1]
    user = q.from_user

    # avisa o usuário
    await q.message.reply_text(
        "📨 Pedido enviado ao suporte!\n\n"
        "Aguarde alguns minutos enquanto conferimos seu pagamento."
    )

    # avisa VOCÊ (admin)
    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=(
            "🆘 *SOLICITAÇÃO DE CONFERÊNCIA DE PAGAMENTO*\n\n"
            f"👤 Usuário: {user.full_name}\n"
            f"🆔 ID: `{user.id}`\n"
            f"📦 Pedido: #{order_id}\n\n"
            "👉 Conferir pagamento e liberar acesso manualmente."
        ),
        parse_mode="Markdown"
    )

# =========================
# FastAPI webhook receiver (evolução)
# =========================
app = FastAPI()

@app.post("/syncpay/webhook")
async def syncpay_webhook(request: Request):
    print("=== WEBHOOK CHEGOU ===")
    print("HEADERS:", dict(request.headers))
    payload = await request.json()
    print("PAYLOAD:", payload)
    return JSONResponse({"received": True})

telegram_app: Optional[Application] = None

@app.on_event("startup")
async def on_startup():
    global telegram_app
    if not BOT_TOKEN:
        raise RuntimeError("Faltou BOT_TOKEN")
    telegram_app = Application.builder().token(BOT_TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CallbackQueryHandler(plan_cb, pattern=r"^plan:"))
    telegram_app.add_handler(CallbackQueryHandler(check_payment_cb, pattern=r"^check:"))
    telegram_app.add_handler(CallbackQueryHandler(support_cb, pattern=r"^support$"))

    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling()

@app.on_event("shutdown")
async def on_shutdown():
    global telegram_app
    if telegram_app:
        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()
