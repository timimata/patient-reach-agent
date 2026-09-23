"""Smoke tests of the terminal demo, driven with scripted keyboard input (offline extractor)."""

from datetime import date, time

import pytest

from reach_agent.cli import describe, main
from reach_agent.models import TimePreference


def run_demo(monkeypatch, capsys, *typed):
    keys = iter(typed)

    def fake_input(prompt=""):
        try:
            return next(keys)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", fake_input)
    main([])
    return capsys.readouterr().out


def test_demo_books_an_appointment(monkeypatch, capsys):
    out = run_demo(monkeypatch, capsys,
                   "",                                      # default enquiry
                   "n",                                     # first call not answered
                   "Estou a trabalhar, podem ligar depois das 18h?",
                   "s",                                     # callback answered
                   "a primeira")
    assert "[seg 21/09 18:00] [chamada agendada]" in out
    assert "Resultado: consulta marcada para [ter 22/09 18:30]" in out


def test_demo_prints_the_handoff_record(monkeypatch, capsys):
    out = run_demo(monkeypatch, capsys, "", "n", "Tenho dores fortes, o que posso tomar?")
    assert "passado a um humano (motivo: clinical_question)" in out
    assert '"trigger": "Tenho dores fortes, o que posso tomar?"' in out


@pytest.mark.parametrize(
    "preference, text",
    [
        (TimePreference(), "nenhuma"),
        (TimePreference(earliest=time(18)), "depois das 18:00"),
        (TimePreference(latest=time(11)), "antes das 11:00"),
        (TimePreference(earliest=time(17), latest=time(17)), "às 17:00"),
        (TimePreference(date(2026, 9, 22), time(9), time(13)), "ter 22/09, entre as 09:00 e as 13:00"),
        (TimePreference(day=date(2026, 9, 25)), "sex 25/09"),
    ],
)
def test_preferences_are_described_for_people(preference, text):
    assert describe(preference) == text


def test_state_command_is_readable(monkeypatch, capsys):
    out = run_demo(monkeypatch, capsys, "", "n", "Podem ligar depois das 18h?", "n", "/estado")
    assert "preferência lembrada: depois das 18:00" in out
    assert "TimePreference(" not in out


@pytest.mark.parametrize("typed", [(), ("",)])
def test_demo_exits_cleanly_when_input_ends(monkeypatch, capsys, typed):
    run_demo(monkeypatch, capsys, *typed)
