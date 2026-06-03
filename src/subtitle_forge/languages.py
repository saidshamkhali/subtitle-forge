LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fa": "Persian/Farsi",
    "fas": "Persian/Farsi",
    "per": "Persian/Farsi",
}


def language_label(code_or_name: str | None) -> str:
    if not code_or_name:
        return "unspecified source language"
    return LANGUAGE_NAMES.get(code_or_name.lower(), code_or_name)
