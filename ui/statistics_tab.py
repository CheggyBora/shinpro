import tkinter as tk
from tkinter import ttk, messagebox
from tkcalendar import DateEntry
from datetime import datetime, timedelta
import styles
from services.statistics_service import StatisticsService

class StatisticsTab:
    def __init__(self, parent, db):
        self.db = db
        self.stats_service = StatisticsService(db)
        
        # Главный фрейм
        self.frame = ttk.Frame(parent, style='BG.TFrame')
        main_frame = self.frame
        
        # Заголовок
        header = styles.create_label(main_frame, "📊 Отчёты и статистика", 'Heading.TLabel')
        header.pack(anchor='w', pady=(0, 20))
        
        # Карточка с фильтрами
        filter_card = styles.create_card_frame(main_frame)
        filter_card.pack(fill='x', pady=(0, 20))
        
        filter_inner = ttk.Frame(filter_card, style='White.TFrame')
        filter_inner.pack(fill='x', padx=20, pady=15)
        
        # Фильтры периода
        period_frame = ttk.Frame(filter_inner, style='White.TFrame')
        period_frame.pack(fill='x')
        
        # С:
        from_label = styles.create_label(period_frame, "С:", 'Card.TLabel')
        from_label.pack(side='left', padx=(0, 10))
        
        self.date_from = DateEntry(period_frame, width=12, background='darkblue',
                                   foreground='white', borderwidth=2,
                                   date_pattern='dd.mm.yyyy')
        self.date_from.set_date(datetime.now() - timedelta(days=30))  # По умолчанию последние 30 дней
        self.date_from.pack(side='left', padx=(0, 20))
        
        # По:
        to_label = styles.create_label(period_frame, "По:", 'Card.TLabel')
        to_label.pack(side='left', padx=(0, 10))
        
        self.date_to = DateEntry(period_frame, width=12, background='darkblue',
                                foreground='white', borderwidth=2,
                                date_pattern='dd.mm.yyyy')
        self.date_to.set_date(datetime.now())
        self.date_to.pack(side='left', padx=(0, 20))
        
        # Кнопка показать отчёт
        show_button = styles.create_button(period_frame, "📊 Показать отчёт", 
                                          self.load_statistics, 'Primary.TButton')
        show_button.pack(side='left')
        
        # Карточки со статистикой
        stats_cards_frame = ttk.Frame(main_frame, style='BG.TFrame')
        stats_cards_frame.pack(fill='x', pady=(0, 20))
        
        # Карточка 1: Обслужено машин
        cars_card = styles.create_card_frame(stats_cards_frame)
        cars_card.pack(side='left', padx=(0, 15), ipadx=50)
        cars_inner = ttk.Frame(cars_card, style='White.TFrame')
        cars_inner.pack(fill='both', padx=20, pady=15)
        label1 = styles.create_label(cars_inner, "🚗 Обслужено машин", 'Card.TLabel')
        label1.pack(anchor='w')
        self.cars_value = styles.create_label(cars_inner, "0", 'CardValue.TLabel')
        self.cars_value.pack(anchor='w', pady=(5, 0))
        
        # Карточка 2: Всего услуг
        services_card = styles.create_card_frame(stats_cards_frame)
        services_card.pack(side='left', padx=(0, 15), ipadx=50)
        services_inner = ttk.Frame(services_card, style='White.TFrame')
        services_inner.pack(fill='both', padx=20, pady=15)
        label2 = styles.create_label(services_inner, "📊 Всего услуг", 'Card.TLabel')
        label2.pack(anchor='w')
        self.services_value = styles.create_label(services_inner, "0", 'CardValue.TLabel')
        self.services_value.pack(anchor='w', pady=(5, 0))
        
        # Карточка 3: Средний чек
        avg_card = styles.create_card_frame(stats_cards_frame)
        avg_card.pack(side='left', ipadx=50)
        avg_inner = ttk.Frame(avg_card, style='White.TFrame')
        avg_inner.pack(fill='both', padx=20, pady=15)
        label3 = styles.create_label(avg_inner, "💰 Средний чек", 'Card.TLabel')
        label3.pack(anchor='w')
        self.avg_value = styles.create_label(avg_inner, "0 ₽", 'CardValue.TLabel')
        self.avg_value.pack(anchor='w', pady=(5, 0))
        
        # Таблица с услугами
        table_card = styles.create_card_frame(main_frame)
        table_card.pack(fill='both', expand=True)
        
        table_inner = ttk.Frame(table_card, style='White.TFrame')
        table_inner.pack(fill='both', expand=True, padx=20, pady=15)
        
        # Заголовок таблицы
        table_header = styles.create_label(table_inner, "Детализация по услугам", 'CardTitle.TLabel')
        table_header.pack(anchor='w', pady=(0, 10))
        
        # Фрейм для таблицы с скроллом
        tree_frame = ttk.Frame(table_inner, style='White.TFrame')
        tree_frame.pack(fill='both', expand=True)
        
        # Таблица
        self.services_tree = ttk.Treeview(tree_frame, 
                                         columns=('Услуга', 'Количество', 'Выручка'), 
                                         show='headings',
                                         height=15)
        self.services_tree.heading('Услуга', text='Услуга')
        self.services_tree.heading('Количество', text='Количество')
        self.services_tree.heading('Выручка', text='Выручка')
        self.services_tree.column('Услуга', width=400)
        self.services_tree.column('Количество', width=150)
        self.services_tree.column('Выручка', width=150)
        self.services_tree.pack(side='left', fill='both', expand=True)
        
        # Скроллбар
        tree_scroll = ttk.Scrollbar(tree_frame, orient='vertical', command=self.services_tree.yview)
        tree_scroll.pack(side='right', fill='y')
        self.services_tree.config(yscrollcommand=tree_scroll.set)
        
        # Итоговая строка
        total_frame = ttk.Frame(table_inner, style='White.TFrame')
        total_frame.pack(fill='x', pady=(10, 0))
        
        total_label = styles.create_label(total_frame, "ИТОГО:", 'CardTitle.TLabel')
        total_label.pack(side='left', padx=(0, 20))
        
        self.total_value = styles.create_label(total_frame, "0 ₽", 'CardValue.TLabel')
        self.total_value.pack(side='left')
        
        # Загружаем статистику при открытии
        self.load_statistics()
    
    def load_statistics(self):
        """Загрузить статистику за выбранный период"""
        try:
            # Получаем выбранные даты
            date_from = self.date_from.get_date()
            date_to = self.date_to.get_date()
            
            # Преобразуем в datetime с временем
            datetime_from = datetime.combine(date_from, datetime.min.time())
            datetime_to = datetime.combine(date_to, datetime.max.time())
            
            # Получаем статистику
            stats = self.stats_service.get_sales_statistics(datetime_from, datetime_to)
            
            # Обновляем карточки
            self.cars_value.config(text=str(stats['total_cars']))
            self.services_value.config(text=str(stats['total_services']))
            self.avg_value.config(text=f"{stats['average_check']:,.2f} ₽".replace(',', ' '))
            
            # Очищаем таблицу
            for item in self.services_tree.get_children():
                self.services_tree.delete(item)
            
            # Заполняем таблицу
            for service in stats['services']:
                revenue_str = f"{service['revenue']:,.2f} ₽".replace(',', ' ')
                self.services_tree.insert('', 'end', values=(
                    service['name'],
                    service['count'],
                    revenue_str
                ))
            
            # Добавляем итоговую строку в таблицу с выделением
            total_revenue_str = f"{stats['total_revenue']:,.2f} ₽".replace(',', ' ')
            total_item = self.services_tree.insert('', 'end', values=(
                '─── ИТОГО ───',
                stats['total_services'],
                total_revenue_str
            ), tags=('total',))
            
            # Стилизуем итоговую строку
            self.services_tree.tag_configure('total', background='#e3f2fd', font=('Arial', 10, 'bold'))
            
            # Обновляем нижнюю итоговую строку
            self.total_value.config(text=total_revenue_str)
            
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось загрузить статистику:\n{str(e)}")
