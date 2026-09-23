"""Smoke tests of the terminal demo, driven with scripted keyboard input (offline extractor)."""

import pytest

from reach_agent.cli import main


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


@pytest.mark.parametrize("typed", [(), ("",)])
def test_demo_exits_cleanly_when_input_ends(monkeypatch, capsys, typed):
    run_demo(monkeypatch, capsys, *typed)
