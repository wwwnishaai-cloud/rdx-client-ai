import uuid
from telegram import Update, Bot
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes

active_bots: dict[str, Application] = {}


async def register_bot(user_id: str, token: str) -> tuple[bool, str]:
    if user_id in active_bots:
        old_app = active_bots[user_id]
        await old_app.shutdown()
        del active_bots[user_id]

    session_tokens: dict[int, str] = {}

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return
        chat_id = update.message.chat_id
        user_text = update.message.text

        if user_text.startswith("/"):
            return

        sess_token = session_tokens.get(chat_id, uuid.uuid4().hex)
        session_tokens[chat_id] = sess_token

        async def send_streaming():
            import httpx
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream(
                    "POST",
                    "http://localhost:8001/api/chat",
                    json={
                        "message": user_text,
                        "platform": "telegram",
                        "session_token": sess_token,
                        "platform_user_id": str(chat_id),
                    },
                ) as response:
                    if response.status_code != 200:
                        await update.message.reply_text("Error talking to AI server")
                        return

                    full = ""
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            import json
                            try:
                                data = json.loads(line[6:])
                                if data.get("done"):
                                    session_tokens[chat_id] = data.get("session_token", sess_token)
                                    continue
                                full += data.get("content", "")
                            except json.JSONDecodeError:
                                pass

                    chunks = [full[i:i+4096] for i in range(0, len(full), 4096)]
                    for chunk in chunks:
                        await update.message.reply_text(chunk, parse_mode="Markdown")

        import asyncio
        asyncio.create_task(send_streaming())

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 *RDX AI Telegram Bot*\n\n"
            "Send me a message and I'll reply!\n"
            "Commands:\n"
            "/ask `<question>` - Ask AI\n"
            "/clear - Clear session\n"
            "/model `<name>` - Switch model",
            parse_mode="Markdown",
        )

    async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
        question = " ".join(context.args) if context.args else "Hello"
        chat_id = update.message.chat_id
        sess_token = session_tokens.get(chat_id, uuid.uuid4().hex)
        session_tokens[chat_id] = sess_token

        import httpx
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                "http://localhost:8001/api/chat",
                json={
                    "message": question,
                    "platform": "telegram",
                    "session_token": sess_token,
                    "platform_user_id": str(chat_id),
                },
            ) as response:
                if response.status_code != 200:
                    await update.message.reply_text("Error")
                    return

                full = ""
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        import json
                        try:
                            data = json.loads(line[6:])
                            if data.get("done"):
                                session_tokens[chat_id] = data.get("session_token", sess_token)
                                continue
                            full += data.get("content", "")
                        except json.JSONDecodeError:
                            pass
                await update.message.reply_text(full[:4096], parse_mode="Markdown")

    async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat_id
        session_tokens.pop(chat_id, None)
        await update.message.reply_text("Session cleared! ✅")

    async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /model `<model_name>`")
            return
        await update.message.reply_text(f"Model switched to {' '.join(context.args)}")

    builder = Application.builder().token(token).build()
    builder.add_handler(CommandHandler("start", start))
    builder.add_handler(CommandHandler("ask", cmd_ask))
    builder.add_handler(CommandHandler("clear", cmd_clear))
    builder.add_handler(CommandHandler("model", cmd_model))
    builder.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    try:
        await builder.initialize()
        await builder.start()
        await builder.updater.start_polling()
        active_bots[user_id] = builder
        return True, "Telegram bot connected successfully!"
    except Exception as e:
        return False, f"Failed to connect Telegram bot: {str(e)}"
