"""
Вставка и копирование при русской раскладке.

Tkinter привязывает Ctrl+V к латинской букве V. При русской раскладке
система сообщает ему Ctrl+М, привязки нет, и ничего не происходит.
Человек жмёт — поле пустое. Выглядит как поломка программы, а в
английской раскладке всё работает, поэтому разработчик этого не видит.

Приёмщик вставляет в поля постоянно: ключ обмена, телефон клиента,
госномер из переписки. Поэтому проверяем по коду клавиши — он один и
тот же при любой раскладке.
"""
import sys
import tkinter as tk

import _setup
from _setup import use_temp_db, check, finish

use_temp_db('clipboard')

_setup.silence_dialogs()

from ui.clipboard import enable, KEY_A, KEY_C, KEY_V, KEY_X

# Окно нужно показать: Tkinter не доставляет нажатия в скрытое окно,
# и проверка молча ничего не проверяла бы
root = tk.Tk()
root.geometry('260x80+0+0')
enable(root)

entry = tk.Entry(root)
entry.pack()
entry.focus_force()
root.update()

KEY = 'Control-KeyPress'


def press(widget, keycode):
    """
    Нажатие с Ctrl, заданное кодом клавиши.

    Именно так обработчик и смотрит на событие: по коду, а не по букве.
    Код один и тот же при любой раскладке — в этом вся суть починки.

    Подделать кириллический keysym через event_generate нельзя, Tk его
    не знает. Но это и не нужно: раз обработчик keysym не читает,
    проверять надо то, что он читает.
    """
    # when='now' — доставить сразу, а не положить в очередь: иначе
    # проверка идёт дальше раньше, чем событие дошло
    widget.event_generate(f'<{KEY}>', keycode=keycode, when='now')
    root.update()


print('=== Буфер готов ===')
root.clipboard_clear()
root.clipboard_append('EqR4ekxRJD2qBoS6d3lvX')
check('в буфере строка', root.clipboard_get() == 'EqR4ekxRJD2qBoS6d3lvX')

print()
print('=== Нажатие по коду клавиши, как при русской раскладке ===')
entry.delete(0, 'end')
press(entry, KEY_V)
check('вставилось', entry.get() == 'EqR4ekxRJD2qBoS6d3lvX', repr(entry.get()))

print()
print('=== Повторное нажатие работает так же ===')
entry.delete(0, 'end')
press(entry, KEY_V)
check('вставилось', entry.get() == 'EqR4ekxRJD2qBoS6d3lvX', repr(entry.get()))

print()
print('=== Копирование при русской раскладке ===')
entry.delete(0, 'end')
entry.insert(0, 'А123ВВ777')
entry.select_range(0, 'end')
root.clipboard_clear()
root.clipboard_append('мусор')
press(entry, KEY_C)
check('в буфере номер', root.clipboard_get() == 'А123ВВ777',
      repr(root.clipboard_get()))

print()
print('=== Вырезание убирает из поля ===')
entry.delete(0, 'end')
entry.insert(0, 'В456СС178')
entry.select_range(0, 'end')
press(entry, KEY_X)
check('поле опустело', entry.get() == '', repr(entry.get()))
check('в буфере вырезанное', root.clipboard_get() == 'В456СС178',
      repr(root.clipboard_get()))

print()
print('=== Выделить всё ===')
entry.delete(0, 'end')
entry.insert(0, 'Шиномонтаж «РИФ»')
entry.selection_clear()
press(entry, KEY_A)
check('выделено целиком', entry.selection_present()
      and entry.selection_get() == 'Шиномонтаж «РИФ»',
      repr(entry.selection_get() if entry.selection_present() else None))

print()
print('=== Вставка заменяет выделенное, а не дописывает ===')
root.clipboard_clear()
root.clipboard_append('новое')
entry.delete(0, 'end')
entry.insert(0, 'старое')
entry.select_range(0, 'end')
press(entry, KEY_V)
check('было заменено', entry.get() == 'новое', repr(entry.get()))

print()
print('=== Ctrl с другой буквой нам не мешает ===')
entry.delete(0, 'end')
entry.insert(0, 'текст')
press(entry, 90)     # Ctrl+Z
check('поле не тронуто', entry.get() == 'текст', repr(entry.get()))

root.destroy()
finish()
