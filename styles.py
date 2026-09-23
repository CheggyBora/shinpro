import tkinter as tk
from tkinter import ttk
import platform
import os
import sys
from logger import log

# Определение шрифта в зависимости от платформы
def get_default_font_name():
    """Возвращает имя подходящего шрифта для текущей платформы с поддержкой кириллицы"""
    system = platform.system()

    if system == 'Windows':
        # Segoe UI — системный шрифт Windows: заметно опрятнее Arial
        # и полностью поддерживает кириллицу
        return 'Segoe UI'
    else:
        # На Linux/Mac будет использоваться DejaVu Sans (регистрируется в main_window.py)
        return 'DejaVu Sans'

def register_dejavu_font():
    """Регистрирует DejaVu Sans шрифт для Tkinter (вызывать ПОСЛЕ создания root window)"""
    system = platform.system()

    if system == 'Windows':
        return  # На Windows используем системный Segoe UI

    try:
        from tkinter import font as tkfont

        # Определяем путь к шрифту
        if getattr(sys, 'frozen', False):
            # Для PyInstaller EXE
            base_path = sys._MEIPASS
        else:
            # Для обычного запуска - styles.py находится в корневой директории
            base_path = os.path.dirname(os.path.abspath(__file__))

        font_path = os.path.join(base_path, "fonts", "DejaVuSans.ttf")

        if os.path.exists(font_path):
            # Проверяем, что шрифт не зарегистрирован
            if 'DejaVu Sans' not in tkfont.families():
                log.debug(f"Регистрация DejaVu Sans шрифта для GUI: {font_path}")
            return True
        else:
            log.warning(f"ВНИМАНИЕ: Файл шрифта не найден: {font_path}")
            return False
    except Exception as e:
        log.error(f"Ошибка при регистрации шрифта: {e}")
        return False

# Получаем имя шрифта (регистрация будет позже в main_window.py)
DEFAULT_FONT = get_default_font_name()

COLORS = {
    # Основной синий — действия и акценты
    'primary': '#2563eb',
    'primary_hover': '#1d4ed8',
    'primary_dark': '#1e40af',
    'primary_soft': '#eff6ff',

    # Нейтральные
    'secondary': '#475569',
    'secondary_hover': '#334155',

    # Состояния
    'success': '#059669',
    'success_hover': '#047857',
    'danger': '#dc2626',
    'danger_hover': '#b91c1c',
    'warning': '#d97706',

    # Поверхности
    'bg': '#f1f5f9',
    'bg_card': '#ffffff',
    'bg_subtle': '#f8fafc',

    # Текст
    'text': '#0f172a',
    'text_secondary': '#64748b',
    'gray': '#64748b',

    # Линии
    'border': '#e2e8f0',
    'border_strong': '#cbd5e1',
    'hover': '#f1f5f9',
}

FONTS = {
    'title': (DEFAULT_FONT, 16, 'bold'),
    'heading': (DEFAULT_FONT, 14, 'bold'),
    'subheading': (DEFAULT_FONT, 11, 'bold'),
    'normal': (DEFAULT_FONT, 10),
    'small': (DEFAULT_FONT, 9),
    'button': (DEFAULT_FONT, 10),
    'value': (DEFAULT_FONT, 22, 'bold'),
}


def _button_style(style, name, background, hover, foreground='#ffffff', padding=(16, 9)):
    """
    Описать цветную кнопку с состояниями наведения и нажатия.

    Без явного map кнопка не реагирует на мышь и выглядит мёртвой.
    """
    style.configure(name,
                    font=FONTS['button'],
                    padding=padding,
                    background=background,
                    foreground=foreground,
                    borderwidth=0,
                    focuscolor=background,
                    relief='flat')
    style.map(name,
              background=[('pressed', hover), ('active', hover), ('disabled', COLORS['border'])],
              foreground=[('disabled', COLORS['text_secondary'])],
              relief=[('pressed', 'flat'), ('active', 'flat')])


