import telebot
from telebot import types
import sqlite3
from datetime import datetime, timedelta
import threading
import time
import schedule

# Токен бота
TOKEN = '8988021987:AAGxLUpbmirBTHXXPR2EufMsX3L_-C133tk'
bot = telebot.TeleBot(TOKEN)


# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('planner.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT NOT NULL,
            category TEXT,
            deadline TEXT,
            duration INTEGER DEFAULT 60,
            priority INTEGER DEFAULT 2,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            address TEXT DEFAULT '',
            items_to_bring TEXT DEFAULT ''
        )
    ''')

    conn.commit()
    return conn


# Глобальное подключение к БД
db = init_db()

# Словарь для хранения состояний пользователей
user_states = {}


def get_user_state(user_id):
    if user_id not in user_states:
        user_states[user_id] = {
            'step': None,
            'task_data': {}
        }
    return user_states[user_id]


# Умный расчет приоритета
def calculate_priority(deadline, category):
    priority_score = 0

    if deadline and deadline != 'no_deadline':
        try:
            deadline_date = datetime.strptime(deadline, '%Y-%m-%d %H:%M')
            days_until_deadline = (deadline_date - datetime.now()).days

            if days_until_deadline <= 0:
                priority_score += 50
            elif days_until_deadline <= 1:
                priority_score += 40
            elif days_until_deadline <= 3:
                priority_score += 30
            elif days_until_deadline <= 7:
                priority_score += 20
            else:
                priority_score += 10
        except:
            pass

    category_weights = {
        'Учеба': 25,
        'Работа': 25,
        'Быт': 10,
        'Развлечение': 5,
        'Здоровье': 20,
        'Финансы': 15,
        'Другое': 10
    }
    priority_score += category_weights.get(category, 10)

    if priority_score >= 60:
        return 3
    elif priority_score >= 35:
        return 2
    else:
        return 1


# Поиск свободного слота
def find_free_slot(user_id, duration_minutes, deadline=None):
    cursor = db.cursor()

    cursor.execute('''
        SELECT deadline, duration 
        FROM tasks 
        WHERE user_id = ? AND status = 'active' AND deadline != 'no_deadline'
        ORDER BY deadline
    ''', (user_id,))

    busy_slots = cursor.fetchall()

    current_time = datetime.now()

    if deadline and deadline != 'no_deadline':
        try:
            search_end = datetime.strptime(deadline, '%Y-%m-%d %H:%M')
        except:
            search_end = current_time + timedelta(days=7)
    else:
        search_end = current_time + timedelta(days=7)

    slot_start = current_time.replace(minute=0, second=0, microsecond=0)
    if current_time.minute >= 30:
        slot_start += timedelta(hours=1)
    else:
        slot_start += timedelta(minutes=30)

    while slot_start < search_end:
        slot_end = slot_start + timedelta(minutes=duration_minutes)

        if not (8 <= slot_start.hour < 22):
            slot_start += timedelta(minutes=30)
            continue

        is_free = True
        for busy_deadline, busy_duration in busy_slots:
            try:
                busy_start = datetime.strptime(busy_deadline, '%Y-%m-%d %H:%M')
                busy_end = busy_start + timedelta(minutes=busy_duration)

                if (slot_start < busy_end and slot_end > busy_start):
                    is_free = False
                    break
            except:
                continue

        if is_free:
            return slot_start.strftime('%Y-%m-%d %H:%M')

        slot_start += timedelta(minutes=30)

    return (current_time + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')


# Оценка длительности
def estimate_duration(title, category):
    title_lower = title.lower()

    quick_keywords = ['позвонить', 'отправить', 'проверить', 'записать', 'купить']
    long_keywords = ['изучить', 'разработать', 'создать', 'написать отчет', 'подготовиться']

    if any(word in title_lower for word in quick_keywords):
        return 30
    elif any(word in title_lower for word in long_keywords):
        return 120
    elif category in ['Учеба', 'Работа']:
        return 90
    else:
        return 60


# Главное меню
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('➕ Новая задача')
    btn2 = types.KeyboardButton('📋 Мои задачи')
    btn3 = types.KeyboardButton('📊 Статистика')
    btn4 = types.KeyboardButton('✅ Выполненные')
    btn5 = types.KeyboardButton('❓ Помощь')
    markup.add(btn1, btn2, btn3, btn4, btn5)
    return markup


# Команда /start
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    user_states[user_id] = {'step': None, 'task_data': {}}

    welcome_text = (
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "Я твой умный бот-планер. Я помогу:\n"
        "• Создавать и управлять задачами\n"
        "• Автоматически определять приоритеты\n"
        "• Находить свободное время\n"
        "• Напоминать о важных делах\n\n"
        "Выберите действие в меню:"
    )

    bot.send_message(message.chat.id, welcome_text, reply_markup=main_menu())


# Обработчик текстовых сообщений
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    text = message.text

    if text == '➕ Новая задача':
        start_new_task(message)
    elif text == '📋 Мои задачи':
        show_active_tasks(message)
    elif text == '📊 Статистика':
        show_statistics(message)
    elif text == '✅ Выполненные':
        show_completed_tasks(message)
    elif text == '❓ Помощь':
        show_help(message)
    elif text == '❌ Отмена':
        cancel_operation(message)
    else:
        # Проверяем, находится ли пользователь в процессе создания задачи
        state = get_user_state(user_id)
        if state['step']:
            process_task_step(message)
        else:
            bot.send_message(
                message.chat.id,
                "Используйте кнопки меню для навигации",
                reply_markup=main_menu()
            )


def start_new_task(message):
    user_id = message.from_user.id
    state = get_user_state(user_id)
    state['step'] = 'title'
    state['task_data'] = {}

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton('❌ Отмена'))

    msg = bot.send_message(
        message.chat.id,
        "📝 Шаг 1/6: Введите название задачи:",
        reply_markup=markup
    )


def process_task_step(message):
    user_id = message.from_user.id
    state = get_user_state(user_id)
    text = message.text

    if state['step'] == 'title':
        state['task_data']['title'] = text
        state['step'] = 'category'

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        categories = ['📚 Учеба', '💼 Работа', '🏠 Быт', '🎮 Развлечение', '💪 Здоровье', '💰 Финансы', '📋 Другое']
        for cat in categories:
            markup.add(types.KeyboardButton(cat))
        markup.add(types.KeyboardButton('❌ Отмена'))

        bot.send_message(
            message.chat.id,
            "Шаг 2/6: Выберите категорию задачи:",
            reply_markup=markup
        )

    elif state['step'] == 'category':
        # Извлекаем название категории из emoji+текст
        category = text.split(' ', 1)[1] if ' ' in text else text
        state['task_data']['category'] = category
        state['step'] = 'waiting_for_deadline'
        
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(
            types.KeyboardButton('🚫 Без дедлайна'),
            types.KeyboardButton('❌ Отмена')
        )
        
        bot.send_message(
            message.chat.id,
            "Шаг 3/6: Укажите дедлайн\n\n"
            "📆 Введите дату и время в формате:\n"
            "ГГГГ-ММ-ДД ЧЧ:ММ\n"
            "📌 Пример: 2026-12-31 23:59\n\n"
            "Или нажмите кнопку:",
            reply_markup=markup
        )

    elif state['step'] == 'waiting_for_deadline':
        text = message.text
        
        # Обработка отмены
        if text == '❌ Отмена':
            cancel_operation(message)
            return
        
        # Обработка кнопки "Без дедлайна"
        if text == '🚫 Без дедлайна':
            state['task_data']['deadline'] = 'no_deadline'
            state['step'] = 'duration'
            
            estimated = estimate_duration(
                state['task_data'].get('title', ''),
                state['task_data'].get('category', '')
            )
            
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add(
                types.KeyboardButton(f'⚡ {estimated} мин'),
                types.KeyboardButton('🕐 30 мин'),
                types.KeyboardButton('🕑 1 час'),
                types.KeyboardButton('🕒 2 часа'),
                types.KeyboardButton('❌ Отмена')
            )
            
            bot.send_message(
                message.chat.id,
                f"Шаг 4/6: Укажите длительность задачи:\n"
                f"Рекомендуемое время: {estimated} минут",
                reply_markup=markup
            )
            return
        
        # Пробуем распарсить введённую пользователем дату
        try:
            deadline = datetime.strptime(text, '%Y-%m-%d %H:%M')
            
            if deadline < datetime.now():
                bot.send_message(
                    message.chat.id,
                    "❌ Дедлайн не может быть в прошлом!\n\n"
                    "Введите будущую дату или нажмите 'Без дедлайна'"
                )
                return
            
            state['task_data']['deadline'] = deadline.strftime('%Y-%m-%d %H:%M')
            state['step'] = 'duration'
            
            estimated = estimate_duration(
                state['task_data'].get('title', ''),
                state['task_data'].get('category', '')
            )
            
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add(
                types.KeyboardButton(f'⚡ {estimated} мин'),
                types.KeyboardButton('🕐 30 мин'),
                types.KeyboardButton('🕑 1 час'),
                types.KeyboardButton('🕒 2 часа'),
                types.KeyboardButton('❌ Отмена')
            )
            
            bot.send_message(
                message.chat.id,
                f"Шаг 4/6: Укажите длительность задачи:\n"
                f"Рекомендуемое время: {estimated} минут",
                reply_markup=markup
            )
            
        except ValueError:
            bot.send_message(
                message.chat.id,
                "❌ Неверный формат!\n\n"
                "Используйте: ГГГГ-ММ-ДД ЧЧ:ММ\n"
                "Пример: 2026-12-31 23:59\n\n"
                "Или нажмите 'Без дедлайна'",
                reply_markup=markup
            )
                
    elif state['step'] == 'duration':
        if '30 мин' in text:
            duration = 30
        elif '1 час' in text:
            duration = 60
        elif '2 часа' in text:
            duration = 120
        elif 'мин' in text:
            duration = int(text.split()[0])
        else:
            bot.send_message(message.chat.id, "Пожалуйста, выберите один из вариантов")
            return

        state['task_data']['duration'] = duration
        state['step'] = 'additional'

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(
            types.KeyboardButton('📍 Добавить адрес'),
            types.KeyboardButton('🎒 Добавить вещи'),
            types.KeyboardButton('✅ Пропустить'),
            types.KeyboardButton('❌ Отмена')
        )

        bot.send_message(
            message.chat.id,
            "Шаг 5/6: Хотите добавить дополнительную информацию?",
            reply_markup=markup
        )

    elif state['step'] == 'additional':
        if text == '📍 Добавить адрес':
            state['step'] = 'address'
            msg = bot.send_message(
                message.chat.id,
                "Введите адрес:",
                reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add(types.KeyboardButton('❌ Отмена'))
            )
        elif text == '🎒 Добавить вещи':
            state['step'] = 'items'
            msg = bot.send_message(
                message.chat.id,
                "Введите список вещей через запятую:",
                reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add(types.KeyboardButton('❌ Отмена'))
            )
        elif text == '✅ Пропустить':
            save_task(message)

    elif state['step'] == 'address':
        state['task_data']['address'] = text
        state['step'] = 'items'
        msg = bot.send_message(
            message.chat.id,
            "Введите список вещей (или нажмите 'Пропустить'):",
            reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add(
                types.KeyboardButton('✅ Пропустить'),
                types.KeyboardButton('❌ Отмена')
            )
        )

    elif state['step'] == 'items':
        if text != '✅ Пропустить':
            state['task_data']['items'] = text
        save_task(message)


def save_task(message):
    user_id = message.from_user.id
    state = get_user_state(user_id)
    task = state['task_data']

    # Расчет приоритета
    priority = calculate_priority(
        task.get('deadline'),
        task.get('category')
    )

    # Поиск свободного времени
    if task.get('deadline') != 'no_deadline':
        suggested_time = find_free_slot(
            user_id,
            task.get('duration', 60),
            task.get('deadline')
        )
    else:
        suggested_time = (datetime.now() + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')

    # Сохранение в БД
    cursor = db.cursor()
    cursor.execute('''
        INSERT INTO tasks 
        (user_id, title, category, deadline, duration, priority, address, items_to_bring)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id,
        task.get('title'),
        task.get('category'),
        task.get('deadline'),
        task.get('duration', 60),
        priority,
        task.get('address', ''),
        task.get('items', '')
    ))
    task_id = cursor.lastrowid
    db.commit()

    # Формирование ответа
    priority_text = {3: '🔴 Высокий', 2: '🟡 Средний', 1: '🟢 Низкий'}[priority]

    response = (
        f"✅ Задача успешно создана!\n\n"
        f"📌 Название: {task.get('title')}\n"
        f"📂 Категория: {task.get('category')}\n"
        f"🗓 Дедлайн: {task.get('deadline') if task.get('deadline') != 'no_deadline' else 'Без дедлайна'}\n"
        f"⏱ Длительность: {task.get('duration')} мин\n"
        f"⭐ Приоритет: {priority_text}\n"
        f"🕒 Рекомендуемое время: {suggested_time}"
    )

    if task.get('address'):
        response += f"\n📍 Адрес: {task.get('address')}"
    if task.get('items'):
        response += f"\n🎒 Вещи: {task.get('items')}"

    response += f"\n\nID задачи: {task_id}"

    # Очистка состояния
    state['step'] = None
    state['task_data'] = {}

    bot.send_message(message.chat.id, response, reply_markup=main_menu())


