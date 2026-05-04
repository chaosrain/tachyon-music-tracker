import requests
import spotipy
import tempfile
import time
import os
import subprocess
import logging
from spotipy.oauth2 import SpotifyOAuth
from dotenv import dotenv_values

CONFIG_PATH = "/home/particle/music-tracker/config/config.env"
config = dotenv_values(CONFIG_PATH)

AUDD_API_KEY = config["AUDD_API_KEY"]
SPOTIFY_CLIENT_ID = config["SPOTIFY_CLIENT_ID"]
SPOTIFY_CLIENT_SECRET = config["SPOTIFY_CLIENT_SECRET"]
SPOTIFY_REDIRECT_URI = config["SPOTIFY_REDIRECT_URI"]
PLAYLIST_NAME = config.get("PLAYLIST_NAME", "Tachyon Heard This")
RECORD_SECONDS = int(config.get("RECORD_SECONDS", 15))
LISTEN_INTERVAL = int(config.get("LISTEN_INTERVAL", 0))
VOLUME_BOOST_DB = int(config.get("VOLUME_BOOST_DB", 20))
VOLUME_GATE_DB = int(config.get("VOLUME_GATE_DB", -50))

LOG_PATH = "/home/particle/music-tracker/logs/tracker.log"
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET,
    redirect_uri=SPOTIFY_REDIRECT_URI,
    scope="playlist-modify-public playlist-modify-private",
    cache_path="/home/particle/music-tracker/.cache/spotify_cache.json"
))

def get_or_create_playlist():
    user_id = sp.current_user()["id"]
    playlists = sp.current_user_playlists(limit=50)
    for pl in playlists["items"]:
        if pl["name"] == PLAYLIST_NAME:
            return pl["id"]
    pl = sp.user_playlist_create(user_id, PLAYLIST_NAME, public=False,
                                  description="Songs recognized by Tachyon music tracker")
    return pl["id"]

def get_max_volume_db(pcm_path):
    """Return max volume in dBFS of raw PCM file."""
    result = subprocess.run(
        ['ffmpeg', '-f', 's16le', '-ar', '48000', '-ac', '2',
         '-i', pcm_path, '-af', 'volumedetect', '-f', 'null', '/dev/null'],
        capture_output=True, text=True
    )
    for line in result.stderr.splitlines():
        if 'max_volume' in line:
            try:
                return float(line.split('max_volume:')[1].strip().split(' ')[0])
            except Exception:
                pass
    return -99.0

def record_audio(seconds=RECORD_SECONDS):
    raw = tempfile.mktemp(suffix=".pcm")
    mp3 = tempfile.mktemp(suffix=".mp3")
    subprocess.run(
        ['timeout', str(seconds + 2), 'tinycap', raw,
         '-D', '0', '-d', '0', '-r', '48000', '-c', '2', '-b', '16',
         '-p', '1024', '-n', '4'],
        timeout=seconds + 5
    )

    # Volume gate — skip silent clips
    max_vol = get_max_volume_db(raw)
    log.debug(f"Raw max volume: {max_vol} dB (gate: {VOLUME_GATE_DB} dB)")
    if max_vol < VOLUME_GATE_DB:
        log.info(f"Silent clip ({max_vol} dB), skipping.")
        os.remove(raw)
        return None

    subprocess.run(
        ['ffmpeg', '-y', '-f', 's16le', '-ar', '48000', '-ac', '2',
         '-i', raw, '-af', f'volume={VOLUME_BOOST_DB}dB', mp3],
        capture_output=True
    )
    os.remove(raw)
    return mp3

def recognize_song(mp3_path):
    with open(mp3_path, 'rb') as f:
        response = requests.post(
            'https://api.audd.io/',
            data={'api_token': AUDD_API_KEY, 'return': 'spotify'},
            files={'file': f}
        )
    return response.json()

def add_to_playlist(playlist_id, track_uri):
    sp.playlist_add_items(playlist_id, [track_uri])

def main():
    log.info("Music tracker started.")
    log.info(f"Settings: {RECORD_SECONDS}s clips, {VOLUME_BOOST_DB}dB boost, {VOLUME_GATE_DB}dB gate, {LISTEN_INTERVAL}s interval")
    playlist_id = get_or_create_playlist()
    log.info(f"Using playlist: {PLAYLIST_NAME} ({playlist_id})")
    seen = set()

    while True:
        try:
            log.info("Recording...")
            mp3 = record_audio()

            if mp3 is None:
                time.sleep(LISTEN_INTERVAL)
                continue

            log.info("Recognizing...")
            result = recognize_song(mp3)
            if os.path.exists(mp3):
                os.remove(mp3)

            if result.get("status") == "success" and result.get("result"):
                song = result["result"]
                title = song.get("title", "Unknown")
                artist = song.get("artist", "Unknown")
                spotify_data = song.get("spotify", {})
                track_uri = spotify_data.get("uri") if spotify_data else None

                log.info(f"Recognized: {title} by {artist}")

                if track_uri and track_uri not in seen:
                    add_to_playlist(playlist_id, track_uri)
                    seen.add(track_uri)
                    log.info(f"Added to playlist: {title} by {artist}")
                elif track_uri in seen:
                    log.info("Already added this song, skipping.")
                else:
                    log.info("No Spotify URI found for this track.")
            else:
                log.info(f"No match. Response: {result.get('status')}")

        except Exception as e:
            log.error(f"Error: {e}")

        time.sleep(LISTEN_INTERVAL)

if __name__ == "__main__":
    main()
