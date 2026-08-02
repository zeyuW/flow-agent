import logging
import urllib.error

from interfaces.channels.telegram import TelegramChannel


def test_telegram_api_failure_log_does_not_expose_bot_token(
    monkeypatch,
    caplog,
):
    token = "123456:very-secret-token"
    channel = TelegramChannel(token)

    def fail_request(*args, **kwargs):
        raise urllib.error.URLError("网络失败")

    monkeypatch.setattr("urllib.request.urlopen", fail_request)
    with caplog.at_level(logging.ERROR):
        channel._post_api(
            f"https://api.telegram.org/bot{token}/sendMessage",
            {"chat_id": 1, "text": "测试"},
        )

    assert token not in caplog.text
    assert "endpoint=sendMessage" in caplog.text