def apply_modern_styles(root):
    style = ttk.Style(root)

    # Тема clam — единственная из встроенных, где ttk честно применяет
    # заданные цвета к кнопкам, вкладкам и заголовкам таблиц.
    # Без неё (на Windows по умолчанию идёт vista) все настройки цвета
    # молча игнорируются, и интерфейс остаётся системно-серым.
    try:
        style.theme_use('clam')
    except tk.TclError:
        pass

    root.configure(bg=COLORS['bg'])
    # Глобальный шрифт через option_add не задаём: он перебивает размеры,
    # заданные в стилях ttk, и крупные числа в карточках становятся мелкими.
    # Обычным виджетам tk шрифт передаём явно там, где они создаются.

    # --- Вкладки ------------------------------------------------------
    # Рамки убираем полностью: в clam вкладка по умолчанию обведена
    # со всех сторон и получается лесенка из коробочек.
    # Размер вкладки при выборе не меняем — иначе соседние прыгают.
    style.configure('TNotebook',
                    background=COLORS['bg'],
                    borderwidth=0,
                    bordercolor=COLORS['bg'],
                    lightcolor=COLORS['bg'],
                    darkcolor=COLORS['bg'],
                    tabmargins=[10, 8, 10, 0])
    style.configure('TNotebook.Tab',
                    padding=[24, 12],
                    font=(DEFAULT_FONT, 10),
                    background=COLORS['bg'],
                    foreground=COLORS['text_secondary'],
                    borderwidth=0,
                    bordercolor=COLORS['bg'],
                    lightcolor=COLORS['bg'],
                    darkcolor=COLORS['bg'],
                    focuscolor=COLORS['bg'])
    style.map('TNotebook.Tab',
              background=[('selected', COLORS['bg_card']), ('active', COLORS['bg_subtle'])],
              foreground=[('selected', COLORS['primary']), ('active', COLORS['text'])],
              lightcolor=[('selected', COLORS['bg_card'])],
              darkcolor=[('selected', COLORS['bg_card'])],
              focuscolor=[('selected', COLORS['bg_card'])])

    # --- Поверхности --------------------------------------------------
    style.configure('TFrame', background=COLORS['bg'])
    style.configure('BG.TFrame', background=COLORS['bg'])
    style.configure('White.TFrame', background=COLORS['bg_card'])
    style.configure('Card.TFrame',
                    background=COLORS['bg_card'],
                    relief='flat',
                    borderwidth=0)

    # --- Текст --------------------------------------------------------
    style.configure('TLabel', background=COLORS['bg'], foreground=COLORS['text'],
                    font=FONTS['normal'])
    style.configure('Heading.TLabel', background=COLORS['bg'],
                    font=FONTS['heading'], foreground=COLORS['text'])
    style.configure('Subheading.TLabel', background=COLORS['bg'],
                    font=FONTS['subheading'], foreground=COLORS['text'])
    style.configure('Card.TLabel', background=COLORS['bg_card'],
                    foreground=COLORS['text'], font=FONTS['normal'])
    style.configure('CardHeading.TLabel', background=COLORS['bg_card'],
                    font=FONTS['subheading'], foreground=COLORS['text'])
    style.configure('CardTitle.TLabel', background=COLORS['bg_card'],
                    font=(DEFAULT_FONT, 13, 'bold'), foreground=COLORS['text'])
    style.configure('CardValue.TLabel', background=COLORS['bg_card'],
                    font=FONTS['value'], foreground=COLORS['primary'])
    style.configure('Muted.TLabel', background=COLORS['bg_card'],
                    font=FONTS['small'], foreground=COLORS['text_secondary'])
    style.configure('ServiceHeading.TLabel',
                    background=COLORS['bg_card'],
                    foreground=COLORS['text_secondary'],
                    font=(DEFAULT_FONT, 9, 'bold'),
                    padding=[2, 6])

    # --- Кнопки -------------------------------------------------------
    _button_style(style, 'Primary.TButton', COLORS['primary'], COLORS['primary_hover'])
    _button_style(style, 'Success.TButton', COLORS['success'], COLORS['success_hover'])
    _button_style(style, 'Danger.TButton', COLORS['danger'], COLORS['danger_hover'])

    # Второстепенная кнопка — светлая с рамкой, чтобы не спорить с основной
    style.configure('Secondary.TButton',
                    font=FONTS['button'],
                    padding=(16, 9),
                    background=COLORS['bg_card'],
                    foreground=COLORS['secondary'],
                    bordercolor=COLORS['border_strong'],
                    borderwidth=1,
                    focuscolor=COLORS['bg_card'],
                    relief='solid')
    style.map('Secondary.TButton',
              background=[('pressed', COLORS['border']), ('active', COLORS['bg_subtle'])],
              foreground=[('disabled', COLORS['text_secondary'])])

    style.configure('TButton',
                    font=FONTS['button'],
                    padding=(14, 8),
                    background=COLORS['bg_card'],
                    foreground=COLORS['secondary'],
                    bordercolor=COLORS['border_strong'],
                    borderwidth=1,
                    focuscolor=COLORS['bg_card'],
                    relief='solid')
    style.map('TButton',
              background=[('pressed', COLORS['border']), ('active', COLORS['bg_subtle'])])

    # Кнопка услуги — компактная плитка, их на экране больше тридцати
    style.configure('Service.TButton',
                    font=(DEFAULT_FONT, 9),
                    padding=(8, 5),
                    background=COLORS['bg_subtle'],
                    foreground=COLORS['text'],
                    bordercolor=COLORS['border'],
                    borderwidth=1,
                    focuscolor=COLORS['bg_subtle'],
                    relief='solid',
                    anchor='w')
    style.map('Service.TButton',
              background=[('pressed', COLORS['primary_soft']), ('active', COLORS['primary_soft'])],
              foreground=[('active', COLORS['primary'])],
              bordercolor=[('active', COLORS['primary'])])

    # --- Поля ввода ---------------------------------------------------
    style.configure('TEntry',
                    fieldbackground=COLORS['bg_card'],
                    foreground=COLORS['text'],
                    bordercolor=COLORS['border_strong'],
                    lightcolor=COLORS['border_strong'],
                    darkcolor=COLORS['border_strong'],
                    borderwidth=1,
                    padding=(8, 7),
                    relief='solid')
    style.map('TEntry',
              bordercolor=[('focus', COLORS['primary'])],
              lightcolor=[('focus', COLORS['primary'])],
              darkcolor=[('focus', COLORS['primary'])])

    style.configure('TCombobox',
                    fieldbackground=COLORS['bg_card'],
                    background=COLORS['bg_card'],
                    foreground=COLORS['text'],
                    bordercolor=COLORS['border_strong'],
                    lightcolor=COLORS['border_strong'],
                    darkcolor=COLORS['border_strong'],
                    arrowcolor=COLORS['secondary'],
                    borderwidth=1,
                    padding=(8, 6),
                    arrowsize=14)
    style.map('TCombobox',
              bordercolor=[('focus', COLORS['primary'])],
              fieldbackground=[('readonly', COLORS['bg_card'])],
              foreground=[('readonly', COLORS['text'])])

    # --- Таблицы ------------------------------------------------------
    style.configure('Treeview',
                    background=COLORS['bg_card'],
                    foreground=COLORS['text'],
                    fieldbackground=COLORS['bg_card'],
                    font=FONTS['normal'],
                    rowheight=32,
                    bordercolor=COLORS['border'],
                    borderwidth=0,
                    relief='flat')
    style.configure('Treeview.Heading',
                    background=COLORS['bg_subtle'],
                    foreground=COLORS['text_secondary'],
                    font=(DEFAULT_FONT, 9, 'bold'),
                    relief='flat',
                    borderwidth=0,
                    padding=(10, 10))
    style.map('Treeview.Heading',
              background=[('active', COLORS['border'])])
    style.map('Treeview',
              background=[('selected', COLORS['primary'])],
              foreground=[('selected', '#ffffff')])
    # Убираем пунктирную рамку вокруг выделенной строки
    style.layout('Treeview.Item', [
        ('Treeitem.padding', {'sticky': 'nswe', 'children': [
            ('Treeitem.indicator', {'side': 'left', 'sticky': ''}),
            ('Treeitem.image', {'side': 'left', 'sticky': ''}),
            ('Treeitem.text', {'side': 'left', 'sticky': ''}),
        ]}),
    ])

    # --- Прочее -------------------------------------------------------
    style.configure('TScrollbar',
                    background=COLORS['border_strong'],
                    troughcolor=COLORS['bg_subtle'],
                    bordercolor=COLORS['bg_subtle'],
                    arrowcolor=COLORS['secondary'],
                    borderwidth=0,
                    arrowsize=13)
    style.map('TScrollbar',
              background=[('active', COLORS['secondary'])])

    style.configure('TSeparator', background=COLORS['border'])

    style.configure('TRadiobutton',
                    background=COLORS['bg_card'],
                    foreground=COLORS['text'],
                    font=FONTS['normal'],
                    focuscolor=COLORS['bg_card'])
    style.map('TRadiobutton',
              background=[('active', COLORS['bg_card'])],
              indicatorcolor=[('selected', COLORS['primary'])])

    style.configure('TCheckbutton',
                    background=COLORS['bg_card'],
                    foreground=COLORS['text'],
                    font=FONTS['normal'],
                    focuscolor=COLORS['bg_card'])


