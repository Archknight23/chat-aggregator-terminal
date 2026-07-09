"""Chaos Foundry Frutiger-Aero TUI palette system.

Purple/orange/red on near-black. OG Xbox energy.
Multiple theme presets with live switching.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Theme:
    """A complete color theme for the TUI."""

    name: str
    description: str

    # Backgrounds
    bg_surface: str = "#0a0a0f"
    bg_panel: str = "#15131c"
    bg_ticker: str = "#1a1726"

    # Text
    fg_primary: str = "#e8e8f0"
    fg_dim: str = "#6b6b7a"
    fg_dim2: str = "#7a7a8c"

    # Accents
    accent_primary: str = "#ff6b1a"  # orange
    accent_secondary: str = "#a855f7"  # purple
    accent_alert: str = "#ff3366"  # red
    accent_warn: str = "#ffd23f"  # yellow
    accent_success: str = "#7fff5a"  # green
    accent_info: str = "#6cc5ff"  # blue

    # Platform colors
    platform_twitch: str = "#a970ff"
    platform_youtube: str = "#ff4444"
    platform_kick: str = "#53fc18"
    platform_local: str = "#ff6b1a"
    platform_system: str = "#ffd23f"

    # Border style
    border_style: Literal["solid", "thick", "rounded", "double"] = "solid"

    # Animation speed (seconds)
    animation_duration: float = 0.2

    @property
    def css_variables(self) -> str:
        """Return CSS variable definitions for this theme."""
        return f"""
        $primary: {self.accent_secondary};
        $secondary: {self.accent_primary};
        $surface: {self.bg_surface};
        $background: {self.bg_surface};
        $panel: {self.bg_panel};
        $fg: {self.fg_primary};
        $fg-dim: {self.fg_dim};
        $alert: {self.accent_alert};
        $warn: {self.accent_warn};
        $success: {self.accent_success};
        $info: {self.accent_info};
        """


# Pre-built themes
THEMES = {
    "frutiger_aero": Theme(
        name="Frutiger Aero",
        description="OG Chaos Foundry — purple/orange/red on near-black",
        bg_surface="#0a0a0f",
        bg_panel="#15131c",
        bg_ticker="#1a1726",
        fg_primary="#e8e8f0",
        fg_dim="#6b6b7a",
        accent_primary="#ff6b1a",
        accent_secondary="#a855f7",
        accent_alert="#ff3366",
        accent_warn="#ffd23f",
        accent_success="#7fff5a",
        accent_info="#6cc5ff",
        platform_twitch="#a970ff",
        platform_youtube="#ff4444",
        platform_kick="#53fc18",
        platform_local="#ff6b1a",
        platform_system="#ffd23f",
        border_style="solid",
    ),
    "neon_dream": Theme(
        name="Neon Dream",
        description="Cyberpunk vibrance — cyan/magenta/high contrast",
        bg_surface="#050508",
        bg_panel="#0f0f1a",
        bg_ticker="#12121f",
        fg_primary="#f0f0ff",
        fg_dim="#5a5a7a",
        accent_primary="#00ffff",
        accent_secondary="#ff00ff",
        accent_alert="#ff2244",
        accent_warn="#ffaa00",
        accent_success="#00ff88",
        accent_info="#00ccff",
        platform_twitch="#c084fc",
        platform_youtube="#ff4444",
        platform_kick="#53fc18",
        platform_local="#00ffff",
        platform_system="#ffaa00",
        border_style="thick",
        animation_duration=0.3,
    ),
    "midnight_oxide": Theme(
        name="Midnight Oxide",
        description="Desaturated industrial — steel/rust/amber",
        bg_surface="#0c0c0e",
        bg_panel="#18181c",
        bg_ticker="#1c1c22",
        fg_primary="#d0d0d8",
        fg_dim="#5a5a62",
        accent_primary="#cc5500",
        accent_secondary="#667788",
        accent_alert="#cc3344",
        accent_warn="#ffaa33",
        accent_success="#55aa55",
        accent_info="#5588aa",
        platform_twitch="#9966cc",
        platform_youtube="#cc4444",
        platform_kick="#66cc33",
        platform_local="#cc5500",
        platform_system="#ffaa33",
        border_style="rounded",
        animation_duration=0.15,
    ),
    "ghost_protocol": Theme(
        name="Ghost Protocol",
        description="Minimal monochrome — green terminal vibes",
        bg_surface="#000500",
        bg_panel="#001000",
        bg_ticker="#001500",
        fg_primary="#c0ffc0",
        fg_dim="#406040",
        accent_primary="#00ff00",
        accent_secondary="#00cc00",
        accent_alert="#ff4444",
        accent_warn="#ffff44",
        accent_success="#00ff00",
        accent_info="#44ff44",
        platform_twitch="#88ff88",
        platform_youtube="#ff6666",
        platform_kick="#88ff88",
        platform_local="#00ff00",
        platform_system="#ffff44",
        border_style="solid",
        animation_duration=0.1,
    ),
}

THEME_ORDER = ["frutiger_aero", "neon_dream", "midnight_oxide", "ghost_protocol"]


def get_theme(name: str) -> Theme:
    """Get a theme by name."""
    return THEMES.get(name, THEMES["frutiger_aero"])


def cycle_theme(current_name: str) -> tuple[str, Theme]:
    """Cycle to the next theme. Returns (new_name, new_theme)."""
    try:
        idx = THEME_ORDER.index(current_name)
    except ValueError:
        idx = -1
    next_idx = (idx + 1) % len(THEME_ORDER)
    next_name = THEME_ORDER[next_idx]
    return next_name, THEMES[next_name]


# Legacy color constants for backward compatibility (point to default theme)
DEFAULT = THEMES["frutiger_aero"]
C_BG = DEFAULT.bg_surface
C_PANEL = DEFAULT.bg_panel
C_TICKER = DEFAULT.bg_ticker
C_FG = DEFAULT.fg_primary
C_DIM = DEFAULT.fg_dim
C_DIM2 = DEFAULT.fg_dim2
C_ORANGE = DEFAULT.accent_primary
C_PURPLE = DEFAULT.accent_secondary
C_RED = DEFAULT.accent_alert
C_YELLOW = DEFAULT.accent_warn
C_GREEN = DEFAULT.accent_success
C_BLUE = DEFAULT.accent_info
C_TWITCH = DEFAULT.platform_twitch
C_YOUTUBE = DEFAULT.platform_youtube
C_KICK = DEFAULT.platform_kick
C_LOCAL = DEFAULT.platform_local
C_SYSTEM = DEFAULT.platform_system


def platform_color(platform: str, theme: Theme | None = None) -> str:
    """Get the color for a platform."""
    t = theme or DEFAULT
    return {
        "twitch": t.platform_twitch,
        "youtube": t.platform_youtube,
        "kick": t.platform_kick,
        "local": t.platform_local,
        "system": t.platform_system,
    }.get(platform or "", t.fg_primary)


def severity_color(text: str, theme: Theme | None = None) -> str:
    """Get color based on severity keywords."""
    t = theme or DEFAULT
    s = (text or "").upper()
    if "RAID" in s or "ERROR" in s or "FAIL" in s:
        return t.accent_alert
    if "REWARD" in s or "REDEEM" in s:
        return t.accent_warn
    if "HOST" in s:
        return t.accent_secondary
    if "SENT" in s or "OK" in s or "CONNECT" in s:
        return t.accent_success
    return t.accent_info
