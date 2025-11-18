from datetime import datetime, timedelta

def get_moscow_time():
    """
    Получить текущее время по Москве (UTC+3)
    """
    utc_now = datetime.utcnow()
    moscow_time = utc_now + timedelta(hours=3)
    return moscow_time
