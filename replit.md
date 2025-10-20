# Система учёта шиномонтажа

## Overview
This **Windows desktop application**, built with Python and Tkinter, streamlines tire service shop operations. It manages order processing, employee and tire storage, and generates financial documents. Key features include a modern UI, robust SQLite database integration, and **automated A4 PDF printing directly to Windows printers** with Cyrillic support. It aims to enhance efficiency, reduce errors, and improve customer service for small to medium-sized tire service businesses.

## User Preferences
- I prefer simple language.
- I want iterative development.
- Ask before making major changes.
- I prefer detailed explanations.
- Do not make changes to the folder `receipts/`.
- Do not make changes to the file `run_app.sh`.

## System Architecture

### UI/UX Design
The application features a modern, clean design with card-based layouts, consistent spacing, and a blue/gray/light color scheme. Typography prioritizes readability with larger headings and platform-specific fonts, ensuring full Cyrillic support. `ttkthemes` are used for all UI elements, and primary actions are indicated by blue buttons. Custom font handling ensures proper display across Windows, Linux, and Mac, including bundled DejaVu Sans for Cyrillic support in both GUI and PDF documents.

### Technical Implementation
The application is built with Python 3.11, using Tkinter for the GUI and SQLAlchemy for ORM. It primarily uses an SQLite database (`tire_shop.db`) but supports PostgreSQL via an environment variable. ReportLab generates all A4 PDF documents, branded "Шиномонтаж РИФ", with DejaVu Sans for Cyrillic text. The application is designed for Windows 10/11, leveraging native `os.startfile(file, "print")` for automated printing.

### Feature Specifications

**Core Modules:**
- **Employees Tab**: Manages employee registration, PIN-protected commission rates, shift tracking, and salary viewing.
- **Orders Tab**: Facilitates comprehensive order processing with license plate autocomplete (auto-clears after order creation), a two-step order creation workflow, and a detailed 4-column service panel allowing quantity editing. Column 3 (editable services) is ordered with "Ремонт жгутом" and "Подкачка/проверка давления" at the top for quick access. It supports multi-tab work orders, automatic pricing based on vehicle type and wheel diameter, discount systems (including an auto-discount for full client data and rim-specific discount), and **A4 PDF receipt printing**. Receipt format shows: service name, quantity, discounted unit price, and line total without strikethrough or explicit discount percentages. Each active order tab includes a **Delete Draft Order** button (🗑) that allows hard deletion of draft orders only with confirmation dialog.
- **History Tab**: Provides a paginated view of past work orders, searchable by vehicle license plate. Includes a **Delete Order** button with confirmation dialog for soft-deleting work orders (marks as deleted without removing from database).
- **Tire Storage Tab**: Manages tire intake and release with full payment integration. Features payment method selection (cash/card), creates WorkOrder for statistics tracking, generates **payment receipt PDF** and **2 copies of storage acceptance act**. Upon release, generates **release act PDF**. All storage orders appear in statistics and history without salary accrual.
- **Statistics/Reports Tab**: Displays sales statistics with date filtering (default: last 30 days). Shows summary cards (cars serviced, total services, average check) and a detailed services breakdown table. All deleted orders are automatically excluded from statistics.
- **Price List Tab**: Allows administrators to view and edit service prices across different vehicle types and wheel diameters (R13-R24). Price modifications are PIN-protected and saved in batches, with real-time updates.

**Service Pricing & Discounts:**
The system manages over 42 services, categorized by type, with prices varying by vehicle type and wheel diameter for basic services. It supports "from" pricing for special services and implements automated discounts:
- **Rim Discount**: Applied only to "Правка литого диска" service via per-item `discount_percent` field (10% or 20%)
- **General Discount**: Applied to the entire order subtotal (10% or 15%)
- **Auto Discount**: 5% automatic discount when full client information is provided
- **Discount Priority**: general_discount > auto_discount (only one applies to order total)

**Database Schema:**
The SQLite database includes tables for `employees`, `work_shifts`, `clients`, `cars`, `services`, `work_orders`, `work_order_items`, `salary_transactions`, `settings`, and `tire_storage`.

**Car Parameter Memory:**
The system automatically remembers and saves vehicle parameters (vehicle_type and wheel_diameter) for each car:
- When creating a new order, the selected vehicle type and wheel diameter are saved to the Car record
- When creating subsequent orders for the same car, these parameters are automatically pre-filled
- Parameters are updated with each new order to always reflect the most recent configuration
- Autofill priority: Car saved parameters > Last WorkOrder > Empty (new car)

**Order Deletion System:**
The system implements two types of deletion based on order status:

1. **Hard Delete (Draft Orders Only):**
   - Available directly in active order tabs via the 🗑 button
   - Only draft orders (status='draft') can be hard-deleted
   - Requires confirmation dialog: "Вы действительно хотите удалить наряд?"
   - Permanently removes order and all items from database
   - Automatically closes the order tab after deletion
   - Protected by dual checks in UI and service layer

2. **Soft Delete (Paid/Completed Orders):**
   - Available in History tab for paid/completed orders
   - Sets `is_deleted` flag to True, records `deleted_at` timestamp
   - Reversal salary transactions automatically created to rollback employee commissions
   - Deleted orders excluded from all statistics, reports, and salary calculations
   - Data preserved for audit trail and potential recovery

### System Design Choices
The project is structured into `models/`, `services/`, and `ui/` for modularity. `config.py` centralizes settings, and `styles.py` manages UI styling. `init_data.py` populates initial database data. An admin PIN (`0000` default) protects sensitive operations.

## External Dependencies

- **Python 3.11+**: Core programming language.
- **SQLAlchemy**: ORM for database interaction.
- **Tkinter**: GUI toolkit.
- **ttkthemes**: Modern themes for Tkinter.
- **tkcalendar**: Date picker widget for statistics filtering.
- **ReportLab**: PDF document generation.
- **python-dotenv**: Environment variable management.
- **PostgreSQL (Optional)**: Alternative database backend.
- **x11vnc (Replit only)**: VNC server for remote access.
- **Fluxbox (Replit only)**: Lightweight window manager for VNC.