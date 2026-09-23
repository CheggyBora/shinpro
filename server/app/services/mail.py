"""
Отправка кода подтверждения на почту.

Пока ящик отправителя не настроен, работает режим «log»: код пишется
в журнал сервера, а письмо не уходит. Так приложение можно
разрабатывать и показывать, ничего не подключая — но в бою этот режим
означает, что войти не сможет никто, кроме того, у кого есть доступ
к журналу.
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import settings

log = logging.getLogger('tire_server')

TIMEOUT_SECONDS = 20


class MailError(Exception):
    pass


def send_code(email, code, purpose='login'):
    """Отправить код подтверждения. Ошибка отправки — это MailError."""
    shop = settings.SHOP_NAME

    if purpose == 'pin_reset':
        subject = f'{shop}: смена ПИН-кода'
        intro = 'Вы запросили смену ПИН-кода в приложении.'
    else:
        subject = f'{shop}: код для входа'
        intro = 'Вы входите в приложение.'

    text = (
        f"{intro}\n\n"
        f"Код подтверждения: {code}\n\n"
        f"Код действует {settings.CODE_TTL_MINUTES} мин. "
        f"Никому его не сообщайте.\n\n"
        f"Если это были не вы, просто не вводите код — ничего не произойдёт.\n"
        f"—\n{shop}"
    )

    provider = (settings.MAIL_PROVIDER or 'log').lower()
    if provider == 'log':
        # Ровно та строка, по которой код можно найти при разработке
        log.warning("Письмо не отправлено (почта не настроена). "
                    "Ящик %s, код %s", email, code)
        return True

    if provider == 'smtp':
        return _send_via_smtp(email, subject, text)

    raise MailError(f"Неизвестный способ отправки почты: {settings.MAIL_PROVIDER}")


def _send_via_smtp(email, subject, text):
    """
    Обычный SMTP — подходит и Яндексу, и Mail.ru, и своему серверу.

    Пароль нужен не от почтового ящика, а отдельный пароль приложения:
    у Яндекса и Mail.ru обычный пароль для внешних программ не работает.
    """
    if not settings.MAIL_HOST or not settings.MAIL_FROM:
        raise MailError('Почта не настроена: нет адреса сервера или отправителя')

    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = settings.MAIL_FROM
    message['To'] = email
    message.set_content(text)

    try:
        if settings.MAIL_USE_SSL:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(settings.MAIL_HOST, settings.MAIL_PORT,
                                  context=context,
                                  timeout=TIMEOUT_SECONDS) as server:
                _login_and_send(server, message)
        else:
            with smtplib.SMTP(settings.MAIL_HOST, settings.MAIL_PORT,
                              timeout=TIMEOUT_SECONDS) as server:
                server.starttls(context=ssl.create_default_context())
                _login_and_send(server, message)
    except smtplib.SMTPAuthenticationError:
        raise MailError('Почтовый сервер не принял логин или пароль. '
                        'Для Яндекса и Mail.ru нужен пароль приложения, '
                        'а не пароль от ящика')
    except (smtplib.SMTPException, OSError) as e:
        raise MailError(f'Не удалось отправить письмо: {e}')

    return True


def _login_and_send(server, message):
    if settings.MAIL_USER:
        server.login(settings.MAIL_USER, settings.MAIL_PASSWORD)
    server.send_message(message)
