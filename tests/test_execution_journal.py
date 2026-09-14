from promethee.journal import export_journal


def test_journal_distinguishes_accepted_failed_cancelled_and_completed(body, tmp_path):
    service, driver, _ = body
    vault = tmp_path / "vault"
    action = {"kind": "move", "args": {"position": [1, 0]}}
    service.submit("accepted", service.get_world()["revision"], action)
    assert export_journal(service.runtime, vault) == 0
    service.cancel("accepted")
    assert export_journal(service.runtime, vault) == 1
    cancelled = next(vault.rglob("*.md"))
    text = cancelled.read_text(encoding="utf-8")
    assert "execution_status: cancelled" in text
    assert "controller_mode: logical-test" in text
    assert "data_origin: fixture" in text
    cancelled.write_text("Annotation personnelle", encoding="utf-8")
    service.submit("finished", service.get_world()["revision"], action)
    driver.complete(driver.start())
    assert export_journal(service.runtime, vault) == 1
    assert cancelled.read_text(encoding="utf-8") == "Annotation personnelle"
    service.submit("failed", service.get_world()["revision"], action)
    driver.start()
    driver.handle.feedback("failed", 1, "failed", error="missing frame")
    assert export_journal(service.runtime, vault) == 1
    assert export_journal(service.runtime, vault) == 0
    notes = [path.read_text(encoding="utf-8") for path in vault.rglob("*.md")]
    assert sum("execution_status: completed" in note for note in notes) == 1
    assert sum("execution_status: failed" in note for note in notes) == 1


def test_interrupted_action_never_exports_a_completed_outcome(body, tmp_path):
    service, driver, clock = body
    service.submit(
        "lost", service.get_world()["revision"], {"kind": "move", "args": {"position": [1, 0]}}
    )
    driver.start()
    clock.advance(6)
    assert service.get("lost")["status"] == "interrupted"
    export_journal(service.runtime, tmp_path / "vault")
    note = next((tmp_path / "vault").rglob("*.md")).read_text(encoding="utf-8")
    assert "execution_status: interrupted" in note
    assert "execution_status: completed" not in note
