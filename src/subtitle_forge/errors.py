class SubtitleForgeError(Exception):
    """Base exception for expected Subtitle Forge failures."""


class SubtitleParseError(SubtitleForgeError):
    """Raised when a subtitle file cannot be parsed."""


class ProviderError(SubtitleForgeError):
    """Raised when a translation provider fails."""


class TranslationValidationError(SubtitleForgeError):
    """Raised when provider output does not match the requested cues."""