class NavBar(tk.Frame):
    """
    Плоская панель навигации вместо стандартных вкладок.

    Штатный ttk.Notebook рисует выбранную вкладку приподнятой коробкой,
    которая ещё и меняет размер — из-за этого интерфейс выглядит как
    программа девяностых. Здесь выбранный раздел отмечен цветом текста
    и полоской снизу, размеры при этом не скачут.
    """

    def __init__(self, parent, on_select=None, compact=False):
        super().__init__(parent, bg=COLORS['bg_card'], highlightthickness=0, bd=0)
        self.on_select = on_select
        self._items = []
        self._current = None

        self._strip = tk.Frame(self, bg=COLORS['bg_card'])
        self._strip.pack(fill='x')

        # Тонкая линия под навигацией отделяет её от содержимого
        tk.Frame(self, bg=COLORS['border'], height=1).pack(fill='x')

        self._pad_x = 14 if compact else 20
        self._pad_y = 8 if compact else 13
        self._font = (DEFAULT_FONT, 10 if compact else 11)

    def add(self, title, frame):
        index = len(self._items)

        holder = tk.Frame(self._strip, bg=COLORS['bg_card'], cursor='hand2')
        holder.pack(side='left')

        label = tk.Label(holder, text=title, font=self._font,
                         bg=COLORS['bg_card'], fg=COLORS['text_secondary'],
                         padx=self._pad_x, pady=self._pad_y, cursor='hand2')
        label.pack()

        # Полоска-указатель под активным разделом
        underline = tk.Frame(holder, bg=COLORS['bg_card'], height=3)
        underline.pack(fill='x')

        item = {'title': title, 'frame': frame, 'label': label,
                'underline': underline, 'holder': holder}
        self._items.append(item)

        for widget in (holder, label):
            widget.bind('<Button-1>', lambda e, i=index: self.select(i))
            widget.bind('<Enter>', lambda e, i=index: self._hover(i, True))
            widget.bind('<Leave>', lambda e, i=index: self._hover(i, False))

        if index == 0:
            self.select(0)
        return index

    def title_at(self, index):
        """Название раздела по номеру — чтобы не сверяться с порядком вкладок."""
        if 0 <= index < len(self._items):
            return self._items[index]['title']
        return None

    def _hover(self, index, entering):
        if index == self._current:
            return
        item = self._items[index]
        item['label'].config(fg=COLORS['text'] if entering else COLORS['text_secondary'])

    def select(self, index):
        if index < 0 or index >= len(self._items):
            return

        for i, item in enumerate(self._items):
            active = i == index
            item['label'].config(
                fg=COLORS['primary'] if active else COLORS['text_secondary'],
                font=self._font)
            item['underline'].config(
                bg=COLORS['primary'] if active else COLORS['bg_card'])
            if active:
                item['frame'].pack(fill='both', expand=True)
            else:
                item['frame'].pack_forget()

        self._current = index
        if self.on_select:
            self.on_select(index)

    def index(self, what='end'):
        """Совместимость с привычным интерфейсом вкладок."""
        return len(self._items) if what == 'end' else self._current

    def titles(self):
        return [item['title'] for item in self._items]

    def current(self):
        return self._current


