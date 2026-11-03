"""Smoke tests for the Streamlit UI (headless, no API calls)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setattr("emporio.llm.load_dotenv", lambda *a, **k: False)
    return AppTest.from_file(APP, default_timeout=30).run()


def test_app_starts_with_welcome_message(app):
    assert not app.exception
    assert "Tom" in app.chat_message[0].markdown[0].value


def test_gemini_is_the_default_provider(app):
    assert app.sidebar.selectbox[0].value == "Gemini"
    assert "generativelanguage.googleapis.com" in app.sidebar.text_input[0].value


def test_switching_provider_fills_preset(app):
    app.sidebar.selectbox[0].set_value("Ollama (local)").run()
    assert app.sidebar.text_input[0].value == "http://localhost:11434/v1"


def test_missing_key_shows_warning_instead_of_calling_llm(app):
    app.chat_input[0].set_value("oi").run()
    assert not app.exception
    assert "API key" in app.warning[0].value
