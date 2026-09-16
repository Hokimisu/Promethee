"""Pure text preparation for the documented VoxCPM2 controls; no model imports.

Sources: https://voxcpm.readthedocs.io/en/latest/cookbook.html
https://voxcpm.readthedocs.io/en/latest/models/voxcpm2.html#style-control
Only punctuation supplies pause hints. No measured pause or SSML is implemented.
"""

import re

MAX_TEXT_CHARS = 1000
MAX_STYLE_CHARS = 1000
SUPPORTED_TAGS = (
    "[laughing]",
    "[sigh]",
    "[Uhm]",
    "[Shh]",
    "[Question-ah]",
    "[Question-ei]",
    "[Question-en]",
    "[Question-oh]",
    "[Surprise-wa]",
    "[Surprise-yo]",
    "[Dissatisfaction-hnn]",
)
_BRACKET = re.compile(r"\[[^\[\]]*\]")
_MARKUP = re.compile(r"<\s*/?\s*[A-Za-z][^>]*(?:>|$)")
_PARENTHESES = str.maketrans("", "", "()（）")


def prepare_speech_text(text, style=""):
    """Return spoken/display text, cleaned style, target_text and ordered tags.

    Non-verbal tags retain their documented spelling and case in spoken_text;
    display_text omits them. Invalid controls fail before any generation. Only
    whitespace is compacted in spoken text: punctuation and Unicode are intact.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
        raise ValueError("text must contain 1 to 1000 characters.")
    if style is None:
        style = ""
    if not isinstance(style, str) or len(style) > MAX_STYLE_CHARS:
        raise ValueError("style must be a string of at most 1000 characters.")
    if _MARKUP.search(text) or _MARKUP.search(style):
        raise ValueError("SSML and XML controls are not supported; use ordinary punctuation.")
    if "[" in style or "]" in style:
        raise ValueError("Non-verbal tags belong in spoken text, not in the style description.")

    spoken = " ".join(text.split())
    tags = _BRACKET.findall(spoken)
    untagged = _BRACKET.sub(" ", spoken)
    if any(tag not in SUPPORTED_TAGS for tag in tags) or "[" in untagged or "]" in untagged:
        raise ValueError(
            "Use only the documented non-verbal tags, with their exact spelling and case."
        )
    display = " ".join(untagged.split())
    if tags:
        # Removing a tag before a comma/full stop must not leave "word ,".
        # Keep spaces before French ; : ? ! and keep every punctuation mark.
        display = re.sub(r"\s+([,.…])", r"\1", display)
    if not display:
        raise ValueError(
            "Spoken text must also contain text for display, not only non-verbal tags."
        )

    # Same half/full-width parenthesis removal as the official demonstration.
    cleaned_style = " ".join(style.translate(_PARENTHESES).split())
    target = f"({cleaned_style}){spoken}" if cleaned_style else spoken
    return {
        "spoken_text": spoken,
        "display_text": display,
        "style": cleaned_style,
        "target_text": target,
        "nonverbal_tags": tags,
    }
