# Tachyon Music Tracker

Always-on music recognition service for the [Particle Tachyon 8GB](https://docs.particle.io/reference/datasheets/tachyon/tachyon-datasheet/) SBC. Listens via the 3.5mm mic input, recognizes songs using the AudD API, and automatically adds them to a Spotify playlist.

## Hardware
- Particle Tachyon 8GB NA (TACH8NA)
- 3.5mm TRRS audio adapter (mic input)

## Features
- Continuous background listening via systemd service
- Qualcomm audio stack (ALSA) mic initialization
- Song fingerprinting via [AudD](https://audd.io)
- Automatic Spotify playlist management via [Spotipy](https://spotipy.readthedocs.io)
- Duplicate detection (won't add the same song twice per session)

## Quick Setup

```bash
bash setup_music_tracker.sh
```

The wizard will:
1. Prompt for AudD and Spotify API credentials
2. Auto-detect ALSA mixer control numids for your board
3. Test the microphone
4. Guide you through Spotify OAuth (can be done from another machine)
5. Create and enable the systemd service

## Manual Setup

### Dependencies
```bash
pip3 install spotipy requests python-dotenv
sudo apt install ffmpeg
```

### Config
Copy `config/config.env.example` to `config/config.env` and fill in your credentials:
```bash
cp config/config.env.example config/config.env
nano config/config.env
```

### Audio
The Qualcomm audio stack on the Tachyon requires ALSA mixer controls to be set before capture works. `scripts/init_audio_capture.sh` handles this automatically and is run via systemd `ExecStartPre`.

### Spotify OAuth (headless)
Run the auth flow on a machine with a browser, then copy the token cache to the Tachyon:
```bash
scp spotify_cache.json particle@<tachyon-ip>:/home/particle/music-tracker/.cache/spotify_cache.json
```

## Service Management
```bash
sudo systemctl status music-tracker
sudo systemctl restart music-tracker
tail -f /home/particle/music-tracker/logs/tracker.log
```

## Project Structure
```
music-tracker/
├── music_tracker.py           # Main service
├── setup_music_tracker.sh     # Interactive setup wizard
├── scripts/
│   └── init_audio_capture.sh  # ALSA mixer init for Qualcomm audio
├── config/
│   ├── config.env             # Your credentials (gitignored)
│   └── config.env.example     # Template for new installs
└── logs/                      # Runtime logs (gitignored)
```
