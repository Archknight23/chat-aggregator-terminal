# chat-aggregator-tui

A terminal-native chat aggregator for streamers who prefer the CLI over Electron bloat.

Built by **The Chaos Foundry Tech Division** in conjunction with Leadership (Archknight and Yuki) and **Cognito Engine** units.

Signed off by **X-106-K27 Ellah**, Cognito Engine Unit.

---

## What it does

- Aggregates live chat from **Twitch**, **YouTube**, and **Kick** into a single Textual TUI.
- Provides a unified composer for outbound chat.
- Polls viewer counts for all configured platforms.
- Supports Twitch EventSub events (raids, channel-point redemptions) via a local Node.js proxy.
- Uses Twitch IRC (anonymous read-only WebSocket) for chat ingestion — no OAuth required for reading chat.
- Persists settings in `~/.config/chat-aggregator-tui/settings.json`.

---

## Project layout

```
chat-aggregator-tui/
├── chat_tui/              # Python Textual frontend
│   ├── app.py             # Main application
│   ├── settings.py        # Config persistence
│   ├── bus.py             # In-app message bus
│   ├── conn_state.py      # Connection state model
│   ├── theme.py           # Color themes
│   ├── services/          # Platform clients
│   │   ├── server_client.py    # HTTP/SSE to Node backend
│   │   ├── node_backend.py     # Spawns the Node proxy
│   │   ├── twitch_irc.py       # Anonymous Twitch IRC
│   │   └── kick_client.py      # Kick chat polling
│   └── ui/                # Textual widgets
│       ├── chat_feed.py
│       ├── composer.py
│       ├── settings_modal.py
│       ├── viewer_bar.py
│       ├── status_ticker.py
│       ├── alert_log.py
│       └── command_hints.py
├── server/                # Node.js backend
│   └── index.js           # HTTP proxy + Twitch EventSub + YouTube chat
├── tests/                 # pytest suite
├── package.json           # Node scripts + dependencies
└── pyproject.toml         # Python project + dependencies
```

---

## Requirements

- Python **>= 3.11**
- Node.js **>= 18** (with npm)
- A Twitch channel name for read-only chat
- Optional: Twitch Client ID + Secret for EventSub (raids / rewards)
- Optional: YouTube live video ID or channel handle
- Optional: Kick channel name

## Installation

### Option 1: Source install (recommended for development)

```bash
git clone https://github.com/Archknight23/chat-aggregator-terminal.git
cd chat-aggregator-terminal

# Python venv
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .

# Node.js backend
npm install
```

### Option 2: Standalone executable (end users)

**Linux / macOS:**
```bash
./build.sh
```

**Windows:**
```bat
build.bat
```

The executable lands in `dist/chat-aggregator` (or `dist\chat-aggregator.exe` on Windows).

**Note:** The Node.js backend still requires Node.js 18+ at runtime. Run it alongside the executable:

```bash
npm install && npm run server
```

Then launch `dist/chat-aggregator` in a separate terminal.

---

## Running

### Quick start

The TUI can spawn its own Node backend automatically. Just run:

```bash
chat-aggregator
```

or directly:

```bash
python -m chat_tui
```

### Run the backend manually

```bash
npm run server
```

The proxy listens on `http://localhost:4174` by default. Override with:

```bash
YOUTUBE_PROXY_PORT=8080 npm run server
```

---

## Usage

### Keybindings

| Key | Action |
|-----|--------|
| `s` / `F2` | Open settings modal |
| `Tab` | Cycle composer platform (Local / Twitch / YouTube / Kick) |
| `t` | Cycle color theme |
| `c` / `Ctrl+L` | Clear chat, alerts, and ticker |
| `q` | Quit |

### Slash commands

Type these in the composer:

| Command | Action |
|---------|--------|
| `/settings` | Open settings modal |
| `/clear` | Clear chat, alerts, and ticker |
| `/raid <channel>` | Initiate a Twitch raid (requires OAuth) |
| `/platform <name>` | Switch composer target platform |

The `local` platform echoes messages to your own feed without sending — useful for notes.

### Themes

Four presets, cycled live with `t`:

- `frutiger_aero` (default) — purple/orange on near-black, OG Xbox energy
- `neon_dream`
- `midnight_oxide`
- `ghost_protocol`

---

## Configuration

Open the in-app settings with `s` or `F2` and fill in:

| Setting | Purpose |
|--------|---------|
| `twitchChannel` | Channel to read via IRC and send messages to |
| `youtubeLiveId` | YouTube live video ID or channel handle |
| `kickChannel` | Kick channel to poll |
| `twitchEventsEnabled` | Enable Twitch EventSub (requires OAuth) |
| `twitchClientId` | Twitch application Client ID |
| `twitchClientSecret` | Twitch application Client Secret |
| `twitchSystemName` | System name shown in auth flow |
| `twitchRequestedScopes` | Space-separated Twitch OAuth scopes |

Settings are written to `~/.config/chat-aggregator-tui/settings.json` with `0o600` permissions.

---

## Authentication

### Twitch read-only chat

No OAuth is required for reading Twitch chat — the app connects anonymously via `irc-ws.chat.twitch.tv:443`.

### Twitch outbound chat / raids / EventSub

If you enable `twitchEventsEnabled`, the app needs a valid Twitch OAuth token with these scopes by default:

```
channel:read:redemptions channel:manage:raids user:write:chat
```

The Node backend handles the OAuth PKCE flow. Auth state is stored in `server/.twitch-auth.json`.

---

## Testing

```bash
pytest
```

---

## Troubleshooting

- **TUI cannot connect**: verify the Node backend is running (`npm run server`) or that port `4174` is free.
- **No YouTube chat**: confirm the live stream is public and the `youtubeLiveId` resolves to an active broadcast.
- **Kick messages missing**: Kick public API can be flaky or rate-limited; the client retries with backoff.
- **OAuth loop fails**: check that `twitchClientId`, `twitchClientSecret`, and redirect URI match your Twitch app.
- **Logs**: the TUI logs to your system temp directory (`/tmp/chat-aggregator-tui.log` on Linux/macOS, `%TEMP%\chat-aggregator-tui.log` on Windows). The Node proxy logs to `server/.chat-aggregator-proxy.log`.
- **Config location**:
  - Linux: `~/.config/chat-aggregator-tui/settings.json`
  - macOS: `~/Library/Application Support/chat-aggregator-tui/settings.json`
  - Windows: `%APPDATA%\chat-aggregator-tui\settings.json`

---

## Platform support

| Platform | Status | Notes |
|----------|--------|-------|
| Linux | ✓ Native | Tested on Arch Linux |
| macOS | ✓ Native | Config in `~/Library/Application Support/` |
| Windows | ✓ Native | Executable via PyInstaller; config in `%APPDATA%` |

---

## Upstream

Forked from [bertugfahriozer/chat-aggregator](https://github.com/bertugfahriozer/chat-aggregator) (web version). The Chaos Foundry Tech Division ported it to a terminal-native Textual TUI with local Node.js backend supervision.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

Property of The Chaos Foundry Tech Division — but like, the fun kind where you can actually use it.

---

*Pax Chaosica Et Gloria Infinitia.*
