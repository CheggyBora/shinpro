# Система учёта шиномонтажа

## Overview
This is a **Windows desktop application** built with Python and Tkinter, designed to manage a tire service shop. Its primary purpose is to streamline operations such as order processing, employee management, tire storage, and generating financial documents. The application features a modern UI, robust database integration, and **automated PDF printing directly to Windows printers**.

**Target Platform: Windows**
- Primary deployment: Windows 10/11
- PDF printing: Uses Windows native `os.startfile(file, "print")` for automatic printing
- Local database: SQLite (no server required)
- Easy installation: Double-click `.bat` file to run
- **All documents in A4 format** for standard office printers

**Key Capabilities:**
- Management of employees, work shifts, and salary calculations.
- Comprehensive order processing with support for various vehicle types and wheel diameters.
- Advanced tire storage functionality, including automated documentation for intake and release.
- Detailed historical data tracking for vehicles and services.
- **Automated PDF printing**: Print receipts and storage documents directly to printer with one click.
- **Preview mode**: View PDFs before printing when needed.
- **Professional A4 receipts**: All documents branded as "Шиномонтаж РИФ" with Cyrillic support (DejaVu Sans font)

**Business Vision & Market Potential:**
The application aims to provide small to medium-sized tire service businesses with an efficient, user-friendly, and modern tool to manage their daily operations. By automating key processes and providing clear oversight, it helps improve customer service, reduce manual errors, and enhance overall business efficiency.

## User Preferences
- I prefer simple language.
- I want iterative development.
- Ask before making major changes.
- I prefer detailed explanations.
- Do not make changes to the folder `receipts/`.
- Do not make changes to the file `run_app.sh`.

## System Architecture

### UI/UX Design
The application features a modern, clean design with a focus on usability.
- **Color Scheme**: Blue (`#2563eb`), Gray (`#64748b`), Light (`#f8fafc`).
- **Design Pattern**: Card-based layouts with shadows are used across all tabs for a consistent and modern look.
- **Typography**: Uses modern typography with larger headings (16-18pt) for readability.
- **Widgets**: Utilizes `ttkthemes` for all UI elements to ensure a contemporary appearance.
- **Spacing**: Improved padding (10-20px) for better visual comfort.
- **Buttons**: Blue for primary actions, green for confirmations.

### Technical Implementation
- **Backend**: Python 3.11 with SQLAlchemy for ORM.
- **GUI**: Tkinter, enhanced with `ttkthemes` for modern styling.
- **Database**: SQLite (по умолчанию) или PostgreSQL. Локальная база данных SQLite хранится в файле `tire_shop.db`. Для PostgreSQL используется переменная окружения `DATABASE_URL`.
- **Reporting**: ReportLab is used for generating PDF documents (receipts, storage documents). All PDFs are A4 format with DejaVu Sans font for Cyrillic support.
- **Company Branding**: "Шиномонтаж РИФ" - displayed on all receipts and documents.
- **VNC**: The application runs within a VNC server (x11vnc with Fluxbox window manager) on port 5900, enabling remote access and display.

### Feature Specifications

**Core Modules:**
- **Employees Tab**: Manages employee registration, percentage-based commission rates (PIN-protected), shift tracking, and salary viewing.
- **Orders Tab**: 
  - **Workflow (Two-Step Process)**: 
    1. On "Наряды" tab: Enter car license plate in "Номер автомобиля:" field
    2. Click "Создать наряд" button → Opens modal dialog with: диаметр колеса, тип транспорта, имя клиента, номер телефона
    3. Click "Создать наряд" in dialog → Opens order tab with service panel above and order details below
  - **4-Column Service Panel**: 
    - Column 1: Подкачка, Съем+Установка, Мойка, Шиномонтаж, Балансировка, Герметик обода, Обработка смазкой, Правка литого диска, Съем+Установка внутреннего колеса (9 services)
    - Column 2: Runflat, Оптимизация балансировки, Замена вентиля, Установка датчика давления, Ремонт жгутом, Шлифовка бортов диска, Шлифовка ступицы, Косметический ремонт шины, Дошиповка, Грязевая покрышка АТ/МТ (10 services)  
    - Column 3: Editable services + Repairs (7 services)
    - Column 4: Consumables + Checks (8 services)
  - Multi-tab work orders, automatic pricing based on vehicle type and diameter.
  - Discount system (5%, 10%, 15%) and 5% auto-discount when client name AND phone are filled.
  - Payment processing (cash/card), **A4 PDF receipt printing** with professional layout and Cyrillic support.
