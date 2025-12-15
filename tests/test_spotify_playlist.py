import types
import bot


class DummyResp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {}

    def json(self):
        return self._data


def test_parse_playlist_id_urls_and_ids():
    assert bot.parseSpotifyPlaylistId("spotify:playlist:abc123") == "abc123"
    assert bot.parseSpotifyPlaylistId("https://open.spotify.com/playlist/abc123") == "abc123"
    assert bot.parseSpotifyPlaylistId("abc123") == "abc123"
    assert bot.parseSpotifyPlaylistId("") is None


def test_get_playlist_tracks_single_page(monkeypatch):
    sample = {"items": [{"track": {"name": "Song1", "artists": [{"name": "A"}], "external_urls": {"spotify": "u"}}}], "next": None}
    resp = DummyResp(200, sample)

    def fake_get(url, headers=None, params=None, timeout=None):
        assert "/v1/playlists/" in url
        return resp

    monkeypatch.setattr(bot, "requests", types.SimpleNamespace(get=fake_get, RequestException=Exception))
    out = bot.getSpotifyPlaylistTracks("https://open.spotify.com/playlist/abc", limit=10)
    assert isinstance(out, list)
    assert len(out) == 1


def test_get_playlist_tracks_error(monkeypatch):
    resp = DummyResp(404, {})

    def fake_get(url, headers=None, params=None, timeout=None):
        return resp

    monkeypatch.setattr(bot, "requests", types.SimpleNamespace(get=fake_get, RequestException=Exception))
    assert bot.getSpotifyPlaylistTracks("invalid", limit=5) is None