def create_app_bar(parent, title, subtitle=''):
    """Верхняя полоса с названием программы."""
    bar = tk.Frame(parent, bg=COLORS['primary_dark'], height=58)
    bar.pack_propagate(False)

    inner = tk.Frame(bar, bg=COLORS['primary_dark'])
    inner.pack(fill='both', expand=True, padx=24)

    tk.Label(inner, text=title, font=(DEFAULT_FONT, 14, 'bold'),
             bg=COLORS['primary_dark'], fg='#ffffff').pack(side='left', pady=14)

    subtitle_label = tk.Label(inner, text=subtitle, font=(DEFAULT_FONT, 10),
                              bg=COLORS['primary_dark'], fg='#bfdbfe')
    subtitle_label.pack(side='right', pady=16)

    bar.subtitle_label = subtitle_label
    return bar


def create_card_frame(parent):
    """
    Карточка — белый блок на сером фоне.

    Обычный tk.Frame, а не ttk: он умеет рисовать тонкую рамку заданного
    цвета через highlightbackground. Раньше рамка задавалась relief='solid'
    и выходила грубой тёмной линией.

    Возвращается настоящий виджет — его используют как родителя
    для содержимого карточки.
    """
    return tk.Frame(parent,
                    bg=COLORS['bg_card'],
                    highlightbackground=COLORS['border'],
                    highlightcolor=COLORS['border'],
                    highlightthickness=1,
                    bd=0)