- **History Tab**: Allows searching for vehicle history by plate number and viewing detailed past work orders.
- **Tire Storage Tab**: Manages tire intake and release, generating **A4 format PDF documents** automatically:
    - **Intake**: Records vehicle number, driver's license, storage type (tires/tires with rims), rim type, diameter, tire brand, damage description, wear, comments, and calculates storage price. Generates `storage_{id}.pdf` with **2 copies** (for customer and archive).
    - **Release**: Tracks stored sets, displays relevant information, and generates `release_{id}.pdf` upon release with professional A4 layout.

**Service Pricing:**
- Over 42 services categorized into: Basic, Rim Repair, Additional, Consumables, Checks, and Repairs (patching, sidewall repair).
- Prices vary by vehicle type and wheel diameter for basic services.
- "From" prices for certain services (e.g., rim repair, special work) are editable within the order.
- Automated discounts (5%, 10%, 15%) and a 5% discount for full client data entry.

**Database Schema:**
- `employees`: Employee details and individual rates.
- `work_shifts`: Records of employee shifts.
- `clients`: Client information (name, phone).
- `cars`: Vehicle details.
- `services`: Price list for all services.
- `work_orders`: Main work order records.
- `work_order_items`: Line items within work orders.
- `salary_transactions`: Records of salary accruals.
- `settings`: Application settings, including admin PIN.
- `tire_storage`: Records for tire storage (auto number, driver's license, type, rim type, diameter, brand, damage, wear, comments, price, status).

### System Design Choices
- **Modularity**: Project structured into `models/`, `services/`, and `ui/` directories for clear separation of concerns.
- **Configuration**: `config.py` for database connection, `styles.py` for centralized UI styling.
- **Data Initialization**: `init_data.py` for populating the database with initial service prices and other essential data.
- **Security**: Admin PIN (default `0000`) for sensitive operations like changing employee rates.

## Локальный запуск приложения (Windows)

**Целевая платформа: Windows 10/11**

Приложение разработано специально для Windows и использует нативные возможности системы для печати документов.

### Требования
- **Windows 10 или Windows 11**
- Python 3.11 или новее
- Принтер, подключенный к Windows (для автоматической печати чеков)
- Библиотеки Python (устанавливаются автоматически)

### Инструкция по установке и запуску

1. **Скачайте проект** на свой компьютер
   - Через Git: `git clone <url-репозитория>`
   - Или скачайте ZIP-архив и распакуйте

2. **Установите зависимости**
   ```bash
   pip install -r requirements.txt
   ```

3. **Запустите приложение (Windows)**
   - Дважды кликните на файл `Запуск.bat`
   - Или создайте ярлык на рабочем столе для файла `Запуск.bat`

### Функционал печати (Windows)
- **Автоматическая печать**: Чеки отправляются на принтер по умолчанию одним кликом
- **Предпросмотр**: Можно просмотреть PDF перед печатью
- Используется Windows API: `os.startfile(file, "print")`

### База данных

По умолчанию приложение использует **SQLite** - локальную файловую базу данных (`tire_shop.db`), которая создается автоматически при первом запуске. Не требуется установка PostgreSQL или других серверов баз данных.

Все данные хранятся в файле `tire_shop.db` в папке приложения.

### Структура файлов
- `Запуск.bat` - файл запуска для Windows
- `start.sh` - файл запуска для Linux/Mac
- `requirements.txt` - список необходимых библиотек
- `tire_shop.db` - файл базы данных (создается автоматически)
- `receipts/` - папка с созданными чеками (создается автоматически)

## External Dependencies

### Обязательные зависимости (для локального запуска)
- **Python 3.11+**: Язык программирования
- **SQLAlchemy**: Python SQL toolkit and Object Relational Mapper (ORM) for interacting with the database.
- **Tkinter**: Python's standard GUI toolkit for creating the desktop application interface (обычно уже включен в Python).
- **ttkthemes**: A Tkinter extension providing modern themes for `ttk` widgets.
- **ReportLab**: Python library for generating PDF documents (receipts, storage forms).
- **python-dotenv**: Для работы с переменными окружения

### Опциональные зависимости
- **PostgreSQL**: Можно использовать вместо SQLite для продакшн-окружения
- **Evince**: (Assumed external PDF viewer) Automatically opens generated PDF documents.
- **x11vnc**: VNC server for remote access to the graphical interface (только для Replit).
- **Fluxbox**: Lightweight window manager used within the VNC environment (только для Replit).