#!/bin/bash
set -e

CONFIG_DIR="/home/particle/music-tracker/config"
CONFIG_FILE="$CONFIG_DIR/config.env"
SERVICE_FILE="/etc/systemd/system/music-tracker.service"
SCRIPT_DIR="/home/particle/music-tracker/scripts"

echo "======================================"
echo "  Tachyon Music Tracker Setup Wizard  "
echo "======================================"
echo ""

read -p "AudD API key (get one at audd.io): " AUDD_API_KEY
read -p "Spotify Client ID: " SPOTIFY_CLIENT_ID
read -s -p "Spotify Client Secret: " SPOTIFY_CLIENT_SECRET
echo ""
read -p "Spotify Redirect URI [http://127.0.0.1:8888/callback]: " SPOTIFY_REDIRECT_URI
SPOTIFY_REDIRECT_URI="${SPOTIFY_REDIRECT_URI:-http://127.0.0.1:8888/callback}"
read -p "Playlist name [Tachyon Heard This]: " PLAYLIST_NAME
PLAYLIST_NAME="${PLAYLIST_NAME:-Tachyon Heard This}"
read -p "Tachyon IP address [10.0.10.200]: " TACHYON_IP
TACHYON_IP="${TACHYON_IP:-10.0.10.200}"
read -p "Record duration in seconds [10]: " RECORD_SECONDS
RECORD_SECONDS="${RECORD_SECONDS:-10}"
read -p "Listen interval in seconds [30]: " LISTEN_INTERVAL
LISTEN_INTERVAL="${LISTEN_INTERVAL:-30}"

echo ""
echo "Auto-detecting ALSA mixer controls..."
NUMIDS=()
for name in "MultiMedia1 Mixer PRI_MI2S_TX" "PRI_MI2S_TX Channels" \
            "PRI_MI2S_TX SampleRate" "PRI_MI2S_TX Format" \
            "PRI_MI2S_TX Bit Format" "PRIM_MI2S_TX MUX" \
            "ADC MUX0" "ADC1"; do
    id=$(amixer -D hw:0 controls 2>/dev/null | grep -i "$name" | grep -o 'numid=[0-9]*' | head -1 | cut -d= -f2)
    NUMIDS+=("$id")
    echo "  $name -> numid=${id:-NOT FOUND}"
done

mkdir -p "$SCRIPT_DIR"
cat > "$SCRIPT_DIR/init_audio_capture.sh" << EOF
#!/bin/bash
set -e
echo "Setting up audio capture path..."
amixer -D hw:0 cset numid=${NUMIDS[0]:-6728} "One"
amixer -D hw:0 cset numid=${NUMIDS[1]:-5225} 192,192
amixer -D hw:0 cset numid=${NUMIDS[2]:-5227} 8
amixer -D hw:0 cset numid=${NUMIDS[3]:-5228} 8
amixer -D hw:0 cset numid=${NUMIDS[4]:-5226} 0
amixer -D hw:0 cset numid=${NUMIDS[5]:-6746} "Line 1L"
amixer -D hw:0 cset numid=${NUMIDS[6]:-6750} "left data = left ADC, right data = left ADC"
amixer -D hw:0 cset numid=${NUMIDS[7]:-599} on,on
echo "Audio capture path initialized."
EOF
chmod +x "$SCRIPT_DIR/init_audio_capture.sh"

echo ""
echo "Testing microphone (5 seconds)..."
bash "$SCRIPT_DIR/init_audio_capture.sh"
TEST_PCM=$(mktemp --suffix=.pcm)
timeout 5 tinycap "$TEST_PCM" -D 0 -d 0 -r 48000 -c 2 -b 16 -p 1024 -n 4 || true
SIZE=$(stat -c%s "$TEST_PCM" 2>/dev/null || echo 0)
rm -f "$TEST_PCM"
if [ "$SIZE" -gt 10000 ]; then
    echo "  Mic OK (captured ${SIZE} bytes)"
else
    echo "  WARNING: Mic may not be working (only ${SIZE} bytes)."
fi

mkdir -p "$CONFIG_DIR"
cat > "$CONFIG_FILE" << EOF
AUDD_API_KEY=$AUDD_API_KEY
SPOTIFY_CLIENT_ID=$SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET=$SPOTIFY_CLIENT_SECRET
SPOTIFY_REDIRECT_URI=$SPOTIFY_REDIRECT_URI
PLAYLIST_NAME=$PLAYLIST_NAME
TACHYON_IP=$TACHYON_IP
RECORD_SECONDS=$RECORD_SECONDS
LISTEN_INTERVAL=$LISTEN_INTERVAL
EOF
chmod 600 "$CONFIG_FILE"
echo "Config written to $CONFIG_FILE"

echo ""
echo "Installing Python dependencies..."
pip3 install -q spotipy requests python-dotenv

echo ""
echo "======================================"
echo "  Spotify Authorization"
echo "======================================"
echo "Run this on a machine with a browser:"
echo ""
echo "  python3 -c \""
echo "import spotipy; from spotipy.oauth2 import SpotifyOAuth"
echo "sp = spotipy.Spotify(auth_manager=SpotifyOAuth("
echo "  client_id='$SPOTIFY_CLIENT_ID',"
echo "  client_secret='$SPOTIFY_CLIENT_SECRET',"
echo "  redirect_uri='$SPOTIFY_REDIRECT_URI',"
echo "  scope='playlist-modify-public playlist-modify-private',"
echo "  cache_path='./spotify_cache.json'))"
echo "print(sp.current_user()['id'])\""
echo ""
echo "Then copy the cache file to the Tachyon:"
echo "  scp spotify_cache.json particle@$TACHYON_IP:/home/particle/music-tracker/.cache/spotify_cache.json"
echo ""
read -p "Press Enter once the cache file is in place..."

sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=Music Tracker
After=network.target sound.target

[Service]
Type=simple
User=particle
Environment=PULSE_RUNTIME_PATH=/run/user/1000/pulse
ExecStartPre=/home/particle/music-tracker/scripts/init_audio_capture.sh
ExecStart=/usr/bin/python3 /home/particle/music-tracker/music_tracker.py
Restart=always
RestartSec=10
StandardOutput=append:/home/particle/music-tracker/logs/tracker.log
StandardError=append:/home/particle/music-tracker/logs/tracker.log

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable music-tracker
sudo systemctl start music-tracker

echo ""
echo "======================================"
echo "  Setup Complete!"
echo "======================================"
sudo systemctl status music-tracker --no-pager
echo ""
echo "Watch logs: tail -f /home/particle/music-tracker/logs/tracker.log"
