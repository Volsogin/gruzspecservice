"""Send one test e-mail with the current SMTP_* settings: `make test-email TO=you@example.com`.

Without SMTP_HOST the letter is written to MAIL_DUMP_DIR as an .eml file (dev mode) — the script says so.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.container import _email_notifier
from app.core.config import get_settings
from app.integrations.notifiers.base import OutgoingMessage, SendError


async def main(to: str) -> int:
    settings = get_settings()
    notifier = _email_notifier(settings)
    if not settings.smtp_host:
        print(f"SMTP_HOST не задан — письмо будет сохранено файлом в {settings.mail_dump_dir}")
    else:
        mode = "SSL" if settings.smtp_ssl else ("STARTTLS" if settings.smtp_starttls else "без шифрования")
        print(f"SMTP: {settings.smtp_host}:{settings.smtp_port} ({mode}), от: {settings.smtp_from}")
    message = OutgoingMessage(
        channel="email",
        recipient=to,
        subject="ГРУЗСПЕЦСЕРВИС: проверка почты",
        text="Это тестовое письмо. Если вы его читаете — SMTP настроен правильно.",
        html="<p>Это тестовое письмо. Если вы его читаете — <b>SMTP настроен правильно</b>.</p>",
    )
    try:
        result = await notifier.send(message)
    except SendError as exc:
        print(f"Не отправлено: {exc}. Проверьте SMTP_HOST/PORT/USER/PASSWORD и режим SSL/STARTTLS.")
        return 1
    print(f"Готово: {result.external_id}. Проверьте входящие и папку «Спам».")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("to", help="адрес получателя")
    sys.exit(asyncio.run(main(parser.parse_args().to)))
