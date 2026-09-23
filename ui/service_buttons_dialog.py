"""
Порядок кнопок услуг в наряде.

Сами кнопки берутся из прайс-листа — здесь настраивается только
раскладка: что в какой колонке и на каком месте. Услуга, которую
никуда не поставили, всё равно получит кнопку: программа положит её
в самую короткую колонку, чтобы новая услуга не потерялась.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from services import OrderService
from services.service_layout import build_columns, save_layout, COLUMN_COUNT
import styles


def open_service_buttons(parent, db):
    return ServiceButtonsDialog(parent, db).dialog


class ServiceButtonsDialog:
    def __init__(self, parent, db):
        self.db = db

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Порядок кнопок услуг")
        self.dialog.geometry("980x620")
        self.dialog.configure(bg=styles.COLORS['bg'])
        self.dialog.transient(parent.winfo_toplevel())
        self.dialog.grab_set()
        styles.center_window(self.dialog, parent.winfo_toplevel())

        content = ttk.Frame(self.dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)

        styles.create_label(content, "Порядок кнопок услуг",
                            'CardHeading.TLabel').pack(anchor='w')
        ttk.Label(content,
                  text="Выберите услугу и переставьте её стрелками или "
                       "перенесите в другую колонку. Услуги из прайс-листа, "
                       "которых нет в раскладке, добавятся в конец сами.",
                  font=(styles.DEFAULT_FONT, 9),
                  background=styles.COLORS['bg_card'],
                  foreground=styles.COLORS['text_secondary'],
                  wraplength=900, justify='left').pack(anchor='w', pady=(4, 14))

        columns_row = ttk.Frame(content, style='White.TFrame')
        columns_row.pack(fill='both', expand=True)

        names = [s.name for s in OrderService(db).get_all_services()]
        layout = build_columns(db, list(dict.fromkeys(names)))

        self.lists = []
        for index in range(COLUMN_COUNT):
            column = ttk.Frame(columns_row, style='White.TFrame')
            column.pack(side='left', fill='both', expand=True,
                        padx=(0, 10 if index < COLUMN_COUNT - 1 else 0))

            styles.create_label(column, f"Колонка {index + 1}",
                                'Card.TLabel').pack(anchor='w', pady=(0, 4))

            listbox = tk.Listbox(column, font=styles.FONTS['normal'],
                                 exportselection=False, activestyle='none',
                                 highlightthickness=1,
                                 highlightbackground=styles.COLORS['border'],
                                 selectbackground=styles.COLORS['primary'],
                                 selectforeground='white')
            listbox.pack(fill='both', expand=True)
            for name in layout[index]:
                listbox.insert('end', name)

            # Выделение живёт в одной колонке: иначе непонятно,
            # какую именно услугу двигают кнопки
            listbox.bind('<<ListboxSelect>>',
                         lambda e, i=index: self._clear_other_selections(i))
            self.lists.append(listbox)

        move_row = ttk.Frame(content, style='White.TFrame')
        move_row.pack(fill='x', pady=(14, 0))

        styles.create_button(move_row, "◀ Влево",
                             lambda: self.move_between(-1),
                             'Secondary.TButton').pack(side='left', padx=(0, 6))
        styles.create_button(move_row, "Вправо ▶",
                             lambda: self.move_between(1),
                             'Secondary.TButton').pack(side='left', padx=(0, 18))
        styles.create_button(move_row, "▲ Выше",
                             lambda: self.move_inside(-1),
                             'Secondary.TButton').pack(side='left', padx=(0, 6))
        styles.create_button(move_row, "▼ Ниже",
                             lambda: self.move_inside(1),
                             'Secondary.TButton').pack(side='left', padx=(0, 18))
        styles.create_button(move_row, "Вернуть порядок по умолчанию",
                             self.reset, 'Secondary.TButton').pack(side='left')

        buttons = ttk.Frame(content, style='White.TFrame')
        buttons.pack(fill='x', pady=(14, 0))
        styles.create_button(buttons, "Сохранить", self.save,
                             'Primary.TButton').pack(side='left', fill='x',
                                                     expand=True, padx=(0, 6))
        styles.create_button(buttons, "Закрыть", self.dialog.destroy,
                             'Secondary.TButton').pack(side='left', fill='x',
                                                       expand=True, padx=(6, 0))

    # ------------------------------------------------------------------

    def _clear_other_selections(self, keep):
        for index, listbox in enumerate(self.lists):
            if index != keep:
                listbox.selection_clear(0, 'end')

    def _selection(self):
        """(номер колонки, номер строки) или None, если ничего не выбрано."""
        for index, listbox in enumerate(self.lists):
            chosen = listbox.curselection()
            if chosen:
                return index, chosen[0]
        messagebox.showinfo("Кнопки услуг", "Сначала выберите услугу",
                            parent=self.dialog)
        return None

    def move_inside(self, step):
        found = self._selection()
        if not found:
            return
        column, row = found
        listbox = self.lists[column]
        target = row + step
        if target < 0 or target >= listbox.size():
            return

        name = listbox.get(row)
        listbox.delete(row)
        listbox.insert(target, name)
        listbox.selection_set(target)
        listbox.see(target)

    def move_between(self, step):
        found = self._selection()
        if not found:
            return
        column, row = found
        target_column = column + step
        if target_column < 0 or target_column >= COLUMN_COUNT:
            return

        name = self.lists[column].get(row)
        self.lists[column].delete(row)
        self.lists[target_column].insert('end', name)
        self.lists[target_column].selection_clear(0, 'end')
        self.lists[target_column].selection_set('end')
        self.lists[target_column].see('end')

    def reset(self):
        if not messagebox.askyesno(
                "Кнопки услуг",
                "Вернуть порядок по умолчанию? Ваша раскладка будет забыта.",
                parent=self.dialog):
            return
        from services.service_layout import reset_layout, DEFAULT_LAYOUT

        reset_layout(self.db)
        names = [s.name for s in OrderService(self.db).get_all_services()]
        layout = build_columns(self.db, list(dict.fromkeys(names)))
        for index, listbox in enumerate(self.lists):
            listbox.delete(0, 'end')
            for name in layout[index]:
                listbox.insert('end', name)

    def save(self):
        columns = [list(listbox.get(0, 'end')) for listbox in self.lists]
        try:
            save_layout(self.db, columns)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось сохранить порядок:\n{e}",
                                 parent=self.dialog)
            return

        messagebox.showinfo("Готово",
                            "Порядок сохранён. В нарядах он появится при "
                            "следующем переходе в раздел.",
                            parent=self.dialog)
        self.dialog.destroy()
