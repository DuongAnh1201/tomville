import pytest
from rich.cells import cell_len

from tomville.core import sprites as sprites_mod
from tomville.core.sprites import (
    DEFAULT_PETS,
    STYLES,
    Sprites,
    SpriteError,
    available_pets,
    load_frames,
    parse_frames,
)


def test_parse_frames_split_on_dashes():
    assert parse_frames("🐱\n---\n😺\n") == ["🐱", "😺"]
    assert parse_frames("^^") == ["^^"]
    assert parse_frames("a \n---  \n b\n---\n") == ["a ", " b"]


def test_parse_frames_rejects_empty_and_multi_line():
    with pytest.raises(SpriteError):
        parse_frames("\n---\n")
    with pytest.raises(SpriteError):
        parse_frames("ab\ncd\n")


def test_builtin_pets_are_cat_dog_sheep_with_two_cell_frames():
    assert available_pets() == ["cat", "dog", "sheep"]
    for pet in available_pets():
        for style in STYLES:
            frames = load_frames(pet, style)
            assert len(frames) >= 2
            assert {cell_len(f) for f in frames} == {2}, (pet, style)


def test_ascii_frames_are_plain_ascii():
    for pet in available_pets():
        assert all(f.isascii() for f in load_frames(pet, "ascii"))


def test_every_agent_kind_has_a_default_pet():
    s = Sprites()
    assert s.pet_for("claude", "claude") == DEFAULT_PETS["claude"] == "cat"
    assert s.pet_for("codex1", "codex") == "dog"
    for kind in ("gemini", "opencode", "something-new", "unknown"):
        assert s.pet_for("x", kind) in available_pets()


def test_pet_override_and_unknown_pet():
    s = Sprites(pets={"codex1": "sheep"})
    assert s.pet_for("codex1", "codex") == "sheep"
    assert s.pet_for("codex2", "codex") == "dog"
    with pytest.raises(SpriteError, match="unknown pet"):
        Sprites(pets={"codex1": "fox"})
    with pytest.raises(SpriteError, match="unknown style"):
        Sprites("neon")


def test_blocks_falls_back_to_ascii_with_one_notice():
    s = Sprites("blocks")
    assert s.style == "ascii"
    assert s.take_notes() == ["Block pixels arrive in M12; using ASCII sprites"]
    assert s.take_notes() == []


def test_from_settings():
    from tomville.core.settings import OfficeSettings

    s = Sprites.from_settings(OfficeSettings(style="ascii", pets={"codex1": {"sprite": "sheep", "color": "#abcdef"}}))
    assert s.style == "ascii" and s.pet_for("codex1", "codex") == "sheep"


def test_style_cycles_between_emoji_and_ascii():
    s = Sprites()
    assert s.style == "emoji"
    assert s.cycle_style() == "ascii"
    assert s.cycle_style() == "emoji"
    assert s.frames("claude", "claude") == load_frames("cat", "emoji")


def test_wrong_width_emoji_falls_back_to_ascii_with_a_note(monkeypatch):
    real = sprites_mod.load_frames

    def fake(pet, style):
        return ["🧑‍💻x"] if (pet, style) == ("cat", "emoji") else real(pet, style)

    monkeypatch.setattr(sprites_mod, "load_frames", fake)
    s = Sprites()
    assert s.frames("claude", "claude") == real("cat", "ascii")
    notes = s.take_notes()
    assert len(notes) == 1 and "cat" in notes[0]
    s.frames("claude", "claude")
    assert s.take_notes() == []
