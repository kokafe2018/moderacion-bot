import os
import sqlite3
import random
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# --- CONFIGURACIÓN ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
raw_channel_id = os.getenv("MODERATION_CHANNEL_ID")

missing_env = []
if not BOT_TOKEN:
    missing_env.append("BOT_TOKEN")
if raw_channel_id is None:
    missing_env.append("MODERATION_CHANNEL_ID")

if missing_env:
    raise RuntimeError(f"Faltan variables de entorno: {', '.join(missing_env)}.")

try:
    MODERATION_CHANNEL_ID = int(raw_channel_id)
except ValueError:
    raise RuntimeError("MODERATION_CHANNEL_ID debe ser un número (chat_id del canal).")
OPCIONES_MENU = ["🧊 Rompehielos", "📝 Carta", "📱 New Feed", "🎤 Nota de voz", "📎 Adjunto"]

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def start_health_server():
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

# --- BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect('moderacion.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS solicitudes 
                     (msg_id TEXT PRIMARY KEY, user_id INTEGER, preview TEXT, categoria TEXT, ticket_id TEXT)''')
    conn.commit()
    conn.close()

# --- MANEJADORES ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hola. Selecciona una categoría:", 
        reply_markup=ReplyKeyboardMarkup([["🧊 Rompehielos", "📝 Carta"], ["📱 New Feed", "🎤 Nota de voz"], ["📎 Adjunto"]], resize_keyboard=True))

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    user_id = update.effective_user.id

    # 1. PROCESAR RECHAZO (ADMIN ESCRIBIENDO MOTIVO)
    esperando = context.bot_data.get("esperando_motivo", {})
    if user_id in esperando:
        data = esperando[user_id]
        texto_rechazo = (
            f"❌ **ENVÍO RECHAZADO**\n"
            f"🎫 **Ticket:** `{data['ticket']}`\n"
            f"📂 **Categoría:** {data['cat']}\n"
            f"💬 **Motivo:** {msg.text}"
        )
        try:
            await context.bot.send_message(chat_id=data['op_id'], text=texto_rechazo, parse_mode="Markdown")
            await msg.reply_text(f"✅ Motivo para el Ticket `{data['ticket']}` enviado con éxito.")
            
            conn = sqlite3.connect('moderacion.db')
            conn.execute('DELETE FROM solicitudes WHERE msg_id = ?', (data['msg_id'],))
            conn.commit()
            conn.close()
        except Exception as e:
            await msg.reply_text(f"⚠️ Error: {e}")
            
        del esperando[user_id]
        context.bot_data["esperando_motivo"] = esperando
        return

    # 2. SELECCIÓN CATEGORÍA (OPERADOR)
    if msg.text in OPCIONES_MENU:
        context.user_data['temp_cat'] = msg.text
        await msg.reply_text(f"Elegiste {msg.text}. Envía el contenido ahora:", reply_markup=ReplyKeyboardRemove())
        return

    # 3. ENVÍO AL CANAL CON TICKET
    if 'temp_cat' in context.user_data:
        if not (msg.text or msg.caption or msg.photo or msg.document or msg.audio or msg.video or msg.voice or msg.animation or msg.sticker):
            await msg.reply_text("⚠️ No se reconoce contenido válido para enviar a moderación. Envía texto o algún tipo de archivo soportado.")
            return

        cat = context.user_data['temp_cat']
        ticket_id = f"TK-{random.randint(1000, 9999)}"
        preview = (msg.text or msg.caption or "Multimedia")[:35]
        
        fwd = await context.bot.forward_message(MODERATION_CHANNEL_ID, msg.chat_id, msg.message_id)
        
        texto_panel = (
            f"🎫 **TICKET:** `{ticket_id}`\n"
            f"🏷 **Categoría:** {cat}\n"
            f"👤 **De:** {update.effective_user.full_name}\n"
            f"📝 **Vista:** {preview}..."
        )
        
        btns = [[InlineKeyboardButton("✅ Aprobar", callback_data=f"ok_{fwd.message_id}"),
                 InlineKeyboardButton("❌ Rechazar", callback_data=f"no_{fwd.message_id}")]]
        
        await context.bot.send_message(MODERATION_CHANNEL_ID, texto_panel, 
                                      reply_markup=InlineKeyboardMarkup(btns), parse_mode="Markdown")
        
        conn = sqlite3.connect('moderacion.db')
        conn.execute('INSERT INTO solicitudes VALUES (?, ?, ?, ?, ?)', 
                     (str(fwd.message_id), user_id, preview, cat, ticket_id))
        conn.commit()
        conn.close()
        
        await msg.reply_text(f"📩 Enviado a moderación.\n🎫 **Tu Ticket es:** `{ticket_id}`")
        del context.user_data['temp_cat']

        return

    await msg.reply_text("⚠️ Primero usa /start y elige una categoría del menú para enviar contenido.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, msg_id = query.data.split("_")
    
    conn = sqlite3.connect('moderacion.db')
    data = conn.execute('SELECT * FROM solicitudes WHERE msg_id = ?', (msg_id,)).fetchone()
    
    if not data:
        await query.edit_message_text("⚠️ No encontrado o ya procesado.")
        conn.close()
        return

    # data = (msg_id, user_id, preview, cat, ticket_id)
    op_id, cat, ticket = data[1], data[3], data[4]

    if action == "ok":
        await context.bot.send_message(op_id, f"✅ **ENVÍO APROBADO**\n🎫 **Ticket:** `{ticket}`\n📂 **Categoría:** {cat}", parse_mode="Markdown")
        await query.edit_message_text(f"✅ APROBADO: `{ticket}` (Admin: {query.from_user.first_name})")
        conn.execute('DELETE FROM solicitudes WHERE msg_id = ?', (msg_id,))
        conn.commit()
    
    elif action == "no":
        if "esperando_motivo" not in context.bot_data:
            context.bot_data["esperando_motivo"] = {}
            
        context.bot_data["esperando_motivo"][query.from_user.id] = {
            'op_id': op_id, 'cat': cat, 'msg_id': msg_id, 'ticket': ticket
        }
        
        bot_info = await context.bot.get_me()
        url_bot = f"https://t.me/{bot_info.username}"
        
        # REINTEGRAMOS EL BOTÓN DE ENLACE AL PRIVADO
        btn_privado = [[InlineKeyboardButton("💬 Ir al Chat para escribir motivo", url=url_bot)]]
        
        await query.edit_message_text(
            f"❌ **RECHAZANDO TICKET:** `{ticket}`\n"
            f"⚠️ Pulsa el botón de abajo para enviar el motivo por mi chat privado.",
            reply_markup=InlineKeyboardMarkup(btn_privado),
            parse_mode="Markdown"
        )
        
        # Enviar el aviso al privado del admin por si ya lo tiene abierto
        await context.bot.send_message(query.from_user.id, f"📝 **Motivo de rechazo**\n🎫 Ticket: `{ticket}`\n📂 Categoría: {cat}\n\nEscribe el motivo aquí debajo:")

    conn.close()

def main():
    init_db()
    Thread(target=start_health_server, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, handle_messages))
    app.add_handler(CallbackQueryHandler(callback_handler))
    print("🚀 Bot Activo (Tickets + Botón de enlace).")
    app.run_polling()

if __name__ == "__main__":
    main()