def show_active_tasks(message):
    user_id = message.from_user.id

    cursor = db.cursor()
    cursor.execute('''
        SELECT id, title, category, deadline, duration, priority, address, items_to_bring
        FROM tasks 
        WHERE user_id = ? AND status = 'active'
        ORDER BY priority DESC, deadline ASC
        LIMIT 10
    ''', (user_id,))

    tasks = cursor.fetchall()

    if not tasks:
        bot.send_message(
            message.chat.id,
            "📭 У вас нет активных задач",
            reply_markup=main_menu()
        )
        return

    response = "📋 Ваши активные задачи:\n\n"

    for task in tasks:
        task_id, title, category, deadline, duration, priority, address, items = task

        priority_emoji = {3: '🔴', 2: '🟡', 1: '🟢'}[priority]

        response += f"{priority_emoji} #{task_id} - {title}\n"
        response += f"   📂 {category} | ⏱ {duration} мин\n"

        if deadline != 'no_deadline':
            try:
                deadline_date = datetime.strptime(deadline, '%Y-%m-%d %H:%M')
                days_left = (deadline_date - datetime.now()).days
                hours_left = int((deadline_date - datetime.now()).seconds / 3600)

                if days_left < 0:
                    response += "   ⚠️ ПРОСРОЧЕНО!\n"
                elif days_left == 0:
                    response += f"   🗓 Сегодня! Осталось {hours_left} ч.\n"
                else:
                    response += f"   📅 {days_left} дн. {hours_left} ч.\n"
            except:
                pass

        if address:
            response += f"   📍 {address}\n"
        if items:
            response += f"   🎒 {items}\n"
        response += "\n"

    # Добавляем инлайн-кнопки для управления
    markup = types.InlineKeyboardMarkup(row_width=3)
    for task in tasks[:5]:
        task_id = task[0]
        markup.add(
            types.InlineKeyboardButton(f"✅ Вып. #{task_id}", callback_data=f"complete_{task_id}"),
            types.InlineKeyboardButton(f"❌ Уд. #{task_id}", callback_data=f"delete_{task_id}")
        )

    bot.send_message(message.chat.id, response, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id

    try:
        if call.data.startswith('complete_'):
            task_id = int(call.data.split('_')[1])
            complete_task(call.message, task_id, user_id)
        elif call.data.startswith('delete_'):
            task_id = int(call.data.split('_')[1])
            delete_task(call.message, task_id, user_id)

        bot.answer_callback_query(call.id, "✅ Выполнено!")
    except Exception as e:
        bot.answer_callback_query(call.id, f"❌ Ошибка: {str(e)}")


def complete_task(message, task_id, user_id):
    cursor = db.cursor()
    cursor.execute('''
        UPDATE tasks 
        SET status = 'completed' 
        WHERE id = ? AND user_id = ? AND status = 'active'
    ''', (task_id, user_id))
    db.commit()

    cursor.execute('SELECT title FROM tasks WHERE id = ?', (task_id,))
    task = cursor.fetchone()

    if task:
        bot.send_message(
            message.chat.id,
            f"✅ Задача #{task_id} '{task[0]}' выполнена! Так держать! 🎉",
            reply_markup=main_menu()
        )
    else:
        bot.send_message(message.chat.id, "❌ Задача не найдена")


def delete_task(message, task_id, user_id):
    cursor = db.cursor()
    cursor.execute('''
        DELETE FROM tasks 
        WHERE id = ? AND user_id = ? AND status = 'active'
    ''', (task_id, user_id))
    db.commit()

    bot.send_message(
        message.chat.id,
        f"🗑 Задача #{task_id} удалена",
        reply_markup=main_menu()
    )


def show_statistics(message):
    user_id = message.from_user.id

    cursor = db.cursor()

    # Общая статистика
    cursor.execute('''
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
            SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active,
            SUM(CASE WHEN status = 'overdue' THEN 1 ELSE 0 END) as overdue
        FROM tasks 
        WHERE user_id = ?
    ''', (user_id,))

    stats = cursor.fetchone()
    total, completed, active, overdue = stats

    # Статистика по категориям
    cursor.execute('''
        SELECT category, COUNT(*) 
        FROM tasks 
        WHERE user_id = ? AND status = 'active'
        GROUP BY category
    ''', (user_id,))
    categories = cursor.fetchall()

    # Статистика по приоритетам
    cursor.execute('''
        SELECT 
            SUM(CASE WHEN priority = 3 THEN 1 ELSE 0 END) as high,
            SUM(CASE WHEN priority = 2 THEN 1 ELSE 0 END) as medium,
            SUM(CASE WHEN priority = 1 THEN 1 ELSE 0 END) as low
        FROM tasks 
        WHERE user_id = ? AND status = 'active'
    ''', (user_id,))
    priorities = cursor.fetchone()

    completion_rate = (completed / total * 100) if total > 0 else 0

    response = f"📊 Ваша статистика:\n\n"
    response += f"📈 Всего задач: {total}\n"
    response += f"✅ Выполнено: {completed} ({completion_rate:.1f}%)\n"
    response += f"🔄 Активных: {active}\n"
    response += f"⚠️ Просрочено: {overdue}\n\n"

    response += "📂 По категориям:\n"
    for cat, count in categories:
        response += f"   • {cat}: {count}\n"

    response += f"\n⭐ По приоритетам:\n"
    response += f"   🔴 Высокий: {priorities[0] or 0}\n"
    response += f"   🟡 Средний: {priorities[1] or 0}\n"
    response += f"   🟢 Низкий: {priorities[2] or 0}\n"

    bot.send_message(message.chat.id, response, reply_markup=main_menu())


def show_completed_tasks(message):
    user_id = message.from_user.id

    cursor = db.cursor()
    cursor.execute('''
        SELECT title, category, deadline, created_at
        FROM tasks 
        WHERE user_id = ? AND status = 'completed'
        ORDER BY created_at DESC
        LIMIT 10
    ''', (user_id,))

    tasks = cursor.fetchall()

    if not tasks:
        bot.send_message(
            message.chat.id,
            "📭 Нет выполненных задач",
            reply_markup=main_menu()
        )
        return

    response = "✅ Последние выполненные задачи:\n\n"

    for title, category, deadline, completed_at in tasks:
        response += f"✅ {title}\n"
        response += f"   📂 {category}\n"
        if deadline != 'no_deadline':
            response += f"   📅 Дедлайн: {deadline}\n"
        response += f"   ✔️ Создано: {completed_at}\n\n"

    bot.send_message(message.chat.id, response, reply_markup=main_menu())


def show_help(message):
    help_text = (
        "🤖 *Помощь по использованию бота*\n\n"
        "*Основные команды:*\n"
        "➕ Новая задача — создать задачу\n"
        "📋 Мои задачи — список активных задач\n"
        "📊 Статистика — ваша продуктивность\n"
        "✅ Выполненные — история\n\n"
        "*Возможности:*\n"
        "• Автоприоритет на основе дедлайна\n"
        "• Умный подбор времени\n"
        "• Напоминания о вещах\n"
        "• Оценка длительности\n\n"
        "*Приоритеты:*\n"
        "🔴 Высокий — срочно!\n"
        "🟡 Средний — важно\n"
        "🟢 Низкий — можно отложить"
    )

    bot.send_message(
        message.chat.id,
        help_text,
        parse_mode='Markdown',
        reply_markup=main_menu()
    )


def cancel_operation(message):
    user_id = message.from_user.id
    state = get_user_state(user_id)
    state['step'] = None
    state['task_data'] = {}

    bot.send_message(
        message.chat.id,
        "❌ Операция отменена",
        reply_markup=main_menu()
    )


# Система напоминаний
def check_reminders():
    try:
        cursor = db.cursor()
        current_time = datetime.now()

        # Проверяем активные задачи с дедлайнами
        cursor.execute('''
            SELECT id, user_id, title, deadline, address, items_to_bring, duration
            FROM tasks 
            WHERE status = 'active' AND deadline != 'no_deadline'
        ''')

        tasks = cursor.fetchall()

        for task in tasks:
            task_id, user_id, title, deadline, address, items, duration = task

            try:
                deadline_date = datetime.strptime(deadline, '%Y-%m-%d %H:%M')

                # Проверка на просрочку
                if deadline_date < current_time:
                    cursor.execute('''
                        UPDATE tasks SET status = 'overdue' WHERE id = ?
                    ''', (task_id,))
                    db.commit()

                    try:
                        bot.send_message(
                            user_id,
                            f"⚠️ Задача просрочена!\n\n📌 {title}\n📅 {deadline}"
                        )
                    except:
                        pass
                    continue

                # Напоминания
                time_diff = deadline_date - current_time
                minutes_left = time_diff.total_seconds() / 60

                # Напоминание за 1 час
                if 58 <= minutes_left <= 62:
                    reminder = f"🗓 Напоминание!\n\n📌 {title}\n⏱ Через 1 час"
                    if address:
                        reminder += f"\n📍 Адрес: {address}"
                    if items:
                        reminder += f"\n🎒 Не забудьте: {items}"

                    try:
                        bot.send_message(user_id, reminder)
                    except:
                        pass

                # Напоминание за 30 минут
                elif 28 <= minutes_left <= 32:
                    reminder = f"🗓 Срочно!\n\n📌 {title}\n⏱ Через 30 минут"
                    if address:
                        reminder += f"\n📍 Адрес: {address}"
                    if items:
                        reminder += f"\n🎒 Возьмите: {items}"

                    try:
                        bot.send_message(user_id, reminder)
                    except:
                        pass

            except Exception as e:
                print(f"Error processing task {task_id}: {e}")

    except Exception as e:
        print(f"Error in check_reminders: {e}")


# Планировщик для напоминаний
def run_scheduler():
    schedule.every(1).minutes.do(check_reminders)

    while True:
        schedule.run_pending()
        time.sleep(30)


# Запуск бота
if __name__ == '__main__':
    print("🤖 Бот-планер запущен!")

    # Запуск планировщика в фоне
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    # Бесконечный цикл с обработкой ошибок
    while True:
        try:
            bot.polling(none_stop=True, interval=0)
        except Exception as e:
            print(f"Ошибка: {e}")
            time.sleep(15)
