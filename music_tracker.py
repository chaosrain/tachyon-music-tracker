import requests
import spotipy
import tempfile
import time
import os
import subprocess
import logging
import hmac
import hashlib
import base64
import json
from datetime import datetime, date
from spotipy.oauth2 import SpotifyOAuth
from dotenv import dotenv_values

CONFIG_PATH = "/home/particle/music-tracker/config/config.env"
config = dotenv_values(CONFIG_PATH)

AUDD_API_KEY = config.get("AUDD_API_KEY", "")
SPOTIFY_CLIENT_ID = config["SPOTIFY_CLIENT_ID"]
SPOTIFY_CLIENT_SECRET = config["SPOTIFY_CLIENT_SECRET"]
SPOTIFY_REDIRECT_URI = config["SPOTIFY_REDIRECT_URI"]
PLAYLIST_NAME = config.get("PLAYLIST_NAME", "Tachyon Heard This")
RECORD_SECONDS = int(config.get("RECORD_SECONDS", 15))
LISTEN_INTERVAL = int(config.get("LISTEN_INTERVAL", 0))
VOLUME_GATE_DB = int(config.get("VOLUME_GATE_DB", -50))
VOLUME_BOOST_DB = int(config.get("VOLUME_BOOST_DB", 0))
HA_URL = config.get("HA_URL", "").rstrip("/")
HA_TOKEN = config.get("HA_TOKEN", "")

ACRCLOUD_HOST = config.get("ACRCLOUD_HOST", "")
ACRCLOUD_KEY = config.get("ACRCLOUD_KEY", "")
ACRCLOUD_SECRET = config.get("ACRCLOUD_SECRET", "")
ACRCLOUD_DAILY_LIMIT = int(config.get("ACRCLOUD_DAILY_LIMIT", 90))

RAPIDAPI_KEY = config.get("RAPIDAPI_KEY", "")
SHAZAM_DAILY_LIMIT = int(config.get("SHAZAM_DAILY_LIMIT", 15))

STATS_PATH = "/home/particle/music-tracker/logs/api_usage.json"
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


# ---------------------------------------------------------------------------
# API usage tracker
# ---------------------------------------------------------------------------

def load_stats():
    today = str(date.today())
    if os.path.exists(STATS_PATH):
        try:
            with open(STATS_PATH) as f:
                stats = json.load(f)
            if stats.get("date") != today:
                stats = {"date": today, "acrcloud": 0, "shazam": 0, "last_used": "shazam"}
        except Exception:
            stats = {"date": today, "acrcloud": 0, "shazam": 0, "last_used": "shazam"}
    else:
        stats = {"date": today, "acrcloud": 0, "shazam": 0, "last_used": "shazam"}
    return stats

def save_stats(stats):
    with open(STATS_PATH, "w") as f:
        json.dump(stats, f)

def pick_recognizer(stats):
    """Round-robin, but skip any service that has hit its daily limit."""
    acr_ok = bool(ACRCLOUD_HOST) and stats["acrcloud"] < ACRCLOUD_DAILY_LIMIT
    shazam_ok = bool(RAPIDAPI_KEY) and stats["shazam"] < SHAZAM_DAILY_LIMIT

    if not acr_ok and not shazam_ok:
        return None

    # Alternate from whichever was used last
    if stats["last_used"] == "acrcloud":
        return "shazam" if shazam_ok else "acrcloud"
    else:
        return "acrcloud" if acr_ok else "shazam"


# ---------------------------------------------------------------------------
# ACRCloud
# ---------------------------------------------------------------------------

