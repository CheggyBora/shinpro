"""
Миграция: добавление полей для мягкого удаления нарядов
Запустить один раз для обновления существующей базы данных
"""
import sqlite3
import os
from config import DATABASE_URL

def migrate():
    # Извлекаем путь к базе данных из DATABASE_URL
    if DATABASE_URL.startswith('sqlite:///'):
        db_path = DATABASE_URL.replace('sqlite:///', '')
    else:
        print("Миграция работает только для SQLite")
        return
    
    if not os.path.exists(db_path):
        print(f"База данных не найдена: {db_path}")
        print("Миграция не требуется - база будет создана с новой схемой")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Проверяем, существует ли уже поле is_deleted
        cursor.execute("PRAGMA table_info(work_orders)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'is_deleted' in columns:
            print("✓ Поля для мягкого удаления уже существуют")
            return
        
        print("Добавляем поля для мягкого удаления...")
        
        # Добавляем новые колонки
        cursor.execute("ALTER TABLE work_orders ADD COLUMN is_deleted BOOLEAN DEFAULT 0")
        cursor.execute("ALTER TABLE work_orders ADD COLUMN deleted_at TIMESTAMP")
        cursor.execute("ALTER TABLE work_orders ADD COLUMN deleted_reason VARCHAR(500)")
        
        # Устанавливаем значения по умолчанию для существующих записей
        cursor.execute("UPDATE work_orders SET is_deleted = 0 WHERE is_deleted IS NULL")
        
        conn.commit()
        print("✓ Миграция успешно выполнена!")
        print("  Добавлены поля: is_deleted, deleted_at, deleted_reason")
        
    except sqlite3.Error as e:
        print(f"✗ Ошибка миграции: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    migrate()
