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


load_dotenv() #va va minnal

token = os.getenv("DISCORD_TOKEN")
geniusToken = os.getenv("GENIUS_TOKEN")
spotifyClientId = os.getenv("SPOTIFY_CLIENT_ID")
spotifyClientSecret = os.getenv("SPOTIFY_CLIENT_SECRET")

#log pannuvom etha nollaiyayi pochi na
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def validateConfig() -> bool:
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


def parseSpotifyPlaylistId(urlOrId: str) -> Optional[str]:
    if not urlOrId:
        return None
    s = urlOrId.strip()
    if s.startswith("spotify:playlist:"):
        return s.split(":", 2)[-1]
    try:
        p = urllib.parse.urlparse(s)
        if p.hostname and "spotify" in p.hostname and p.path:
            parts = p.path.strip("/").split("/")
            if parts and parts[0] == "playlist":
                return parts[1] if len(parts) > 1 else None
    except Exception:
        pass
    if all(c.isalnum() or c in "_-" for c in s):
        return s
    return None


def getSpotifyPlaylistTracks(playlist: str, accessToken: Optional[str] = None, limit: int = 20) -> Optional[list]:
    playlistId = parseSpotifyPlaylistId(playlist)
    if not playlistId:
        return None
    token = accessToken or getSpotifyAppToken(spotifyClientId, spotifyClientSecret)
    if not token:
        return None
    url = f"https://api.spotify.com/v1/playlists/{playlistId}/tracks"
    headers = {"Authorization": f"Bearer {token}"}
    collected = []
    params = {"limit": min(limit, 100), "offset": 0}
    try:
        while len(collected) < limit:
            r = requests.get(url, headers=headers, params=params, timeout=10)
            if r.status_code != 200:
                logger.warning("Spotify playlist tracks returned status %s", r.status_code)
                return None
            data = r.json()
            items = data.get("items", [])
            if not items:
                break
            for it in items:
                collected.append(it)
                if len(collected) >= limit:
                    break
            if not data.get("next"):
                break
            params["offset"] += params["limit"]
    except requests.RequestException:
        logger.exception("Spotify playlist tracks request failed")
        return None
    return collected


def searchGenius(lyrics: str, token: str) -> Optional[dict]:
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
    try:
        r = requests.get(url, headers={"User-Agent": "lyrics-bot/1.0"}, timeout=10)
    except requests.RequestException:
        logger.exception("Failed to fetch Genius page for lyrics")
        return None
    if r.status_code != 200:
        logger.warning("Genius lyrics page returned status %s", r.status_code)
        return None
    soup = BeautifulSoup(r.text, "html.parser")

    parts = soup.find_all("div", attrs={"data-lyrics-container": "true"})
    if parts:
        textParts = [p.get_text(separator="\n", strip=True) for p in parts]
        return "\n".join(textParts).strip()

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
    print(f"Synced {len(synced)} commands to use. watha ek aur baar bot add krna h aur koi easy method h kya?")


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

    genius = searchGenius(lyrics, geniusToken)
    if not genius:
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


@bot.tree.command(name="playlist-tracks", description="Show tracks from a Spotify playlist URL or ID")
@app_commands.describe(playlist="Spotify playlist URL or ID", limit="Number of tracks to show (max 100)")
async def playlistTracks(interaction: discord.Interaction, playlist: str, limit: int = 10, access_token: Optional[str] = None):
    try:
        await interaction.response.defer(ephemeral=True)
        deferred = True
    except discord.NotFound:
        deferred = False
    except Exception:
        raise

    if limit < 1 or limit > 100:
        limit = 10

    tokenToUse = access_token or None
    tracks = getSpotifyPlaylistTracks(playlist, tokenToUse, limit)
    if tracks is None:
        msg = "Could not fetch playlist tracks. Ensure the playlist is public and the ID/URL is correct."
        if deferred:
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        return

    lines = []
    for i, it in enumerate(tracks):
        tr = it.get("track", {})
        name = tr.get("name")
        artists = ", ".join(a.get("name") for a in tr.get("artists", []))
        link = tr.get("external_urls", {}).get("spotify")
        lines.append(f"{i+1}. {name} — {artists} {link or ''}".strip())

    out = "\n".join(lines) or "No tracks found."
    if deferred:
        await interaction.followup.send(out, ephemeral=True)
    else:
        await interaction.response.send_message(out, ephemeral=True)

if validateConfig():
    bot.run(token)
else:
    logger.info("Bot not started due to missing DISCORD_TOKEN; set it in .env to start the bot")
"""
ab tak jo h chala do, baki kal dekhte h 
"""