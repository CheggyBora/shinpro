import os
from datetime import datetime, timedelta, timezone

def get_moscow_time():
    """
    Получить текущее время:
    - На Replit: московское время (UTC+3)
    - Локально: системное время компьютера
    Возвращает aware datetime с часовым поясом
    """
    # Проверяем, запущена ли программа на Replit
    is_replit = os.getenv('REPL_ID') is not None or os.getenv('REPLIT_DB_URL') is not None
    
    if is_replit:
        # На Replit используем фиксированное московское время UTC+3
        moscow_tz = timezone(timedelta(hours=3))
        return datetime.now(moscow_tz)
    else:
        # Локально используем системное время компьютера
        return datetime.now().astimezone()
