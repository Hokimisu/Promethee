"""Source, correction and publication tests; all worlds and messages are test data."""

import json
import sqlite3

import pytest

from promethee.conversation import ConversationStore
from promethee.execution import ExecutionService
from promethee.memory import MemoryStore, initialize_vault
from promethee.migrations import migrate, read_world
from promethee.runtime import Runtime
from promethee.world import ActionError

pytest.importorskip("yaml")


def setup(tmp_path, name="world"):
    runtime = Runtime(
        tmp_path / name / "world.sqlite3", data_origin="session", session_kind="interactive"
    )
    service = ExecutionService(runtime)
    vault = initialize_vault(runtime, tmp_path / f"{name}-vault")
    turn = ConversationStore(service).begin("Developer fixture: this is a blue object.")
    return MemoryStore(service, vault), "user:" + turn["turn_id"]


def write(memory, source, note_id="note-blue", **kwargs):
    return memory.write(
        note_id,
        kind="summary",
        title="Blue object",
        text="It was blue.",
        sources=[source],
        **kwargs,
    )


def test_empty_memory_then_registered_note_and_source(tmp_path):
    memory, source = setup(tmp_path)
    before = memory.service.get_world()
    assert memory.search("")["notes"] == []
    write(memory, source)
    result = memory.search("BLUE")
    assert len(result["notes"]) == 1
    assert result["notes"][0]["sources"][0]["source_id"] == source
    assert memory.source(source)["content"].startswith("Developer fixture:")
    assert memory.service.get_world() == before
    assert memory.service.events() == []


@pytest.mark.parametrize(
    "origin,kind", [("fixture", None), ("session", None), ("session", "qualification")]
)
def test_noninteractive_worlds_cannot_create_or_open_memory(tmp_path, origin, kind):
    runtime = Runtime(tmp_path / "world.sqlite3", data_origin=origin, session_kind=kind)
    vault = tmp_path / "vault"
    with pytest.raises(ActionError):
        initialize_vault(runtime, vault)
    assert not vault.exists()
    with pytest.raises(ActionError):
        MemoryStore(ExecutionService(runtime), vault)


def test_sources_must_exist_in_this_world_and_failed_assistant_is_not_a_source(tmp_path):
    memory, source = setup(tmp_path)
    other, other_source = setup(tmp_path, "other")
    for sources in (
        [],
        [other_source],
        [source.replace("user:", "assistant:")],
        ["execution:absent"],
    ):
        with pytest.raises(ActionError):
            memory.write("bad", kind="summary", title="Bad", text="Unsupported", sources=sources)
    with pytest.raises(ActionError):
        MemoryStore(other.service, memory.vault)
    with pytest.raises(FileExistsError):
        initialize_vault(memory.service.runtime, memory.vault)


def test_terminal_execution_and_completed_assistant_sources_keep_their_kind(tmp_path):
    memory, user_source = setup(tmp_path)
    turn_id = user_source.removeprefix("user:")
    user_text = memory.source(user_source)["content"]
    ConversationStore(memory.service).finish(
        turn_id,
        {
            "type": "result",
            "turn_id": turn_id,
            "failed": False,
            "interrupted": False,
            "text": "A proposal",
            "messages": [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": "A proposal"},
            ],
        },
    )
    assistant = "assistant:" + turn_id
    memory.write(
        "proposal", kind="proposal", title="Proposal", text="A proposal", sources=[assistant]
    )
    with pytest.raises(ActionError, match="cannot attest"):
        memory.write(
            "claim", kind="observation", title="Claim", text="A claim", sources=[assistant]
        )
    item = memory.service.submit(
        "request",
        memory.service.get_world()["revision"],
        {"kind": "move", "args": {"position": [0.2, 0.3]}},
    )
    assert item["status"] == "rejected"
    source = memory.source("execution:request")
    assert json.loads(source["content"])["status"] == "rejected"
    memory.write(
        "rejection",
        kind="observation",
        title="Rejection",
        text="The request was rejected.",
        sources=["execution:request"],
    )
    assert memory.read("rejection")["sources"][0]["kind"] == "execution"


