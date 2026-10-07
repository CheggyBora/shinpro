"""
Калькулятор покраски дисков.

Покраску считают не как шиномонтаж: там цена из прайса по диаметру, а
здесь к базовой работе клиент выбирает дополнения, и сумма складывается
на ходу. Приёмщику это нужно в разговоре — человек спрашивает «а
сколько с проточкой», и ответ должен быть сразу, а не через калькулятор
в телефоне.

Экран устроен проще некуда: слева выбор, справа счёт. Любое нажатие
сразу пересчитывает итог — ни кнопки «посчитать», ни полей ввода.
Ошибиться негде, а значит, можно считать при клиенте.
"""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import styles
from services.paint_service import PaintService


class PaintTab:
    def __init__(self, parent, db):
        self.db = db
        self.service = PaintService(db)

        self.frame = ttk.Frame(parent, style='BG.TFrame')

        self.diameter = tk.IntVar(value=17)
        self.wheels = tk.IntVar(value=4)
        self.picked = {}          # id дополнения -> BooleanVar

        self._build()
        self.recalc()

    # ------------------------------------------------------------------
    # Экран
    # ------------------------------------------------------------------

    def _build(self):
        wrap = tk.Frame(self.frame, bg=styles.COLORS['bg'])
        wrap.pack(fill='both', expand=True, padx=20, pady=20)

        styles.create_label(wrap, "Покраска дисков",
                            'Heading.TLabel').pack(anchor='w', pady=(0, 2))
        ttk.Label(wrap, text="Выберите размер и дополнения — сумма посчитается сама.",
                  font=(styles.DEFAULT_FONT, 10),
                  foreground=styles.COLORS['text_secondary'],
                  background=styles.COLORS['bg']).pack(anchor='w', pady=(0, 14))

        body = tk.Frame(wrap, bg=styles.COLORS['bg'])
        body.pack(fill='both', expand=True)

        left = tk.Frame(body, bg=styles.COLORS['bg_card'])
        left.pack(side='left', fill='both', expand=True)

        right = tk.Frame(body, bg=styles.COLORS['bg_card'], width=360)
        right.pack(side='right', fill='y', padx=(16, 0))
        right.pack_propagate(False)

        self._build_choice(left)
        self._build_bill(right)

    def _build_choice(self, parent):
        inner = tk.Frame(parent, bg=styles.COLORS['bg_card'])
        inner.pack(fill='both', expand=True, padx=18, pady=18)

        # --- размер ---------------------------------------------------
        styles.create_label(inner, "Размер диска",
                            'CardHeading.TLabel').pack(anchor='w')

        sizes = tk.Frame(inner, bg=styles.COLORS['bg_card'])
        sizes.pack(fill='x', pady=(8, 16))

        for index, row in enumerate(self.service.sizes()):
            ttk.Radiobutton(sizes, text=f"R{row['diameter']}",
                            value=row['diameter'], variable=self.diameter,
                            command=self.recalc).grid(
                row=index // 6, column=index % 6, sticky='w', padx=(0, 16),
                pady=3)

        # --- сколько колёс --------------------------------------------
        styles.create_label(inner, "Сколько колёс",
                            'CardHeading.TLabel').pack(anchor='w')

        wheels = tk.Frame(inner, bg=styles.COLORS['bg_card'])
        wheels.pack(fill='x', pady=(8, 16))

        for count in (1, 2, 3, 4, 5):
            text = "4 (комплект)" if count == 4 else str(count)
            ttk.Radiobutton(wheels, text=text, value=count,
                            variable=self.wheels,
                            command=self.recalc).pack(side='left', padx=(0, 16))

        # --- дополнения -----------------------------------------------
        styles.create_label(inner, "Дополнения",
                            'CardHeading.TLabel').pack(anchor='w')

        self.options_box = tk.Frame(inner, bg=styles.COLORS['bg_card'])
        self.options_box.pack(fill='both', expand=True, pady=(8, 0))

        self._draw_options()

        styles.create_button(inner, "Изменить цены", self.open_prices,
                             'Secondary.TButton').pack(anchor='w', pady=(14, 0))

    def _draw_options(self):
        for child in self.options_box.winfo_children():
            child.destroy()

        self.picked = {}

        options = self.service.options()
        if not options:
            ttk.Label(self.options_box,
                      text="Дополнений пока нет — добавьте их в «Изменить цены».",
                      font=(styles.DEFAULT_FONT, 10),
                      foreground=styles.COLORS['text_secondary'],
                      background=styles.COLORS['bg_card']).pack(anchor='w')
            return

        for option in options:
            row = tk.Frame(self.options_box, bg=styles.COLORS['bg_card'])
            row.pack(fill='x', pady=2)

            flag = tk.BooleanVar(value=False)
            self.picked[option.id] = flag

            price = f"{int(option.price)} ₽"
            price += " за колесо" if option.per_wheel else " за заказ"

            ttk.Checkbutton(row, text=f"{option.name} — {price}",
                            variable=flag,
                            command=self.recalc).pack(anchor='w')

            if option.note:
                ttk.Label(row, text=option.note,
                          font=(styles.DEFAULT_FONT, 9),
                          foreground=styles.COLORS['text_secondary'],
                          background=styles.COLORS['bg_card'],
                          wraplength=420, justify='left').pack(
                    anchor='w', padx=(24, 0))

    def _build_bill(self, parent):
        inner = tk.Frame(parent, bg=styles.COLORS['bg_card'])
        inner.pack(fill='both', expand=True, padx=18, pady=18)

        styles.create_label(inner, "Счёт",
                            'CardHeading.TLabel').pack(anchor='w', pady=(0, 10))

        self.bill_box = tk.Frame(inner, bg=styles.COLORS['bg_card'])
        self.bill_box.pack(fill='both', expand=True)

        line = tk.Frame(inner, height=1, bg=styles.COLORS['border'])
        line.pack(fill='x', pady=10)

        total_row = tk.Frame(inner, bg=styles.COLORS['bg_card'])
        total_row.pack(fill='x')

        styles.create_label(total_row, "Итого",
                            'CardHeading.TLabel').pack(side='left')

        self.total_label = ttk.Label(
            total_row, text="0 ₽",
            font=(styles.DEFAULT_FONT, 20, 'bold'),
            foreground=styles.COLORS['primary'],
            background=styles.COLORS['bg_card'])
        self.total_label.pack(side='right')

        styles.create_button(inner, "Скопировать счёт", self.copy_bill,
                             'Secondary.TButton').pack(fill='x', pady=(14, 0))

    # ------------------------------------------------------------------
    # Счёт
    # ------------------------------------------------------------------

    def current_quote(self):
        chosen = [option_id for option_id, flag in self.picked.items()
                  if flag.get()]
        return self.service.quote(self.diameter.get(), self.wheels.get(),
                                  chosen)

    def recalc(self):
        quote = self.current_quote()

        for child in self.bill_box.winfo_children():
            child.destroy()

        for line in quote['lines']:
            row = tk.Frame(self.bill_box, bg=styles.COLORS['bg_card'])
            row.pack(fill='x', pady=3)

            title = line['name']
            if line['quantity'] > 1:
                title += f" × {line['quantity']}"

            ttk.Label(row, text=title, font=(styles.DEFAULT_FONT, 10),
                      foreground=styles.COLORS['text'],
                      background=styles.COLORS['bg_card'],
                      wraplength=220, justify='left').pack(side='left')

            ttk.Label(row, text=f"{int(line['total'])} ₽",
                      font=(styles.DEFAULT_FONT, 10, 'bold'),
                      foreground=styles.COLORS['text'],
                      background=styles.COLORS['bg_card']).pack(side='right')

        self.total_label.config(text=f"{int(quote['total'])} ₽")

    def bill_text(self):
        quote = self.current_quote()

        lines = ["Покраска дисков"]
        for line in quote['lines']:
            title = line['name']
            if line['quantity'] > 1:
                title += f" × {line['quantity']}"
            lines.append(f"{title} — {int(line['total'])} ₽")

        lines.append(f"Итого: {int(quote['total'])} ₽")
        return "\n".join(lines)

    def copy_bill(self):
        """Счёт в буфер — отправить клиенту в переписку."""
        try:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(self.bill_text())
            messagebox.showinfo("Счёт", "Счёт скопирован — можно вставить "
                                        "в переписку с клиентом")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось скопировать: {e}")

    # ------------------------------------------------------------------
    # Цены
    # ------------------------------------------------------------------

    def open_prices(self):
        dialog = tk.Toplevel(self.frame)
        dialog.title("Цены на покраску")
        dialog.configure(bg=styles.COLORS['bg_card'])
        dialog.geometry("760x560")
        dialog.transient(self.frame.winfo_toplevel())
        dialog.grab_set()

        content = ttk.Frame(dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)

        styles.create_label(content, "Базовая покраска по размерам",
                            'CardHeading.TLabel').pack(anchor='w')
        ttk.Label(content,
                  text="Цена за одно колесо. Двойной клик — изменить.",
                  font=(styles.DEFAULT_FONT, 9),
                  foreground=styles.COLORS['text_secondary'],
                  background=styles.COLORS['bg_card']).pack(anchor='w',
                                                            pady=(0, 8))

        base = ttk.Treeview(content, columns=('Размер', 'Цена'),
                            show='headings', height=6)
        base.heading('Размер', text='Размер')
        base.heading('Цена', text='Цена за колесо, руб.')
        base.column('Размер', width=120, anchor='center')
        base.column('Цена', width=200, anchor='center')
        base.pack(fill='x', pady=(0, 14))

        def load_base():
            base.delete(*base.get_children())
            for row in self.service.sizes():
                base.insert('', 'end',
                            values=(f"R{row['diameter']}",
                                    f"{int(row['price'])}"),
                            tags=(str(row['diameter']),))

        def edit_base(event):
            selection = base.selection()
            if not selection:
                return

            size = int(base.item(selection[0])['tags'][0])
            value = simpledialog.askfloat(
                "Базовая покраска", f"R{size}\n\nЦена за одно колесо, руб.:",
                initialvalue=self.service.base_price(size), minvalue=0,
                parent=dialog)
            if value is None:
                return

            self.service.set_base_price(size, value)
            load_base()
            self.recalc()

        base.bind('<Double-1>', edit_base)
        load_base()

        styles.create_label(content, "Дополнения",
                            'CardHeading.TLabel').pack(anchor='w')
        ttk.Label(content,
                  text="Двойной клик — изменить цену. Снятая галочка прячет "
                       "дополнение из калькулятора, не удаляя его.",
                  font=(styles.DEFAULT_FONT, 9),
                  foreground=styles.COLORS['text_secondary'],
                  background=styles.COLORS['bg_card'],
                  wraplength=700, justify='left').pack(anchor='w', pady=(0, 8))

        extras = ttk.Treeview(content,
                              columns=('Название', 'Цена', 'Как', 'Видно'),
                              show='headings', height=9)
        extras.heading('Название', text='Дополнение')
        extras.heading('Цена', text='Цена, руб.')
        extras.heading('Как', text='Считается')
        extras.heading('Видно', text='Показывать')
        extras.column('Название', width=330, anchor='w')
        extras.column('Цена', width=110, anchor='center')
        extras.column('Как', width=130, anchor='center')
        extras.column('Видно', width=110, anchor='center')
        extras.pack(fill='both', expand=True)

        def load_extras():
            extras.delete(*extras.get_children())
            for option in self.service.options(only_active=False):
                extras.insert('', 'end', values=(
                    option.name,
                    f"{int(option.price)}",
                    "за колесо" if option.per_wheel else "за заказ",
                    "да" if option.is_active else "нет",
                ), tags=(str(option.id),))

        def edit_extra(event):
            selection = extras.selection()
            if not selection:
                return

            option_id = int(extras.item(selection[0])['tags'][0])
            option = self.service.option(option_id)
            if option is None:
                return

            column = extras.identify_column(event.x)

            # Видно и способ расчёта — переключаются щелчком: значений
            # по два, спрашивать их окном незачем
            if column == '#4':
                self.service.save_option(option_id,
                                         is_active=not option.is_active)
            elif column == '#3':
                self.service.save_option(option_id,
                                         per_wheel=not option.per_wheel)
            else:
                value = simpledialog.askfloat(
                    "Цена дополнения", f"«{option.name}»\n\nЦена, руб.:",
                    initialvalue=float(option.price or 0), minvalue=0,
                    parent=dialog)
                if value is None:
                    return
                self.service.save_option(option_id, price=value)

            load_extras()
            self._draw_options()
            self.recalc()

        extras.bind('<Double-1>', edit_extra)
        load_extras()

        styles.create_button(content, "Закрыть", dialog.destroy,
                             'Secondary.TButton').pack(fill='x', pady=(14, 0))
