"""CPU checks for the documented VoxCPM2 text controls."""

import pytest
from speech_text import SUPPORTED_TAGS, prepare_speech_text


@pytest.mark.parametrize("tag", SUPPORTED_TAGS)
def test_documented_tag_reaches_speech_but_not_display(tag):
    result = prepare_speech_text(f"{tag} Hé, tu es là… quelle journée !", "Warm voice.")
    assert result["spoken_text"] == f"{tag} Hé, tu es là… quelle journée !"
    assert result["display_text"] == "Hé, tu es là… quelle journée !"
    assert result["nonverbal_tags"] == [tag]
    assert result["target_text"] == f"(Warm voice.){result['spoken_text']}"


def test_synthetic_prompt_is_preserved_exactly():
    # A public text fixture, not a copy of a voice qualification or conversation.
    text = "Voilà, je suis prête… Et toi, ça va ?"
    instruction = "Warm conversational delivery, then curious."
    result = prepare_speech_text(text, instruction)
    assert result["spoken_text"] == result["display_text"] == text
    assert result["style"] == instruction
    assert result["target_text"] == f"({instruction}){text}"


def test_nested_and_fullwidth_style_parentheses_get_one_wrapper():
    result = prepare_speech_text("C’est déjà fini ?", " (Warm (soft) voice) （relaxed） ")
    assert result["style"] == "Warm soft voice relaxed"
    assert result["target_text"] == "(Warm soft voice relaxed)C’est déjà fini ?"
    assert prepare_speech_text(result["spoken_text"], result["style"]) == result


@pytest.mark.parametrize("style", [None, "", " ((（ ）)) "])
def test_absent_direction_has_no_wrapper(style):
    assert prepare_speech_text("Bonjour.", style)["target_text"] == "Bonjour."


def test_tag_removal_preserves_french_punctuation_and_accents():
    result = prepare_speech_text("  Écoute [sigh], c’est étrange… [Uhm] Tu crois ? Oui !\n")
    assert result["spoken_text"] == "Écoute [sigh], c’est étrange… [Uhm] Tu crois ? Oui !"
    assert result["display_text"] == "Écoute, c’est étrange… Tu crois ? Oui !"
    assert result["nonverbal_tags"] == ["[sigh]", "[Uhm]"]


@pytest.mark.parametrize(
    "text",
    [
        "[Laughing] Bonjour",
        "[pause:1s] Bonjour",
        "[rire] Bonjour",
        "[] Bonjour",
        "[[sigh]] Bonjour",
        "[sigh Bonjour",
        "sigh] Bonjour",
        "[sigh] [laughing]",
        '<break time="1s"/> Bonjour',
        "<speak>Bonjour</speak>",
        "Bonjour <break",
        None,
        123,
        "",
        "  ",
        "x" * 1001,
    ],
)
def test_invalid_text_fails_explicitly(text):
    with pytest.raises(ValueError):
        prepare_speech_text(text)


@pytest.mark.parametrize("style", [123, [], "x" * 1001, "[sigh]", "<prosody rate='slow'>"])
def test_invalid_style_fails_explicitly(style):
    with pytest.raises(ValueError):
        prepare_speech_text("Bonjour.", style)


def test_ordinary_comparison_and_maximum_lengths_are_allowed():
    assert prepare_speech_text("2 < 3 et 4 > 2.")["display_text"] == "2 < 3 et 4 > 2."
    result = prepare_speech_text("é" * 1000, "a" * 1000)
    assert len(result["spoken_text"]) == 1000
    assert len(result["style"]) == 1000
