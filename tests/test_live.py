"""The one-command launcher, against a fake Graph API: settings, pre-flight checks, webhook."""

import time

import httpx
import pytest

from reach_agent.live import REQUIRED, SetupError, check_meta, find_tunnel_url, load_settings, point_webhook

SETTINGS = {"META_ACCESS_TOKEN": "EAA-token", "META_PHONE_NUMBER_ID": "PHONE", "META_APP_SECRET": "secret",
            "META_VERIFY_TOKEN": "verify", "META_APP_ID": "APP", "META_WABA_ID": "WABA"}


def write_env(tmp_path, text):
    path = tmp_path / "live.env"
    path.write_text(text, encoding="utf-8")
    return path


def test_settings_are_read_from_the_file_and_the_environment_wins(tmp_path):
    lines = [f'{key}="{value}"' for key, value in SETTINGS.items()]
    path = write_env(tmp_path, "# comment\n\n" + "\n".join(lines))
    assert load_settings(path, environ={}) == SETTINGS
    assert load_settings(path, environ={"META_ACCESS_TOKEN": " EAA-new "})["META_ACCESS_TOKEN"] == "EAA-new"


def test_missing_or_placeholder_settings_are_named(tmp_path):
    path = write_env(tmp_path, "META_ACCESS_TOKEN=EAA...\nMETA_APP_ID=APP\n")
    with pytest.raises(SetupError, match="META_ACCESS_TOKEN") as problem:
        load_settings(path, environ={})
    assert "META_APP_ID" not in str(problem.value) and "META_WABA_ID" in str(problem.value)


def fake_meta(*, secret_ok=True, token_valid=True, expires_at=0, phone_ok=True, subscribed=True,
              webhook_failures=0):
    calls = []
    failures = {"left": webhook_failures}

    def handler(request):
        path, method = request.url.path, request.method
        calls.append(f"{method} {path.split('/', 2)[2]}")
        if path.endswith("/APP") and method == "GET":
            return httpx.Response(200 if secret_ok else 400, json={"id": "APP"})
        if path.endswith("/debug_token"):
            return httpx.Response(200, json={"data": {"is_valid": token_valid, "expires_at": expires_at}})
        if path.endswith("/PHONE"):
            return httpx.Response(200 if phone_ok else 400, json={"display_phone_number": "+1 555-140-4683"})
        if path.endswith("/subscribed_apps"):
            apps = [{"whatsapp_business_api_data": {"id": "APP"}}] if subscribed else []
            return httpx.Response(200, json={"data": apps} if method == "GET" else {"success": True})
        if path.endswith("/subscriptions"):
            if failures["left"]:
                failures["left"] -= 1
                return httpx.Response(400, json={"error": {"message": "callback verification failed"}})
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404)

    return calls, httpx.Client(transport=httpx.MockTransport(handler))


def test_all_good_returns_the_number_to_message():
    _, http = fake_meta()
    assert check_meta(SETTINGS, http) == "+1 555-140-4683"


@pytest.mark.parametrize("problem, message", [
    ({"secret_ok": False}, "App secret"),
    ({"token_valid": False}, "expirou"),
    ({"phone_ok": False}, "PHONE_NUMBER_ID"),
])
def test_each_bad_setting_stops_with_a_clear_reason(problem, message):
    _, http = fake_meta(**problem)
    with pytest.raises(SetupError, match=message):
        check_meta(SETTINGS, http)


def test_time_left_on_the_token_is_shown(capsys):
    _, http = fake_meta(expires_at=int(time.time()) + 3 * 3600 + 120)
    check_meta(SETTINGS, http)
    assert "token válido por mais 3 h" in capsys.readouterr().out


def test_the_test_account_is_linked_to_the_app_when_it_is_not():
    calls, http = fake_meta(subscribed=False)
    check_meta(SETTINGS, http)
    assert "POST WABA/subscribed_apps" in calls
    calls, http = fake_meta(subscribed=True)
    check_meta(SETTINGS, http)
    assert "POST WABA/subscribed_apps" not in calls


def test_webhook_is_retried_while_the_new_tunnel_address_propagates():
    calls, http = fake_meta(webhook_failures=2)
    point_webhook(SETTINGS, "https://abc.trycloudflare.com/whatsapp", http, wait=0)
    assert calls.count("POST APP/subscriptions") == 3


def test_webhook_gives_up_with_metas_reason():
    _, http = fake_meta(webhook_failures=10)
    with pytest.raises(SetupError, match="callback verification failed"):
        point_webhook(SETTINGS, "https://abc.trycloudflare.com/whatsapp", http, attempts=3, wait=0)


def test_tunnel_address_is_found_in_cloudflareds_output():
    line = "2026-09-24T13:15:22Z INF |  https://basic-cope-theater-berkeley.trycloudflare.com  |"
    assert find_tunnel_url(line) == "https://basic-cope-theater-berkeley.trycloudflare.com"
    assert find_tunnel_url("INF Registered tunnel connection") is None


def test_required_settings_start_with_what_the_meta_transport_takes():
    assert REQUIRED[:4] == ("META_ACCESS_TOKEN", "META_PHONE_NUMBER_ID", "META_APP_SECRET", "META_VERIFY_TOKEN")
