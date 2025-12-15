import base64
import os
import textwrap
from typing import Optional
from dotenv import load_dotenv

import discord
import requests
from bs4 import BeautifulSoup
import logging
from discord import app_commands
from discord.ext import commands


load_dotenv()  # load variables from a .env file into the environment

token = os.getenv("DISCORD_TOKEN")
geniusToken = os.getenv("GENIUS_TOKEN")
spotifyClientId = os.getenv("SPOTIFY_CLIENT_ID")
spotifyClientSecret = os.getenv("SPOTIFY_CLIENT_SECRET")

#log pannuvom etha nollaiyayi pochi na
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def validateConfig() -> bool:
    """Validate configuration and return True if minimum config is present.

    This does not raise; instead it logs errors/warnings and returns a
    boolean so callers can decide how to proceed. The bot will only start
    if `DISCORD_TOKEN` is present.
    """
    ok = True
    if not token:
        logger.error("DISCORD_TOKEN not configured: bot will not start")
        ok = False
    if not geniusToken:
        logger.warning("GENIUS_TOKEN not configured: /guess and /lyrics will be disabled")
    if not spotifyClientId or not spotifyClientSecret:
        logger.warning("Spotify client credentials not configured: Spotify lookups will be skipped")
    return ok


def getSpotifyAppToken(clientId: str, clientSecret: str) -> Optional[str]:
    """Obtain a Spotify app access token using Client Credentials flow.

    Returns `None` on error instead of raising, so callers can gracefully
    degrade if Spotify is unavailable or credentials are missing.
    """
    if not clientId or not clientSecret:
        logger.debug("Spotify credentials missing, skipping token request")
        return None
    url = "https://accounts.spotify.com/api/token"
    auth = base64.b64encode(f"{clientId}:{clientSecret}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"}
    data = {"grant_type": "client_credentials"}
    try:
        r = requests.post(url, headers=headers, data=data, timeout=10)
    except requests.RequestException:
        logger.exception("Failed to obtain Spotify app token")
        return None
    if r.status_code != 200:
        logger.warning("Spotify token request returned status %s", r.status_code)
        return None
    return r.json().get("access_token")


def searchSpotifyTrack(title: str, artist: str, appToken: str) -> Optional[str]:
    """Search Spotify for a track and return a Spotify track URL if found.

    Returns `None` on error or when no match is found.
    """
    if not appToken:
        logger.debug("No Spotify app token available, skipping Spotify search")
        return None
    query = f"track:{title} artist:{artist}"
    url = "https://api.spotify.com/v1/search"
    params = {"q": query, "type": "track", "limit": 1}
    headers = {"Authorization": f"Bearer {appToken}"}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
    except requests.RequestException:
        logger.exception("Spotify search request failed")
        return None
    if r.status_code != 200:
        logger.warning("Spotify search returned status %s", r.status_code)
        return None
    items = r.json().get("tracks", {}).get("items", [])
    if not items:
        return None
    return items[0].get("external_urls", {}).get("spotify")


def searchGenius(lyrics: str, token: str) -> Optional[dict]:
    """Search Genius for lyrics snippet. Returns dict with title and artist and url.

    Returns `None` on error or when no results were found.
    """
    if not token:
        logger.debug("No Genius token configured, skipping Genius search")
        return None
    url = "https://api.genius.com/search"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"q": lyrics}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
    except requests.RequestException:
        logger.exception("Genius search request failed")
        return None
    if r.status_code != 200:
        logger.warning("Genius search returned status %s", r.status_code)
        return None
    hits = r.json().get("response", {}).get("hits", [])
    if not hits:
        return None
    top = hits[0].get("result", {})
    title = top.get("title")
    artist = top.get("primary_artist", {}).get("name")
    url = top.get("url")
    return {"title": title, "artist": artist, "genius_url": url}


def getGeniusLyricsFromUrl(url: str) -> Optional[str]:
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
        logger.exception("Failed to fetch Genius page for lyrics")
        return None
    if r.status_code != 200:
        logger.warning("Genius lyrics page returned status %s", r.status_code)
        return None
    soup = BeautifulSoup(r.text, "html.parser")

    # Newer Genius markup uses multiple divs with data-lyrics-container="true".
    parts = soup.find_all("div", attrs={"data-lyrics-container": "true"})
    if parts:
        textParts = [p.get_text(separator="\n", strip=True) for p in parts]
        return "\n".join(textParts).strip()

    # Fallback to legacy container
    legacy = soup.select_one(".lyrics")
    if legacy:
        return legacy.get_text(separator="\n", strip=True)

    return None
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
    # Robustly try to defer; if the interaction is no longer valid, fall back
    try:
        await interaction.response.defer()
        deferred = True
    except discord.NotFound:
        logger.warning("Interaction not found when deferring in /guess; falling back to immediate response")
        deferred = False
    except Exception:
        raise

    genius = searchGenius(lyrics, geniusToken)
    if not genius:
        # If Genius is not configured or no results, inform the user politely.
        if deferred:
            await interaction.followup.send("No match found on Genius for that lyrics snippet.")
        else:
            await interaction.response.send_message("No match found on Genius for that lyrics snippet.")
        return

    title = genius["title"]
    artist = genius["artist"]
    geniusUrl = genius.get("genius_url")

    spotifyToken = getSpotifyAppToken(spotifyClientId, spotifyClientSecret)
    spotifyUrl = None
    if spotifyToken:
        spotifyUrl = searchSpotifyTrack(title, artist, spotifyToken)

    embed = discord.Embed(title=f"{title} — {artist}")
    desc = textwrap.dedent(f"""
    Found a likely match on Genius: {geniusUrl}
    {( 'Spotify link: ' + spotifyUrl) if spotifyUrl else 'Spotify match not found.'}
    """)
    embed.description = desc

    if deferred:
        try:
            await interaction.followup.send(embed=embed)
            return
        except discord.NotFound:
            logger.warning("Followup failed after defer in /guess; falling back to response.send_message")

    try:
        await interaction.response.send_message(embed=embed)
    except Exception:
        if interaction.channel:
            await interaction.channel.send(embed=embed)
        else:
            logger.exception("Unable to send response for /guess; no channel available")



# Ensure required configuration is present (graceful warnings for optional keys)
if validateConfig():
    bot.run(token)
else:
    logger.info("Bot not started due to missing DISCORD_TOKEN; set it in .env to start the bot")