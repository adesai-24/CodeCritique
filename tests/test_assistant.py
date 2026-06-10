"""Unit tests for the natural-language assistant (ask / do)."""

from unittest.mock import MagicMock

from critique import assistant


# ---------------------------------------------------------------------------
# Manifest / ask
# ---------------------------------------------------------------------------

def test_build_manifest_lists_real_commands():
    manifest = assistant.build_manifest()
    for command in ("check", "fix", "format", "ask", "do", "install-hooks"):
        assert command in manifest
    assert "--install-completion" in manifest


def test_answer_question_grounds_llm_in_manifest():
    llm = MagicMock()
    llm.complete.return_value = "Use `codecritique fix`."

    answer = assistant.answer_question("how do I fix lint?", llm)

    assert answer == "Use `codecritique fix`."
    system, user = llm.complete.call_args[0]
    assert "manifest" in user.lower()
    assert "codecritique fix" in user  # manifest content included
    assert "how do I fix lint?" in user


# ---------------------------------------------------------------------------
# Plan validation
# ---------------------------------------------------------------------------

def test_validate_plan_accepts_known_actions():
    raw = {
        "reply": "ok",
        "plan": [
            {"action": "fix", "args": {"unsafe": True}},
            {"action": "check", "args": {"incremental": False, "ai": False}},
        ],
    }
    steps, errors = assistant.validate_plan(raw)

    assert errors == []
    assert [s["action"] for s in steps] == ["fix", "check"]
    assert steps[0]["args"] == {"unsafe": True}
    assert steps[1]["args"] == {"incremental": False, "ai": False}


def test_validate_plan_rejects_unknown_action():
    raw = {"plan": [{"action": "rm_rf", "args": {}}]}
    steps, errors = assistant.validate_plan(raw)

    assert steps == []
    assert any("rm_rf" in e for e in errors)


def test_validate_plan_drops_unknown_and_mistyped_args():
    raw = {
        "plan": [
            {"action": "fix", "args": {"unsafe": "yes", "shell": "rm -rf /"}},
        ]
    }
    steps, errors = assistant.validate_plan(raw)

    assert steps == [{"action": "fix", "args": {}}]
    assert any("shell" in e for e in errors)
    assert any("unsafe" in e for e in errors)


def test_validate_plan_coerces_single_file_string_to_list():
    raw = {"plan": [{"action": "check", "args": {"files": "a.py"}}]}
    steps, errors = assistant.validate_plan(raw)

    assert errors == []
    assert steps[0]["args"]["files"] == ["a.py"]


def test_validate_plan_handles_malformed_response():
    assert assistant.validate_plan(None) == ([], [])
    assert assistant.validate_plan({"plan": "not a list"}) == (
        [], ["Model returned a malformed plan."]
    )


# ---------------------------------------------------------------------------
# Plan execution
# ---------------------------------------------------------------------------

def test_run_plan_executes_steps_in_order(monkeypatch):
    calls = []

    def make_handler(name, result=True):
        def handler(**kwargs):
            calls.append((name, kwargs))
            return result
        return handler

    monkeypatch.setitem(assistant.ACTIONS, "fix", (make_handler("fix"), "d", {"unsafe": ""}))
    monkeypatch.setitem(assistant.ACTIONS, "check", (make_handler("check"), "d", {}))

    ok = assistant.run_plan([
        {"action": "fix", "args": {"unsafe": False}},
        {"action": "check", "args": {}},
    ])

    assert ok is True
    assert calls == [("fix", {"unsafe": False}), ("check", {})]


def test_run_plan_stops_on_first_failure(monkeypatch):
    calls = []

    def failing(**kwargs):
        calls.append("check")
        return False

    def never(**kwargs):
        calls.append("fix")
        return True

    monkeypatch.setitem(assistant.ACTIONS, "check", (failing, "d", {}))
    monkeypatch.setitem(assistant.ACTIONS, "fix", (never, "d", {}))

    ok = assistant.run_plan([
        {"action": "check", "args": {}},
        {"action": "fix", "args": {}},
    ])

    assert ok is False
    assert calls == ["check"]


def test_run_plan_treats_exception_as_failure(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("nope")

    monkeypatch.setitem(assistant.ACTIONS, "check", (boom, "d", {}))

    assert assistant.run_plan([{"action": "check", "args": {}}]) is False


# ---------------------------------------------------------------------------
# Planning round-trip with a mocked model
# ---------------------------------------------------------------------------

def test_plan_actions_passes_action_spec_and_returns_dict():
    llm = MagicMock()
    llm.complete_json.return_value = {"reply": "ok", "plan": []}

    result = assistant.plan_actions("fix everything", llm)

    assert result == {"reply": "ok", "plan": []}
    kwargs = llm.complete_json.call_args.kwargs
    assert "fix everything" in kwargs["user"]
    for action in assistant.ACTIONS:
        assert action in kwargs["system"]


def test_plan_actions_normalizes_non_dict_response():
    llm = MagicMock()
    llm.complete_json.return_value = ["unexpected"]

    assert assistant.plan_actions("x", llm) == {"reply": "", "plan": []}


# ---------------------------------------------------------------------------
# set_config action
# ---------------------------------------------------------------------------

def test_validate_plan_accepts_set_config_string_args():
    raw = {
        "plan": [
            {"action": "set_config", "args": {"setting": "language", "value": "cpp"}},
            {"action": "set_config", "args": {"setting": "temperature", "value": 0.3}},
        ]
    }
    steps, errors = assistant.validate_plan(raw)

    assert errors == []
    assert steps[0]["args"] == {"setting": "language", "value": "cpp"}
    assert steps[1]["args"] == {"setting": "temperature", "value": "0.3"}


def test_set_config_refuses_api_keys():
    assert assistant._do_set_config("api_key", "secret") is False
    assert assistant._do_set_config("gemini-key", "secret") is False


def test_set_config_rejects_unknown_setting():
    assert assistant._do_set_config("favorite_color", "blue") is False


def test_set_config_rejects_invalid_choice():
    assert assistant._do_set_config("language", "java") is False
    assert assistant._do_set_config("suggestion_mode", "yolo") is False


def test_set_config_persists_valid_setting(tmp_path, monkeypatch):
    from critique import config

    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")

    assert assistant._do_set_config("language", "cpp") is True
    assert config.load_config().language == "cpp"

    assert assistant._do_set_config("suggestion_mode", "strict") is True
    assert config.load_config().suggestion_mode == "strict"

    assert assistant._do_set_config("adaptive_style", "on") is True
    assert config.load_config().adaptive_style is True


def test_prompt_spec_lists_configurable_settings():
    spec = assistant._actions_for_prompt()
    assert "set_config" in spec
    for setting in ("language", "suggestion_mode", "provider"):
        assert setting in spec
