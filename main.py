from utils import make_output_safe

# ДО всего остального: программа не должна падать из-за того,
# что консоль не умеет печатать символ «✓» в своей кодировке
make_output_safe()

import tkinter as tk
from tkinter import messagebox
from ui import MainWindow
from config import init_db, get_db_file_path
from init_data import initialize_data
from services.backup_service import create_backup
import os
from logger import log, cleanup_old_logs


def set_app_icon(root):
    """
    Логотип в заголовке окна, на панели задач и у всех диалогов, а не
    перо Tk. Нет файла или не Windows — остаётся как было.
    """
    import sys

    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, 'assets', 'app.ico')
    if not os.path.exists(path):
        return
    try:
        # Без своего AppUserModelID Windows при запуске из Python
        # показывает на панели задач значок интерпретатора
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('rif.tireshop')
    except Exception:
        pass
    try:
        root.iconbitmap(default=path)
    except Exception as e:
        log.warning(f"Значок окна не поставился: {e}")


if __name__ == "__main__":
    # Первая строка в журнале — метка запуска: по ней видно границу
    # между сеансами работы, когда разбираем вчерашнюю проблему
    log.info("=" * 60)
    log.info("Запуск программы")
    cleanup_old_logs()

    # Сохраняем переменные окружения X-сервера для открытия PDF (только для Linux/Replit)
    import platform
    if platform.system() != 'Windows':
        display = os.environ.get('DISPLAY', '')
        xauthority = os.environ.get('XAUTHORITY', '')
        log.debug(f"X Server: DISPLAY={display}, XAUTHORITY={xauthority}")

        # Сохраняем в файл для использования в subprocess
        try:
            with open('/tmp/x_display.env', 'w') as f:
                f.write(f"DISPLAY={display}\n")
                f.write(f"XAUTHORITY={xauthority}\n")
        except:
            pass  # Не критично, если не удалось

    # Резервная копия базы ДО инициализации: если что-то пойдёт не так
    # при обновлении программы, будет к чему вернуться
    try:
        db_file = get_db_file_path()
        if db_file:
            backup_path = create_backup(db_file)
            if backup_path:
                log.info(f"Резервная копия базы: {backup_path}")
    except Exception as e:
        # Не смогли сделать копию — это плохо, но работать не мешает
        log.error(f"Не удалось создать резервную копию: {e}")

    try:
        init_db()
        initialize_data()
    except Exception as e:
        log.error(f"Ошибка инициализации БД: {e}")

    root = tk.Tk()
    set_app_icon(root)
    app = MainWindow(root)
    try:
        root.mainloop()
    except Exception:
        # Падение с окном — самое неприятное для мастера: экран просто
        # исчезает. Хотя бы след в журнале должен остаться
        log.exception("Программа завершилась с ошибкой")
        raise
    log.info("Программа закрыта")
