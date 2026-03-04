"""Theme configuration for MCPDB UI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ThemeColors:
    """Color palette for the UI."""

    primary: str = "#1976D2"
    secondary: str = "#424242"
    accent: str = "#82B1FF"
    background: str = "#121212"
    surface: str = "#1E1E1E"
    text: str = "#FFFFFF"
    text_secondary: str = "#B0B0B0"
    success: str = "#4CAF50"
    warning: str = "#FF9800"
    error: str = "#F44336"
    info: str = "#2196F3"


@dataclass
class ThemeConfig:
    """Full theme configuration."""

    name: str = "dark"
    colors: ThemeColors = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.colors is None:
            self.colors = ThemeColors()


DARK_THEME = ThemeConfig(name="dark")

LIGHT_THEME = ThemeConfig(
    name="light",
    colors=ThemeColors(
        primary="#1976D2",
        secondary="#757575",
        accent="#82B1FF",
        background="#FAFAFA",
        surface="#FFFFFF",
        text="#212121",
        text_secondary="#757575",
        success="#4CAF50",
        warning="#FF9800",
        error="#F44336",
        info="#2196F3",
    ),
)


def get_theme(name: str = "dark") -> ThemeConfig:
    """Get theme by name."""
    if name == "light":
        return LIGHT_THEME
    return DARK_THEME
