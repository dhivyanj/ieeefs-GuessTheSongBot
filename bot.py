import base64
import os
import textwrap
from typing import Optional
from dotenv import load_dotenv

import discord
import requests
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View
#from button_utils import get_random_button_style
import logging


load_dotenv()  # loads variables from a .env file into the environment

TOKEN = os.getenv("DISCORD_TOKEN")
GENIUS_TOKEN = os.getenv("GENIUS_TOKEN")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")


def _validate_config():
    missing = []
    if not TOKEN:
        missing.append("DISCORD_TOKEN")
    if not GENIUS_TOKEN:
        missing.append("GENIUS_TOKEN")
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        missing.append("SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET")
    if missing:
        raise RuntimeError("Missing required config keys: " + ", ".join(missing))


def _get_spotify_app_token(client_id: str, client_secret: str) -> Optional[str]:
    """Obtain a Spotify app access token using Client Credentials flow."""
    url = "https://accounts.spotify.com/api/token"
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"}
    data = {"grant_type": "client_credentials"}
    r = requests.post(url, headers=headers, data=data, timeout=10)
    if r.status_code != 200:
        return None
    return r.json().get("access_token")


def _search_spotify_track(title: str, artist: str, app_token: str) -> Optional[str]:
    """Search Spotify for a track and return a Spotify track URL if found."""
    query = f"track:{title} artist:{artist}"
    url = "https://api.spotify.com/v1/search"
    params = {"q": query, "type": "track", "limit": 1}
    headers = {"Authorization": f"Bearer {app_token}"}
    r = requests.get(url, headers=headers, params=params, timeout=10)
    if r.status_code != 200:
        return None
    items = r.json().get("tracks", {}).get("items", [])
    if not items:
        return None
    return items[0].get("external_urls", {}).get("spotify")


def _search_genius(lyrics: str, token: str) -> Optional[dict]:
    """Search Genius for lyrics snippet. Returns dict with title and artist and url."""
    url = "https://api.genius.com/search"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"q": lyrics}
    r = requests.get(url, headers=headers, params=params, timeout=10)
    if r.status_code != 200:
        return None
    hits = r.json().get("response", {}).get("hits", [])
    if not hits:
        return None
    top = hits[0].get("result", {})
    title = top.get("title")
    artist = top.get("primary_artist", {}).get("name")
    url = top.get("url")
    return {"title": title, "artist": artist, "genius_url": url}


_validate_config()

bot = commands.Bot(
    command_prefix=None,
    help_command=None,
    is_case_insensitive=True,
    intents=discord.Intents.default(),
)

logger = logging.getLogger(__name__)


@bot.event
async def on_ready():
    print("Ready!")
    synced = await bot.tree.sync()
    print(f"Synced {len(synced)} commands")


@bot.tree.command(name="guess", description="Guess the song from lyrics (Genius + Spotify)")
@app_commands.describe(lyrics="A short snippet of the lyrics to search for")
async def guess(interaction: discord.Interaction, lyrics: str):
    try:
        await interaction.response.defer()
        deferred = True
    except discord.NotFound:
        logger.warning("Interaction not found when deferring in /guess; falling back to immediate response")
        deferred = False
    except Exception:
        raise
    genius = _search_genius(lyrics, GENIUS_TOKEN)
    if not genius:
        await interaction.followup.send("No match found on Genius for that lyrics snippet.")
        return

    title = genius["title"]
    artist = genius["artist"]
    genius_url = genius.get("genius_url")

    spotify_token = _get_spotify_app_token(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
    spotify_url = None
    if spotify_token:
        spotify_url = _search_spotify_track(title, artist, spotify_token)

    embed = discord.Embed(title=f"{title} — {artist}")
    desc = textwrap.dedent(f"""
    Found a likely match on Genius: {genius_url}
    {('Spotify link: ' + spotify_url) if spotify_url else 'Spotify match not found.'}
    """)
    embed.description = desc
    # Prefer followup if we deferred; otherwise try an initial response, then channel fallback
    if deferred:
        try:
            await interaction.followup.send(embed=embed)
            return
        except discord.NotFound:
            logger.warning("Followup failed after defer in /guess; falling back to response.send_message")

    try:
        await interaction.response.send_message(embed=embed)
    except Exception:
        # Last resort: send directly to the channel if available
        if interaction.channel:
            await interaction.channel.send(embed=embed)
        else:
            logger.exception("Unable to send response for /guess; no channel available")


@bot.tree.command(name="colorbutton", description="Send a demo button with a random color style")
async def colorbutton(interaction: discord.Interaction):
    style = get_random_button_style()
    button = Button(style=style, label="Click me")

    async def _callback(i: discord.Interaction):
        button.disabled = True
        await i.response.edit_message(view=view)
        await i.followup.send("You clicked the button!")

    button.callback = _callback
    view = View()
    view.add_item(button)
    await interaction.response.send_message("Here's a random-colored button:", view=view)


bot.run(TOKEN)
