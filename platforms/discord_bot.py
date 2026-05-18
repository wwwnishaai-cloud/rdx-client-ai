import uuid
import discord
from discord.ext import commands
from typing import Optional

active_bots: dict[str, commands.Bot] = {}


async def register_bot(user_id: str, token: str) -> tuple[bool, str]:
    if user_id in active_bots:
        old_bot = active_bots[user_id]
        await old_bot.close()
        del active_bots[user_id]

    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    session_tokens: dict[int, str] = {}

    @bot.event
    async def on_ready():
        print(f"[Discord Bot] {bot.user} is online for user {user_id}")

    @bot.event
    async def on_message(message):
        if message.author.bot:
            return

        if isinstance(message.channel, discord.DMChannel):
            await handle_message(
                user_id, message, bot, session_tokens
            )
        elif bot.user in message.mentions:
            await handle_message(
                user_id, message, bot, session_tokens
            )

    @bot.tree.command(name="ask", description="Ask RDX AI a question")
    async def ask(interaction: discord.Interaction, question: str):
        await interaction.response.defer()
        msg = await handle_ask(user_id, question, interaction.user.id, session_tokens)
        await interaction.followup.send(msg[:2000] if len(msg) > 2000 else msg)

    @bot.tree.command(name="clear", description="Clear your chat session")
    async def clear(interaction: discord.Interaction):
        session_tokens.pop(interaction.user.id, None)
        await interaction.response.send_message("Session cleared! ✅")

    @bot.tree.command(name="model", description="Switch AI model")
    async def model(interaction: discord.Interaction, model_name: str):
        sess_token = session_tokens.get(interaction.user.id, uuid.uuid4().hex)
        session_tokens[interaction.user.id] = sess_token
        await interaction.response.send_message(f"Model switched to {model_name}")

    try:
        await bot.start(token)
        active_bots[user_id] = bot
        return True, f"Discord bot connected successfully as {bot.user}"
    except Exception as e:
        return False, f"Failed to connect Discord bot: {str(e)}"


async def handle_message(
    user_id: str,
    message: discord.Message,
    bot: commands.Bot,
    session_tokens: dict,
):
    if message.content.startswith("!"):
        return

    sess_token = session_tokens.get(message.author.id, uuid.uuid4().hex)
    session_tokens[message.author.id] = sess_token

    async with message.channel.typing():
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                f"http://localhost:8001/api/chat",
                json={
                    "message": message.content,
                    "platform": "discord",
                    "session_token": sess_token,
                    "platform_user_id": str(message.author.id),
                },
            ) as response:
                if response.status_code != 200:
                    await message.channel.send("Error talking to AI server")
                    return

                full = ""
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        import json
                        try:
                            data = json.loads(line[6:])
                            if data.get("done"):
                                session_tokens[message.author.id] = data.get("session_token", sess_token)
                                continue
                            full += data.get("content", "")
                        except json.JSONDecodeError:
                            pass

                chunks = [full[i:i+2000] for i in range(0, len(full), 2000)]
                for chunk in chunks:
                    await message.channel.send(chunk)


async def handle_ask(
    user_id: str,
    question: str,
    discord_user_id: int,
    session_tokens: dict,
) -> str:
    sess_token = session_tokens.get(discord_user_id, uuid.uuid4().hex)
    session_tokens[discord_user_id] = sess_token

    import httpx
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            f"http://localhost:8001/api/chat",
            json={
                "message": question,
                "platform": "discord",
                "session_token": sess_token,
                "platform_user_id": str(discord_user_id),
            },
        ) as response:
            if response.status_code != 200:
                return "Error talking to AI server"

            full = ""
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    import json
                    try:
                        data = json.loads(line[6:])
                        if data.get("done"):
                            session_tokens[discord_user_id] = data.get("session_token", sess_token)
                            continue
                        full += data.get("content", "")
                    except json.JSONDecodeError:
                        pass
            return full or "No response from AI"
