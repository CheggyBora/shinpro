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
- **Orders Tab**: Facilitates comprehensive order processing with license plate autocomplete, a two-step order creation workflow, and a detailed 4-column service panel allowing quantity editing. It supports multi-tab work orders, automatic pricing based on vehicle type and wheel diameter, discount systems (including an auto-discount for full client data), and **A4 PDF receipt printing**.
- **History Tab**: Provides a paginated view of past work orders, searchable by vehicle license plate. Includes a **Delete Order** button with confirmation dialog for soft-deleting work orders (marks as deleted without removing from database).
- **Tire Storage Tab**: Manages tire intake and release, generating **A4 PDF documents** (`storage_{id}.pdf` and `release_{id}.pdf`) with detailed records for stored items.
- **Statistics/Reports Tab**: Displays sales statistics with date filtering (default: last 30 days). Shows summary cards (cars serviced, total services, average check) and a detailed services breakdown table. All deleted orders are automatically excluded from statistics.
- **Price List Tab**: Allows administrators to view and edit service prices across different vehicle types and wheel diameters (R13-R24). Price modifications are PIN-protected and saved in batches, with real-time updates.

**Service Pricing:**
The system manages over 42 services, categorized by type, with prices varying by vehicle type and wheel diameter for basic services. It supports "from" pricing for special services and implements automated discounts.

**Database Schema:**
The SQLite database includes tables for `employees`, `work_shifts`, `clients`, `cars`, `services`, `work_orders`, `work_order_items`, `salary_transactions`, `settings`, and `tire_storage`.

**Soft-Delete System:**
Work orders use soft-delete (is_deleted flag) instead of hard deletion. When an order is deleted:
- The `is_deleted` flag is set to True, `deleted_at` timestamp is recorded, and `deleted_reason` can be optionally provided
- Reversal salary transactions are automatically created to rollback employee commissions
- Deleted orders are excluded from all statistics, reports, and salary calculations
- Data is preserved for audit trail and potential recovery

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