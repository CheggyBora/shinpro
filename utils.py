from datetime import datetime, timedelta, timezone

def get_moscow_time():
    """
    Получить текущее время по Москве (UTC+3)
    Возвращает aware datetime с часовым поясом UTC+3
    """
    moscow_tz = timezone(timedelta(hours=3))
    moscow_time = datetime.now(moscow_tz)
    return moscow_time