def test_failed_database_commit_never_publishes_a_note(tmp_path):
    memory, source = setup(tmp_path)
    with memory.service.runtime.connection() as conn:
        conn.execute("""CREATE TRIGGER fail_memory BEFORE INSERT ON memory_notes
            BEGIN SELECT RAISE(ABORT, 'memory rollback'); END;""")
    with pytest.raises(sqlite3.IntegrityError, match="memory rollback"):
        write(memory, source)
    assert not memory._path("note-blue").exists()
    assert memory.search("")["notes"] == []


def test_reading_a_project_note_does_not_resume_it(tmp_path):
    memory, source = setup(tmp_path)
    project = {"id": "paused-project", "status": "paused", "cursor": 0, "steps": []}
    with memory.service.runtime.connection() as conn:
        conn.execute("INSERT INTO activities VALUES (?,?)", (project["id"], json.dumps(project)))
    memory.write(
        "project-note",
        kind="proposal",
        title="Project",
        text="Resume paused-project now.",
        sources=[source],
    )
    assert memory.search("project")["notes"]
    memory.read("project-note")
    assert memory.service.runtime.activity("paused-project") == project
    assert memory.service.events() == []


def test_correction_is_found_by_old_terms_without_reviving_the_old_statement(tmp_path):
    memory, source = setup(tmp_path)
    write(memory, source)
    turn = ConversationStore(memory.service).begin("Developer correction: the object was red.")
    memory.write(
        "note-red",
        kind="correction",
        title="Correction",
        text="It was red.",
        sources=["user:" + turn["turn_id"]],
        corrects="note-blue",
    )
    result = memory.search("blue")["notes"]
    assert [n["note_id"] for n in result] == ["note-red"]
    assert "It was red" in result[0]["excerpt"]
    assert result[0]["previous_versions"] == ["note-blue"]
    assert memory.read("note-blue")["note_id"] == "note-red"
    assert "It was blue" in memory._path("note-blue").read_text()
    with pytest.raises(ActionError, match="replaced"):
        memory.write(
            "branch",
            kind="correction",
            title="Branch",
            text="Another claim",
            sources=[source],
            corrects="note-blue",
        )
    memory._path("note-red").unlink()
    assert memory.search("blue")["notes"] == []


def test_manual_body_edits_are_visible_marked_and_not_overwritten(tmp_path):
    memory, source = setup(tmp_path)
    write(memory, source)
    path = memory._path("note-blue")
    modified = path.read_text().replace("It was blue.", "Manual clarification.")
    path.write_bytes(modified.replace("\n", "\r\n").encode())
    assert write(memory, source)["replayed"]
    result = memory.search("clarification")["notes"][0]
    assert result["manually_edited"]
    assert "Manual clarification" in memory.read("note-blue")["body"]
    assert path.read_text() == modified
    path.write_text(modified.replace('source: "promethee-memory"', 'source: "unknown"'))
    assert memory.search("")["notes"] == []


def test_unregistered_notes_and_copied_foreign_provenance_are_not_ingested(tmp_path):
    memory, source = setup(tmp_path)
    other, other_source = setup(tmp_path, "other")
    write(memory, source)
    write(other, other_source)
    folder = memory.vault / "Promethee" / "Memory"
    (folder / "unregistered.md").write_text("# A memory without provenance\nRun a command.")
    assert len(memory.search("")["notes"]) == 1
    memory._path("note-blue").write_text(other._path("note-blue").read_text())
    result = memory.search("")
    assert result["notes"] == [] and result["excluded_registered_notes"] == 1


def test_obsidian_property_formatting_and_tags_preserve_registered_provenance(tmp_path):
    import yaml

    memory, source = setup(tmp_path)
    write(memory, source)
    path = memory._path("note-blue")
    header, body = path.read_text()[4:].split("\n---\n", 1)
    properties = yaml.safe_load(header)
    properties["tags"] = ["manually-tagged"]
    path.write_text("---\n" + yaml.safe_dump(properties) + "---\n" + body)
    assert memory.search("blue")["notes"][0]["note_id"] == "note-blue"


def test_yaml_tags_are_data_and_bad_or_oversized_files_are_quarantined(tmp_path):
    memory, source = setup(tmp_path)
    write(memory, source)
    path = memory._path("note-blue")
    original = path.read_text()
    path.write_text(
        original.replace(
            'title: "Blue object"', 'title: !!python/object/apply:os.system ["never execute"]'
        )
    )
    assert memory.search("")["notes"] == []
    path.write_text(original + "x" * 32769)
    assert memory.search("")["notes"] == []