def recognize_acrcloud(mp3_path):
    timestamp = str(int(time.time()))
    string_to_sign = "\n".join(["POST", "/v1/identify", ACRCLOUD_KEY,
                                 "audio", "1", timestamp])
    signature = base64.b64encode(
        hmac.new(ACRCLOUD_SECRET.encode(), string_to_sign.encode(),
                  digestmod=hashlib.sha1).digest()
    ).decode()

    with open(mp3_path, "rb") as f:
        audio_data = f.read()

    response = requests.post(
        f"https://{ACRCLOUD_HOST}/v1/identify",
        files={"sample": audio_data},
        data={
            "access_key": ACRCLOUD_KEY,
            "sample_bytes": len(audio_data),
            "timestamp": timestamp,
            "signature": signature,
            "data_type": "audio",
            "signature_version": "1"
        },
        timeout=10
    )
    raw = response.json()

    # Normalize to common format
    status_code = raw.get("status", {}).get("code", -1)
    if status_code == 0 and raw.get("metadata", {}).get("music"):
        music = raw["metadata"]["music"][0]
        title = music.get("title", "Unknown")
        artist = music.get("artists", [{}])[0].get("name", "Unknown")
        album = music.get("album", {}).get("name", "Unknown")
        spotify_id = (music.get("external_metadata", {})
                      .get("spotify", {}).get("track", {}).get("id", ""))
        spotify_url = f"https://open.spotify.com/track/{spotify_id}" if spotify_id else ""
        track_uri = f"spotify:track:{spotify_id}" if spotify_id else None
        return {"matched": True, "title": title, "artist": artist,
                "album": album, "spotify_url": spotify_url, "track_uri": track_uri,
                "rate_limited": False}
    elif status_code == 3003:
        return {"matched": False, "rate_limited": True}
    else:
        return {"matched": False, "rate_limited": False}


# ---------------------------------------------------------------------------
# Shazam via RapidAPI
# ---------------------------------------------------------------------------

def recognize_shazam(mp3_path):
    with open(mp3_path, "rb") as f:
        audio_data = f.read()

    response = requests.post(
        "https://shazam.p.rapidapi.com/songs/v2/detect",
        headers={
            "X-RapidAPI-Key": RAPIDAPI_KEY,
            "X-RapidAPI-Host": "shazam.p.rapidapi.com",
            "Content-Type": "text/plain"
        },
        data=base64.b64encode(audio_data).decode(),
        timeout=10
    )

    if response.status_code == 429:
        return {"matched": False, "rate_limited": True}

    raw = response.json()

    # Normalize to common format
    track = raw.get("track")
    if not track:
        return {"matched": False, "rate_limited": False}

    title = track.get("title", "Unknown")
    artist = track.get("subtitle", "Unknown")
    album = (track.get("sections", [{}])[0].get("metadata", [{}])[0].get("text", "Unknown")
             if track.get("sections") else "Unknown")

    # Extract Spotify URI from hub providers
    track_uri = None
    spotify_url = ""
    for provider in track.get("hub", {}).get("providers", []):
        for action in provider.get("actions", []):
            uri = action.get("uri", "")
            if uri.startswith("spotify:track:"):
                track_uri = uri
                track_id = uri.split(":")[-1]
                spotify_url = f"https://open.spotify.com/track/{track_id}"
                break

    return {"matched": True, "title": title, "artist": artist,
            "album": album, "spotify_url": spotify_url, "track_uri": track_uri,
            "rate_limited": False}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def recognize_song(mp3_path):
    stats = load_stats()
    services = ["acrcloud", "shazam"]

    for _ in range(2):
        service = pick_recognizer(stats)
        if service is None:
            log.warning("All recognition services have hit their daily limit.")
            return None

        log.info(f"Using {service} ({stats[service]}/{ACRCLOUD_DAILY_LIMIT if service == 'acrcloud' else SHAZAM_DAILY_LIMIT} today)")

        try:
            result = recognize_acrcloud(mp3_path) if service == "acrcloud" else recognize_shazam(mp3_path)
        except Exception as e:
            log.warning(f"{service} error: {e}")
            stats["last_used"] = service
            save_stats(stats)
            continue

        stats[service] += 1
        stats["last_used"] = service
        save_stats(stats)

        if result.get("rate_limited"):
            log.warning(f"{service} rate limited, trying other service.")
            continue

        return result

    return None


# ---------------------------------------------------------------------------
# Spotify
# ---------------------------------------------------------------------------

def get_or_create_playlist():
    user_id = sp.current_user()["id"]
    playlists = sp.current_user_playlists(limit=50)
    for pl in playlists["items"]:
        if pl["name"] == PLAYLIST_NAME:
            return pl["id"]
    pl = sp.user_playlist_create(user_id, PLAYLIST_NAME, public=False,
                                  description="Songs recognized by Tachyon music tracker")
    return pl["id"]

def add_to_playlist(playlist_id, track_uri):
    sp.playlist_add_items(playlist_id, [track_uri])


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

