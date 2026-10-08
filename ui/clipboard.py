"""
Вставка и копирование при русской раскладке.

Tkinter привязывает Ctrl+V к латинской букве V. Когда раскладка
русская, система сообщает ему про Ctrl+М — такой привязки нет, и
ничего не происходит. Человек жмёт, поле пустое, и выглядит это как
поломка программы.

Беда известная и неочевидная: в английской раскладке всё работает, и
разработчик её не видит. А приёмщик вставляет ключ обмена, номер
телефона, госномер из переписки — и упирается.

Лечим по коду клавиши, а не по букве. Код у клавиши один и тот же при
любой раскладке: V — 86, C — 67, X — 88, A — 65. Так вставка работает
и на русской, и на английской.

Заодно вешаем правую кнопку мыши: не все знают про Ctrl+V, а меню
видно глазами.
"""
import tkinter as tk

# Коды клавиш на Windows. Не зависят от раскладки — это физическая
# клавиша, а не нарисованная на ней буква
KEY_A = 65
KEY_C = 67
KEY_V = 86
KEY_X = 88


def _has_selection(widget):
    try:
        return bool(widget.selection_present())
    except Exception:
        try:
            return bool(widget.tag_ranges('sel'))
        except Exception:
            return False


def _delete_selection(widget):
    try:
        if widget.selection_present():
            widget.delete('sel.first', 'sel.last')
    except Exception:
        try:
            if widget.tag_ranges('sel'):
                widget.delete('sel.first', 'sel.last')
        except Exception:
            pass


def paste(widget):
    try:
        text = widget.clipboard_get()
    except tk.TclError:
        return 'break'          # в буфере пусто или не текст

    # Вставка поверх выделенного заменяет его — так ведут себя все
    # поля, и ждут от нас того же
    _delete_selection(widget)

    try:
        widget.insert('insert', text)
    except Exception:
        pass

    return 'break'


def copy(widget):
    if not _has_selection(widget):
        return 'break'

    try:
        widget.clipboard_clear()
        widget.clipboard_append(widget.selection_get())
    except Exception:
        pass

    return 'break'


def cut(widget):
    copy(widget)
    _delete_selection(widget)
    return 'break'


def select_all(widget):
    try:
        widget.select_range(0, 'end')
        widget.icursor('end')
    except Exception:
        try:
            widget.tag_add('sel', '1.0', 'end')
        except Exception:
            pass

    return 'break'


def _on_control_key(event):
    """Ctrl с буквой — разбираем по коду клавиши, а не по букве."""
    actions = {KEY_V: paste, KEY_C: copy, KEY_X: cut, KEY_A: select_all}
    action = actions.get(event.keycode)

    if action is None:
        return None

    return action(event.widget)


def _menu_for(widget):
    menu = tk.Menu(widget, tearoff=0)
    menu.add_command(label='Вырезать', command=lambda: cut(widget))
    menu.add_command(label='Копировать', command=lambda: copy(widget))
    menu.add_command(label='Вставить', command=lambda: paste(widget))
    menu.add_separator()
    menu.add_command(label='Выделить всё', command=lambda: select_all(widget))
    return menu


def _on_right_click(event):
    widget = event.widget
    try:
        widget.focus_set()
        menu = _menu_for(widget)
        menu.tk_popup(event.x_root, event.y_root)
    except Exception:
        pass
    finally:
        try:
            menu.grab_release()
        except Exception:
            pass

    return 'break'


def enable(root):
    """
    Включить вставку и копирование во всех полях окна.

    Вешаем на класс виджета, а не на каждое поле: полей в программе
    сотни, и заводить привязку в каждом месте — верный способ однажды
    забыть и получить одно поле, где вставка не работает.
    """
    for klass in ('Entry', 'TEntry', 'Text', 'TCombobox'):
        root.bind_class(klass, '<Control-KeyPress>', _on_control_key, add='+')
        root.bind_class(klass, '<Button-3>', _on_right_click, add='+')