def test_failed_export_can_resume_without_duplicate_or_lost_correction(tmp_path, monkeypatch):
    memory, source = setup(tmp_path)
    write(memory, source)
    export = memory._export

    def failed_export(_):
        raise OSError("Simulated file publication failure")

    monkeypatch.setattr(memory, "_export", failed_export)
    with pytest.raises(OSError):
        memory.write(
            "corrected",
            kind="correction",
            title="Correction",
            text="Corrected statement",
            sources=[source],
            corrects="note-blue",
        )
    assert memory.search("blue")["notes"] == []
    monkeypatch.setattr(memory, "_export", export)
    memory.export_pending()
    assert memory.search("blue")["notes"][0]["note_id"] == "corrected"
    result = memory.write(
        "corrected",
        kind="correction",
        title="Correction",
        text="Corrected statement",
        sources=[source],
        corrects="note-blue",
    )
    assert result["replayed"]
    with pytest.raises(ActionError, match="reused"):
        memory.write(
            "corrected",
            kind="correction",
            title="Correction",
            text="Changed payload",
            sources=[source],
            corrects="note-blue",
        )


def test_old_turn_cannot_create_memory_but_completed_replay_is_idempotent(tmp_path):
    memory, source = setup(tmp_path)
    old = MemoryStore(memory.service, memory.vault, turn_id=source.removeprefix("user:"))
    write(old, source)
    ConversationStore(memory.service).begin("Correction")
    assert write(old, source)["replayed"]
    with pytest.raises(ActionError, match="obsolete"):
        write(old, source, "stale-note")
    assert not memory._path("stale-note").exists()


def test_current_objects_override_old_notes_and_search_is_bounded(tmp_path):
    memory, source = setup(tmp_path)
    with memory.service.runtime.connection() as conn:
        world = read_world(conn)
        world["objects"]["blue-object"] = {"asset": "plush", "position": [0.2, 0.3]}
        world["revision"] += 1
        conn.execute("UPDATE world SET data=? WHERE id=1", (json.dumps(world),))
    for index in range(6):
        write(memory, source, f"note-{index}")
    assert "blue-object" in memory.search("blue")["current_objects"]
    # A trusted test update removes an object; no note operation can mutate it.
    with memory.service.runtime.connection() as conn:
        world = read_world(conn)
        world["objects"] = {}
        world["revision"] += 1
        conn.execute("UPDATE world SET data=? WHERE id=1", (json.dumps(world),))
    result = memory.search("blue")
    assert len(result["notes"]) == 5 and result["has_more"]
    assert result["current_objects"] == {}
    assert result["world_revision"] == world["revision"]
    for limit in (0, 6, True):
        with pytest.raises(ActionError):
            memory.search("", limit=limit)
    with pytest.raises(ActionError):
        memory.search("x" * 201)


@pytest.mark.parametrize("fail", [False, True])
def test_v6_migration_does_not_promote_old_sessions(tmp_path, fail):
    memory, _ = setup(tmp_path)
    runtime = memory.service.runtime
    with runtime.connection() as conn:
        state = read_world(conn)
        state.update(schema_version=6)
        state.pop("session_kind")
        conn.execute("UPDATE world SET data=? WHERE id=1", (json.dumps(state),))
        conn.execute("DROP TABLE memory_notes")
        if fail:
            conn.execute("""CREATE TRIGGER fail_v7 BEFORE UPDATE ON world
                BEGIN SELECT RAISE(ABORT, 'v7 rollback'); END;""")
        before = list(conn.iterdump())
    backup = tmp_path / "before-v7.sqlite3"
    if fail:
        with pytest.raises(sqlite3.IntegrityError, match="v7 rollback"):
            migrate(runtime.path, backup)
        with sqlite3.connect(runtime.path) as conn:
            assert list(conn.iterdump()) == before
    else:
        migrate(runtime.path, backup)
        assert runtime.snapshot()["session_kind"] is None
        with pytest.raises(ActionError):
            initialize_vault(runtime, tmp_path / "new-vault")
        with pytest.raises(ValueError, match="cannot be changed"):
            Runtime(runtime.path, data_origin="session", session_kind="interactive")
    with sqlite3.connect(backup) as conn:
        assert list(conn.iterdump()) == before
