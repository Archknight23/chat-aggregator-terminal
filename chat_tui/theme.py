"""Chaos Foundry Frutiger-Aero TUI palette.

Purple/orange/red on near-black. OG Xbox energy.
These are real hex strings — safe in both Rich Text styles and Textual CSS markup.
"""

# Backgrounds
C_BG     = "#0a0a0f"  # near-black, primary
C_PANEL  = "#15131c"  # slightly raised, panel borders
C_TICKER = "#1a1726"  # darker band

# Text
C_FG     = "#e8e8f0"  # primary foreground (off-white)
C_DIM    = "#6b6b7a"  # secondary, metadata
C_DIM2   = "#7a7a8c"  # slightly less dim

# Accents
C_ORANGE = "#ff6b1a"  # primary — section headers, focused borders
C_PURPLE = "#a855f7"  # secondary — borders, :: brackets
C_RED    = "#ff3366"  # alerts, raids, errors
C_YELLOW = "#ffd23f"  # warnings, rewards
C_GREEN  = "#7fff5a"  # success, sent status
C_BLUE   = "#6cc5ff"  # info, links

# Platform colors
C_TWITCH  = "#a970ff"  # twitch purple
C_YOUTUBE = "#ff4444"  # youtube red
C_KICK    = "#53fc18"  # kick green
C_LOCAL   = "#ff6b1a"  # local = orange
C_SYSTEM  = "#ffd23f"  # system messages = yellow


def platform_color(platform: str) -> str:
    return {
        "twitch": C_TWITCH,
        "youtube": C_YOUTUBE,
        "kick": C_KICK,
        "local": C_LOCAL,
        "system": C_SYSTEM,
    }.get(platform or "", C_FG)


def severity_color(text: str) -> str:
    s = (text or "").upper()
    if "RAID" in s or "ERROR" in s or "FAIL" in s:
        return C_RED
    if "REWARD" in s or "REDEEM" in s:
        return C_YELLOW
    if "HOST" in s:
        return C_PURPLE
    if "SENT" in s or "OK" in s or "CONNECT" in s:
        return C_GREEN
    return C_BLUE