def get_max_volume_db(pcm_path):
    result = subprocess.run(
        ["ffmpeg", "-f", "s16le", "-ar", "48000", "-ac", "2",
         "-i", pcm_path, "-af", "volumedetect", "-f", "null", "/dev/null"],
        capture_output=True, text=True
    )
    for line in result.stderr.splitlines():
        if "max_volume" in line:
            try:
                return float(line.split("max_volume:")[1].strip().split(" ")[0])
            except Exception:
                pass
    return -99.0

def record_audio(seconds=RECORD_SECONDS):
    raw = tempfile.mktemp(suffix=".pcm")
    mp3 = tempfile.mktemp(suffix=".mp3")
    subprocess.run(
        ["timeout", str(seconds + 2), "tinycap", raw,
         "-D", "0", "-d", "0", "-r", "48000", "-c", "2", "-b", "16",
         "-p", "1024", "-n", "4"],
        timeout=seconds + 5
    )

    max_vol = get_max_volume_db(raw)
    if max_vol < VOLUME_GATE_DB:
        log.info(f"Silent clip ({max_vol} dB), skipping.")
        os.remove(raw)
        return None

    boost_str = f" (+{VOLUME_BOOST_DB}dB boost)" if VOLUME_BOOST_DB else ""
    log.info(f"Audio level: {max_vol} dB{boost_str}")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "s16le", "-ar", "48000", "-ac", "2",
         "-i", raw] + (["-af", f"volume={VOLUME_BOOST_DB}dB"] if VOLUME_BOOST_DB else []) + [mp3],
        capture_output=True
    )
    os.remove(raw)
    return mp3


# ---------------------------------------------------------------------------
# Home Assistant
# ---------------------------------------------------------------------------

def update_ha_sensor(title, artist, album, spotify_url, captured_at):
    if not HA_URL or not HA_TOKEN:
        return
    try:
        response = requests.post(
            f"{HA_URL}/api/states/sensor.tachyon_now_playing",
            headers={
                "Authorization": f"Bearer {HA_TOKEN}",
                "Content-Type": "application/json"
            },
            json={
                "state": f"{title} by {artist}",
                "attributes": {
                    "friendly_name": "Tachyon Now Playing",
                    "title": title,
                    "artist": artist,
                    "album": album,
                    "spotify_url": spotify_url,
                    "captured_at": captured_at,
                    "icon": "mdi:music"
                }
            },
            timeout=5
        )
        if response.status_code in (200, 201):
            log.info("HA sensor updated.")
        else:
            log.warning(f"HA sensor update failed: {response.status_code}")
    except Exception as e:
        log.warning(f"HA sensor update error: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log.info("Music tracker started.")
    log.info(f"Settings: {RECORD_SECONDS}s clips, {VOLUME_GATE_DB}dB gate, {LISTEN_INTERVAL}s interval")
    log.info(f"Recognition: ACRCloud ({'enabled' if ACRCLOUD_HOST else 'disabled'}, limit {ACRCLOUD_DAILY_LIMIT}/day) | "
             f"Shazam ({'enabled' if RAPIDAPI_KEY else 'disabled'}, limit {SHAZAM_DAILY_LIMIT}/day)")
    if HA_URL and HA_TOKEN:
        log.info(f"Home Assistant: {HA_URL}")

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

            if result is None:
                log.warning("No recognition service available.")
                time.sleep(60)
                continue

            if result.get("matched"):
                title = result["title"]
                artist = result["artist"]
                album = result["album"]
                spotify_url = result["spotify_url"]
                track_uri = result["track_uri"]
                captured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                log.info(f"Recognized: {title} by {artist}")
                update_ha_sensor(title, artist, album, spotify_url, captured_at)

                if track_uri and track_uri not in seen:
                    add_to_playlist(playlist_id, track_uri)
                    seen.add(track_uri)
                    log.info(f"Added to playlist: {title} by {artist}")
                elif track_uri in seen:
                    log.info("Already added this song, skipping.")
                else:
                    log.info("No Spotify URI found for this track.")
            else:
                log.info("No match.")

        except Exception as e:
            log.error(f"Error: {e}")

        time.sleep(LISTEN_INTERVAL)


if __name__ == "__main__":
    main()
