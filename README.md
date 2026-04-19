# meshcore-bots

Matrix bots that piggyback on [meshcore-matrix-bridge](https://github.com/Basti77/meshcore-matrix-bridge). Each bot is its own Matrix user and its own process; they post to channel rooms and the bridge forwards the messages onto the LoRa mesh.

No meshcore-lib dependency here — bots speak Matrix, the bridge speaks LoRa.

## Bots

### `meshbot-wetter`

Posts a 3-point weather ticker (now / +6 h / +12 h) every 6 h into a Matrix room bound to a mesh channel (typically `#wetter`). Uses Windy Point Forecast API (ICON-EU model). Output is crafted to fit LoRa payload limits — the bridge splits at 140 chars if needed.

**Example output**

```
🌦 OWL Langenberg 14:00
Jetzt: 12°C SW18 (B35) wolkig
+6h: 14°C S22 (B38) Regen 0.8mm
+12h: 9°C W15 bedeckt
```

## Architecture

```
meshbot-wetter ─(Matrix)─▶ #mesh-wetter room ─(bridge)─▶ LoRa mesh, channel "wetter"
meshbot-mention ─(Matrix)─▶ #mesh-nrw room ─(bridge)─▶ LoRa mesh, channel "nrw"   (future)
```

The bridge already forwards **every message** in a bound channel room onto the mesh. So a bot that posts into that room is automatically heard over LoRa — no extra IPC needed.

Future: an optional HTTP endpoint on the bridge for Mesh-DM sends (bot → specific contact).

## Install (one-shot, per bot)

```bash
cd ~
git clone https://github.com/Basti77/meshcore-bots.git
python3 -m venv ~/.local/venvs/meshcore-bots
~/.local/venvs/meshcore-bots/bin/pip install -e ~/meshcore-bots
```

Create the Matrix user (example: Synapse with shared-secret registration):

```bash
docker exec matrix-synapse register_new_matrix_user \
  -c /data/homeserver.yaml http://localhost:8008 \
  -u meshwetter -p "$(openssl rand -base64 18)" --no-admin
```

Store token/password in `~/.meshcore-bot-secrets/wetter.env` (see `bots/wetter/wetter.env.example`).

Enable systemd-user unit:

```bash
mkdir -p ~/.config/systemd/user
cp ~/meshcore-bots/systemd/meshbot-wetter.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now meshbot-wetter.service
```

Make sure `loginctl enable-linger $USER` is set so the unit starts without an active login.

## Writing your own bot

1. Drop a package under `bots/yourbot/`.
2. Import `shared.matrix_sender.SimpleMatrixSender` (login + `send_text`).
3. Add a systemd unit under `systemd/` and an env-example next to your `main.py`.
4. Create the Matrix user, store the token in `~/.meshcore-bot-secrets/yourbot.env`.
5. Invite the bot to the channel room(s) it should post into, or let it join via alias.

Rule of thumb: **bots stay unaware of the mesh.** The bridge is the radio; bots just chat on Matrix.

## License

MIT — see [LICENSE](LICENSE).
