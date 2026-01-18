import os
import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# --- CONFIGURACIÓN ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Falta la variable de entorno BOT_TOKEN.")
ADMIN_IDS = [5496321016, 111111111, 222222222] # Agrega aquí los 4 IDs

PENDING = {}  # Datos del envío
OPERADOR_ESTADO = {} 
ADMIN_WAITING_REASON = {} 

OPCIONES_MENU = ["🧊 Rompehielos", "📝 Carta", "📱 New Feed", "🎤 Nota de voz", "📎 Adjunto"]

# --- UTILIDADES ---
def extract_preview(msg) -> str:
    text = msg.text or msg.caption or ""
    if not text:
        if msg.photo: return "📷 [Foto]"
        if msg.voice: return "🎤 [Nota de voz]"
        return "📦 [Adjunto]"
    return (text[:40] + "...") if len(text) > 40 else text

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        await update.message.reply_text("👮 Modo ADMIN multi-usuario activo.")
    else:
        await update.message.reply_text("👋 Elige tipo de contenido:", reply_markup=ReplyKeyboardMarkup([["🧊 Rompehielos", "📝 Carta"], ["📱 New Feed", "🎤 Nota de voz"], ["📎 Adjunto"]], resize_keyboard=True))

async def handle_any_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.message

    # SI ES UN ADMIN ESCRIBIENDO MOTIVO
    if user.id in ADMIN_IDS and user.id in ADMIN_WAITING_REASON:
        data = ADMIN_WAITING_REASON[user.id]
        op_chat_id = data["operator_chat_id"]
        accion_label = "DECLINADO ❌" if data["action"] == "decline" else "PARA MODIFICAR ✏️"
        
        # Notificar al operador
        await context.bot.send_message(
            chat_id=op_chat_id,
            text=f"Tu envío ha sido {accion_label}\n📌 **Contenido:** {data['preview']}\n💬 **Motivo:** {msg.text}",
            parse_mode="Markdown"
        )
        await msg.reply_text(f"✅ Motivo enviado. El contenido ha quedado cerrado.")
        del ADMIN_WAITING_REASON[user.id]
        return

    if user.id in ADMIN_IDS: return

    # SI ES OPERADOR ENVIANDO CONTENIDO
    if user.id not in OPERADOR_ESTADO:
        if msg.text in OPCIONES_MENU:
            OPERADOR_ESTADO[user.id] = msg.text
            await msg.reply_text(f"Has seleccionado {msg.text}. Envíalo ahora:", reply_markup=ReplyKeyboardRemove())
        else:
            await msg.reply_text("⚠️ Selecciona una categoría primero.")
        return

    tipo = OPERADOR_ESTADO[user.id]
    preview = extract_preview(msg)
    
    # Generar un ID único interno para este envío (usamos el timestamp)
    internal_id = f"{user.id}_{datetime.datetime.now().timestamp()}"
    
    await msg.reply_text(f"📩 Tu {tipo} ha sido enviado a los moderadores.")

    # Enviar a todos los admins
    for admin_id in ADMIN_IDS:
        try:
            sent_fwd = await context.bot.forward_message(admin_id, msg.chat_id, msg.message_id)
            keyboard = [[
                InlineKeyboardButton("✅ Aprobar", callback_data=f"app_{internal_id}"),
                InlineKeyboardButton("❌ Declinar", callback_data=f"dec_{internal_id}")
            ], [InlineKeyboardButton("✏️ Modificar", callback_data=f"mod_{internal_id}")]]

            # Guardamos cada mensaje enviado a cada admin relacionado al mismo ID interno
            kb_msg = await sent_fwd.reply_text(
                f"📨 **NUEVO:** {tipo}\nDe: {user.full_name}\nResumen: {preview}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            
            # PENDING ahora guarda el estado global por internal_id
            if internal_id not in PENDING:
                PENDING[internal_id] = {
                    "operator_chat_id": msg.chat_id,
                    "preview": preview,
                    "content_type": tipo,
                    "status": "pending",
                    "moderated_by": None,
                    "admin_messages": [] # Lista para rastrear todos los mensajes de botones enviados
                }
            PENDING[internal_id]["admin_messages"].append((admin_id, kb_msg.message_id))
            
        except Exception as e: print(f"Error admin {admin_id}: {e}")
    
    del OPERADOR_ESTADO[user.id]

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    admin = query.from_user
    data_parts = query.data.split("_")
    action_code = data_parts[0] # app, dec, mod
    internal_id = "_".join(data_parts[1:])
    
    info = PENDING.get(internal_id)

    # 1. VERIFICAR SI YA FUE MODERADO
    if not info or info["status"] != "pending":
        moderador = info["moderated_by"] if info else "alguien"
        await query.edit_message_text(f"⚠️ Este contenido ya fue procesado por {moderador}.")
        return

    # 2. PROCESAR ACCIÓN
    if action_code == "app":
        info["status"] = "completed"
        info["moderated_by"] = admin.full_name
        
        # Notificar operador
        await context.bot.send_message(
            chat_id=info["operator_chat_id"],
            text=f"🎉 Tu {info['content_type']} fue APROBADO ✅\n📌 Contenido: {info['preview']}\n👮 Moderado por: {admin.full_name}"
        )
        
        # Actualizar mensajes de TODOS los admins para que sepan que ya se cerró
        for adm_id, msg_id in info["admin_messages"]:
            try:
                await context.bot.edit_message_text(
                    chat_id=adm_id,
                    message_id=msg_id,
                    text=f"✅ **APROBADO** por {admin.full_name}\nContenido: {info['preview']}"
                )
            except: pass
        
    elif action_code in ["dec", "mod"]:
        info["status"] = "waiting_reason"
        info["moderated_by"] = admin.full_name
        
        # Bloquear para el admin que presionó el botón
        ADMIN_WAITING_REASON[admin.id] = {
            "operator_chat_id": info["operator_chat_id"],
            "action": "decline" if action_code == "dec" else "modify",
            "preview": info["preview"]
        }
        
        # Actualizar el mensaje del admin que está escribiendo
        await query.edit_message_text(f"✍️ Estás procesando este contenido. Escribe el motivo:")
        
        # Actualizar mensajes de los OTROS admins para que no toquen nada
        for adm_id, msg_id in info["admin_messages"]:
            if adm_id != admin.id:
                try:
                    await context.bot.edit_message_text(
                        chat_id=adm_id,
                        message_id=msg_id,
                        text=f"⏳ {admin.full_name} está escribiendo un motivo para este contenido..."
                    )
                except: pass

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, handle_any_message))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.run_polling()

if __name__ == "__main__":
    main()
