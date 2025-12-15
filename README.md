# GuessTheSongBot

Simple Discord bot that can guess a song from a snippet of lyrics by searching Genius and then looking up the matching track on Spotify (app-level search).

## Configuration
Add the following keys to `config.json`:

- `DISCORD_TOKEN`: Your bot token (required)
- `GENIUS_TOKEN`: Genius API token (required)
- `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`: Spotify app credentials (required)

Example `config.json`:

```json
{
  "DISCORD_TOKEN": "your-discord-token",
  "GENIUS_TOKEN": "your-genius-token",
  "SPOTIFY_CLIENT_ID": "your-spotify-client-id",
  "SPOTIFY_CLIENT_SECRET": "your-spotify-client-secret"
}
```

## Usage
- Run `pip install -r requirements.txt` to install dependencies.
- Start the bot: `python bot.py`.
- Use the `/guess` command with a `lyrics` argument in your server.
 - Use the `/guess` command with a `lyrics` argument in your server.
 - Try the `/colorbutton` command to see a demo button with a random color (blurple/green/red).
