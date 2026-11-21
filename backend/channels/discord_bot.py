"""Discord channel adapter.

It contains no verification logic: it forwards the message to POST /api/check (the same
endpoint the web UI uses) and formats the answer. Users can:
  - send the bot a direct message,
  - mention it in a channel: "@TapCheck <treść lub link>",
  - use the slash command /sprawdz.

Run from the backend/ directory:  python -m channels.discord_bot
"""

import base64
import hashlib
import logging

import discord
import httpx
from discord import app_commands

from app.config import get_settings
from app.net import async_http_client

log = logging.getLogger("discord_bot")
settings = get_settings()

DISCORD_LIMIT = 2000
EMOJI = {
    "potwierdzone": "✅",
    "fałszywe": "❌",
    "wprowadzające_w_błąd": "⚠️",
    "brak_wystarczających_dowodów": "❔",
    "nie_podlega_weryfikacji": "💬",
}
LABEL = {
    "potwierdzone": "POTWIERDZONE",
    "fałszywe": "FAŁSZ",
    "wprowadzające_w_błąd": "WPROWADZA W BŁĄD",
    "brak_wystarczających_dowodów": "BRAK WYSTARCZAJĄCYCH DOWODÓW",
    "nie_podlega_weryfikacji": "NIE PODLEGA WERYFIKACJI",
}


def session_id_for(user_id: int) -> str:
    """Pseudonymous session id: the raw Discord user id is never sent to the API or logs."""
    return "dc-" + hashlib.sha256(f"tapcheck:{user_id}".encode()).hexdigest()[:16]


def format_response(data: dict) -> str:
    if data["status"] != "ok":
        return f"ℹ️ {data.get('status_detail') or 'Nie udało się wykonać sprawdzenia.'}"

    lines = []
    for i, claim in enumerate(data["claims"], 1):
        v = claim["verdict"]
        score = claim.get("score")
        # For "misleading" the score is ~0 by definition (sources neither confirm nor refute): hide it.
        hide = score is None or v == "wprowadzające_w_błąd"
        score_text = "" if hide else f"  ·  wynik dowodów {score:+.2f} (od −1 do +1)".replace(".", ",")
        lines.append(f"**{i}. {EMOJI[v]} {LABEL[v]}**{score_text}")
        lines.append(f"> {claim['text']}")
        lines.append(claim["explanation"])
        for ev in claim["evidence"][:3]:
            date = (ev.get("published_at") or "")[:10] or "brak daty"
            lines.append(f"• {ev['publisher']} ({date}): <{ev['url']}>")
        if claim.get("limitations"):
            lines.append(f"_Ograniczenia: {claim['limitations']}_")
        lines.append("")
    if data.get("security_events"):
        lines.append("🛡️ Wykryto i zignorowano polecenia ukryte w treści.")
    if data.get("result_url"):
        lines.append(f"🔎 Pełny wynik ze źródłami i cytatami: {data['result_url']}")
    lines.append("_Tap & Check pomaga ocenić informacje — sprawdź źródła samodzielnie._")

    text = "\n".join(lines)
    if len(text) > DISCORD_LIMIT:
        suffix = f"\n… (skrócono) Pełny wynik: {data.get('result_url', '')}"
        text = text[: DISCORD_LIMIT - len(suffix)] + suffix
    return text


IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 5_000_000


def first_image(attachments: list) -> "discord.Attachment | None":
    """The first attached image the API accepts (type and size), if any."""
    for a in attachments:
        if (a.content_type or "").split(";")[0] in IMAGE_TYPES and a.size <= MAX_IMAGE_BYTES:
            return a
    return None


async def call_api(text: str, user_id: int, image: "discord.Attachment | None" = None) -> str:
    payload = {"text": text, "channel": "discord", "session_id": session_id_for(user_id)}
    if image is not None:  # same API as the web page: the image is read, never stored
        payload["image"] = base64.b64encode(await image.read()).decode()
        payload["image_media_type"] = (image.content_type or "").split(";")[0]
    try:
        async with async_http_client(timeout=90.0) as client:
            resp = await client.post(f"{settings.api_base_url}/api/check", json=payload)
        if resp.status_code == 429:
            return "ℹ️ Zbyt wiele zapytań. Spróbuj ponownie za minutę."
        resp.raise_for_status()
        return format_response(resp.json())
    except httpx.HTTPError:
        log.exception("API call failed")
        return "ℹ️ Usługa jest chwilowo niedostępna. To błąd techniczny, nie wynik sprawdzenia."


class TapCheckBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.dm_messages = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def _sync_commands(self, guild: discord.abc.Snowflake) -> None:
        # Per-server registration shows /sprawdz immediately (global sync can take up to an hour).
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def on_ready(self) -> None:
        for guild in self.guilds:
            await self._sync_commands(guild)
        log.info("Logged in as %s; /sprawdz registered on %d server(s)", self.user, len(self.guilds))

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self._sync_commands(guild)
        log.info("Joined %s; /sprawdz registered", guild.name)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or self.user is None:
            return
        is_dm = isinstance(message.channel, discord.DMChannel)
        if not is_dm and self.user not in message.mentions:
            return
        text = message.content.replace(f"<@{self.user.id}>", "").replace(f"<@!{self.user.id}>", "").strip()
        image = first_image(message.attachments)
        if not text and image is None:
            await message.reply(
                "Wyślij pytanie, treść doniesienia, link albo zrzut ekranu (PNG/JPG/WebP do 5 MB), "
                "a sprawdzę je w wiarygodnych źródłach."
            )
            return
        async with message.channel.typing():
            reply = await call_api(text, message.author.id, image)
        await message.reply(reply, suppress_embeds=True)


bot = TapCheckBot()


@bot.tree.command(name="sprawdz", description="Sprawdź doniesienie, pytanie, link lub zrzut ekranu w wiarygodnych źródłach")
@app_commands.describe(tresc="Pytanie, treść doniesienia albo link", obraz="Zrzut ekranu lub zdjęcie (opcjonalnie)")
async def sprawdz(interaction: discord.Interaction, tresc: str = "", obraz: discord.Attachment | None = None) -> None:
    image = first_image([obraz]) if obraz else None
    if not tresc.strip() and image is None:
        await interaction.response.send_message("Podaj treść, link albo dołącz obraz (PNG/JPG/WebP do 5 MB).", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    await interaction.followup.send(await call_api(tresc, interaction.user.id, image), suppress_embeds=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not settings.discord_token:
        raise SystemExit("Set DISCORD_TOKEN in .env to run the Discord bot.")
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
