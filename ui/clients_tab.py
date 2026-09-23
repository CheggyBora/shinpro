"""
Вкладка «Клиенты».

Две подвкладки:
  - Клиенты — поиск по имени, телефону или номеру автомобиля;
  - История нарядов — прежняя вкладка целиком, вместе с удалением наряда
    и откатом начислений зарплаты.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from services import ClientService
from ui.client_card import open_client_card
from ui.history_tab import HistoryTab
from utils import format_phone
import styles


class ClientsTab:
    def __init__(self, parent, db):
        self.db = db
        self.client_service = ClientService(db)
        self.frame = ttk.Frame(parent, style='BG.TFrame')

        self.nav = styles.NavBar(self.frame, compact=True)
        self.nav.pack(fill='x')

        self.content = tk.Frame(self.frame, bg=styles.COLORS['bg'])
        self.content.pack(fill='both', expand=True)

        # Подраздел поиска клиентов
        self.search_frame = ttk.Frame(self.content, style='BG.TFrame')
        self._build_search()

        # История — прежняя вкладка как есть, чтобы не потерять
        # удаление нарядов и постраничный просмотр
        self.history_tab = HistoryTab(self.content, db)

        self.nav.add('Клиенты', self.search_frame)
        self.nav.add('История нарядов', self.history_tab.frame)

    # ------------------------------------------------------------------

    def _build_search(self):
        card = styles.create_card_frame(self.search_frame)
        card.pack(fill='x', padx=15, pady=(15, 10))

        inner = ttk.Frame(card, style='White.TFrame')
        inner.pack(fill='both', expand=True, padx=20, pady=20)

        styles.create_label(inner, "Поиск клиента",
                            'CardHeading.TLabel').pack(anchor='w', pady=(0, 5))
        ttk.Label(inner,
                  text="Можно искать по имени, номеру телефона (хватит последних цифр) "
                       "или по госномеру любого автомобиля клиента.",
                  font=(styles.DEFAULT_FONT, 9), foreground='#64748b',
                  wraplength=900, justify='left').pack(anchor='w', pady=(0, 12))

        row = ttk.Frame(inner, style='White.TFrame')
        row.pack(fill='x')

        styles.create_label(row, "Клиент или номер авто:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.query_entry = styles.create_entry(row, width=30)
        self.query_entry.pack(side='left', padx=(0, 10))
        self.query_entry.bind('<Return>', lambda e: self.search())

        styles.create_button(row, "Найти", self.search, 'Primary.TButton').pack(side='left', padx=(0, 5))
        styles.create_button(row, "Показать всех", self.show_all, 'Secondary.TButton').pack(side='left')

        # Результаты
        results_card = styles.create_card_frame(self.search_frame)
        results_card.pack(fill='both', expand=True, padx=15, pady=(0, 15))

        results_inner = ttk.Frame(results_card, style='White.TFrame')
        results_inner.pack(fill='both', expand=True, padx=20, pady=20)

        header = ttk.Frame(results_inner, style='White.TFrame')
        header.pack(fill='x', pady=(0, 10))
        styles.create_label(header, "Найденные клиенты", 'CardHeading.TLabel').pack(side='left')
        styles.create_button(header, "Открыть карточку", self.open_selected,
                             'Primary.TButton').pack(side='right')

        tree_frame = ttk.Frame(results_inner, style='White.TFrame')
        tree_frame.pack(fill='both', expand=True)

        self.tree = ttk.Treeview(
            tree_frame, columns=('Имя', 'Телефон', 'Машины', 'Визитов', 'Сумма'),
            show='headings')
        for column, title, width in (('Имя', 'Имя', 200), ('Телефон', 'Телефон', 160),
                                     ('Машины', 'Автомобили', 320),
                                     ('Визитов', 'Визитов', 90), ('Сумма', 'На сумму', 130)):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor='w')
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.bind('<Double-1>', lambda e: self.open_selected())

        scroll = ttk.Scrollbar(tree_frame, orient='vertical', command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.config(yscrollcommand=scroll.set)

        self.status_label = ttk.Label(results_inner, text="", font=(styles.DEFAULT_FONT, 9),
                                      foreground='#64748b')
        self.status_label.pack(anchor='w', pady=(10, 0))

        ttk.Label(results_inner, text="Двойной клик по клиенту — открыть карточку",
                  font=(styles.DEFAULT_FONT, 9), foreground='#64748b').pack(anchor='w')

        self.show_all()

    # ------------------------------------------------------------------

    def _fill(self, clients, empty_message):
        for row in self.tree.get_children():
            self.tree.delete(row)

        for client in clients:
            summary = self.client_service.get_client_summary(client.id)
            plates = ', '.join(car.license_plate for car in summary['cars'])
            self.tree.insert('', 'end', values=(
                client.name or 'без имени',
                format_phone(client.phone) if client.phone else '—',
                plates or '—',
                summary['visits'],
                f"{summary['total_spent']:.0f} руб.",
            ), tags=(str(client.id),))

        if clients:
            self.status_label.config(text=f"Найдено: {len(clients)}", foreground='#059669')
        else:
            self.status_label.config(text=empty_message, foreground='#dc2626')

    def search(self):
        query = self.query_entry.get().strip()
        if not query:
            self.show_all()
            return

        try:
            found = self.client_service.search(query, limit=200)
            self._fill(found, f"По запросу «{query}» никого не нашлось")
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось выполнить поиск:\n{e}")

    def show_all(self):
        from models import Client

        self.query_entry.delete(0, tk.END)
        try:
            clients = self.db.query(Client).order_by(Client.name).limit(500).all()
            self._fill(clients, "Клиентов пока нет")
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось загрузить клиентов:\n{e}")

    def open_selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Выбор", "Выберите клиента в списке")
            return

        client_id = int(self.tree.item(selection[0])['tags'][0])
        try:
            card = open_client_card(self.frame, self.db, client_id)
            # После закрытия карточки список мог измениться —
            # клиенту могли добавить машину или поправить телефон
            self.frame.wait_window(card)
            self.search() if self.query_entry.get().strip() else self.show_all()
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось открыть карточку: {e}")
