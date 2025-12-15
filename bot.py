import base64
import json
import textwrap
from typing import Optional

import discord
import requests
from bs4 import BeautifulSoup
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View
#from button_utils import get_random_button_style


with open("config.json") as f:
    config = json.load(f)

TOKEN = config.get("DISCORD_TOKEN")
GENIUS_TOKEN = config.get("GENIUS_TOKEN")
SPOTIFY_CLIENT_ID = config.get("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = config.get("SPOTIFY_CLIENT_SECRET")


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


def _get_genius_lyrics_from_url(url: str) -> Optional[str]:
    """Scrape the Genius song page for lyrics.

    Implementation notes:
    - Prefers divs with `data-lyrics-container="true"` which Genius uses to
      render lyrics fragments. Falls back to the legacy `.lyrics` container.
    - Returns a plain-text string or `None` if extraction fails.
    - Keep any returned snippet short when sending to Discord to avoid
      reposting large amounts of copyrighted text; the command below only
      exposes a short snippet and links back to the Genius page.
    """
    try:
        r = requests.get(url, headers={"User-Agent": "lyrics-bot/1.0"}, timeout=10)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "html.parser")

    # Newer Genius markup uses multiple divs with data-lyrics-container="true".
    parts = soup.find_all("div", attrs={"data-lyrics-container": "true"})
    if parts:
        text_parts = [p.get_text(separator="\n", strip=True) for p in parts]
        return "\n".join(text_parts).strip()

    # Fallback to legacy container
    legacy = soup.select_one(".lyrics")
    if legacy:
        return legacy.get_text(separator="\n", strip=True)

    return None


_validate_config()

bot = commands.Bot(
    command_prefix=None,
    help_command=None,
    is_case_insensitive=True,
    intents=discord.Intents.default(),
)


@bot.event
async def on_ready():
    print("Ready!")
    synced = await bot.tree.sync()
    print(f"Synced {len(synced)} commands")


@bot.tree.command(name="guess", description="Guess the song from lyrics (Genius + Spotify)")
@app_commands.describe(lyrics="A short snippet of the lyrics to search for")
async def guess(interaction: discord.Interaction, lyrics: str):
    await interaction.response.defer()
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
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="lyrics", description="Fetch lyrics for a track (Genius). Returns a short snippet and link.")
@app_commands.describe(query="Song title and/or artist to search for", url="Direct Genius song URL (optional)")
async def lyrics(interaction: discord.Interaction, query: Optional[str] = None, url: Optional[str] = None):
    await interaction.response.defer(ephemeral=True)

    if not query and not url:
        await interaction.followup.send("Provide either `query` or `url` to fetch lyrics.", ephemeral=True)
        return

    target_url = url
    if not target_url:
        # Reuse search to find a likely Genius page
        result = _search_genius(query or "", GENIUS_TOKEN)
        if not result:
            await interaction.followup.send("No match found on Genius for that query.", ephemeral=True)
            return
        target_url = result.get("genius_url")

    lyrics_text = _get_genius_lyrics_from_url(target_url)
    if not lyrics_text:
        await interaction.followup.send("Could not extract lyrics from the Genius page.", ephemeral=True)
        return

    # Only show a short snippet to avoid posting long copyrighted text;
    # link to Genius for the full lyrics.
    snippet_len = 400
    snippet = lyrics_text.strip()
    if len(snippet) > snippet_len:
        snippet = snippet[:snippet_len].rsplit("\n", 1)[0] + "..."

    note = f"\n\nFull lyrics are available on Genius: {target_url}"
    await interaction.followup.send(f"Lyrics snippet:\n{snippet}{note}", ephemeral=True)



bot.run(TOKEN)
