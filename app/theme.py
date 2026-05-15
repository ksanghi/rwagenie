"""
RWAGenie theme — placeholder values, mostly mirrors AccGenie's palette
for v0.1 while branding/marketing decides on the real colours.

Pages import this module instead of `ui.theme` directly so the RWA
shell can diverge from AG's look later without touching pages.

Update strategy: when marketing settles, replace the values in
RWA_THEME below + swap the logo path. Pages don't need to change.
"""
from __future__ import annotations

# Lazy-import AG's theme so RWAGenie can override individual tokens
# rather than redefining the whole palette. v0.1 just re-exports.
try:
    from ui.theme import THEME as _AG_THEME, get_stylesheet as _ag_get_stylesheet
except Exception:
    # Defensive: if AG isn't on sys.path yet we still want this module to
    # import. Real launches go through main.py which bootstraps the path.
    _AG_THEME = {
        "bg":              "#0F172A",
        "bg_card":         "#1E293B",
        "bg_input":        "#0F172A",
        "bg_hover":        "#334155",
        "bg_selected":     "#1E40AF",
        "bg_sidebar":      "#020617",
        "accent":          "#635BFF",
        "accent_hover":    "#7C75FF",
        "accent_dim":      "#1E1A4D",
        "success":         "#00D4AA",
        "warning":         "#F5A524",
        "danger":          "#EF4444",
        "text_primary":    "#F1F5F9",
        "text_secondary":  "#94A3B8",
        "text_dim":        "#64748B",
        "border":          "#334155",
        "border_error":    "#EF4444",
    }
    _ag_get_stylesheet = None


# Token overrides — empty for v0.1. Marketing-driven changes land here.
_RWA_OVERRIDES: dict[str, str] = {
    # Example for when branding lands:
    # "accent":       "#10B981",     # RWAGenie green
    # "accent_hover": "#34D399",
    # "accent_dim":   "#064E3B",
}


THEME: dict[str, str] = {**_AG_THEME, **_RWA_OVERRIDES}


def get_stylesheet() -> str:
    """Whole-app stylesheet — same shape as AG's. When _RWA_OVERRIDES
    diverges enough that the AG sheet doesn't look right, fork the
    template here."""
    if _ag_get_stylesheet is None:
        return ""
    # AG's get_stylesheet() builds its sheet against ui.theme.THEME at
    # import time. When we override tokens, we want them reflected. The
    # cheapest way is to monkey-patch ui.theme.THEME before calling.
    try:
        import ui.theme as _ag_theme_mod
        _ag_theme_mod.THEME = THEME
    except Exception:
        pass
    return _ag_get_stylesheet()