def create_button(parent, text, command, style='Primary.TButton'):
    return ttk.Button(parent, text=text, command=command, style=style, cursor='hand2')


def create_label(parent, text, style='TLabel'):
    return ttk.Label(parent, text=text, style=style)


def create_entry(parent, width=20):
    entry = ttk.Entry(parent, width=width, font=FONTS['normal'])
    return entry


def stripe_rows(tree):
    """
    Подкрасить чётные строки таблицы.

    На широких таблицах глаз теряет строку на полпути — полоски
    это лечат. Вызывать после заполнения таблицы.
    """
    tree.tag_configure('stripe', background=COLORS['bg_subtle'])
    for index, row in enumerate(tree.get_children()):
        tags = list(tree.item(row, 'tags'))
        if 'stripe' in tags:
            tags.remove('stripe')
        if index % 2:
            tags.append('stripe')
        tree.item(row, tags=tags)


def center_window(window, parent=None):
    """Центрирует окно на экране или относительно родительского окна"""
    window.update_idletasks()

    if parent:
        # Центрируем относительно родительского окна
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()

        window_width = window.winfo_width()
        window_height = window.winfo_height()

        x = parent_x + (parent_width - window_width) // 2
        y = parent_y + (parent_height - window_height) // 2
    else:
        # Центрируем на экране
        window_width = window.winfo_width()
        window_height = window.winfo_height()
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()

        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2

    window.geometry(f'+{x}+{y}')
