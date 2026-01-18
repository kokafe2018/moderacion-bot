import os
from telegram.ext import Application, MessageHandler, filters

async def detect_id(update, context):
    # Esto detectará cualquier mensaje que llegue al bot desde el canal
    if update.channel_post:
        print(f"\n✅ ID DEL CANAL DETECTADO: {update.channel_post.chat_id}")
        print(f"Copia este número y ponlo en tu configuración.\n")

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("Debes definir la variable de entorno BOT_TOKEN para usar get_id.py")

    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, detect_id))
    print("🚀 Esperando mensaje en el canal... (Escribe algo en tu canal ahora)")
    app.run_polling()

if __name__ == "__main__":
    main()
