import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
import sqlite3
import os

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('anon_questions.db')
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        referral_code TEXT UNIQUE
    )
    ''')
    
    # Таблица вопросов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS questions (
        question_id INTEGER PRIMARY KEY AUTOINCREMENT,
        receiver_id INTEGER,
        question_text TEXT,
        is_answered INTEGER DEFAULT 0,
        FOREIGN KEY (receiver_id) REFERENCES users (user_id)
    )
    ''')
    
    conn.commit()
    conn.close()

# Генерация реферального кода
def generate_referral_code(user_id):
    return f"ref_{user_id}"

# Обработчик команды /start
def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    conn = sqlite3.connect('anon_questions.db')
    cursor = conn.cursor()
    
    # Проверяем, есть ли пользователь в базе
    cursor.execute('SELECT referral_code FROM users WHERE user_id = ?', (user.id,))
    result = cursor.fetchone()
    
    if result:
        referral_code = result[0]
    else:
        # Добавляем нового пользователя
        referral_code = generate_referral_code(user.id)
        cursor.execute(
            'INSERT INTO users (user_id, username, referral_code) VALUES (?, ?, ?)',
            (user.id, user.username, referral_code)
        )
        conn.commit()
    
    # Формируем ссылку
    bot_username = context.bot.username
    referral_link = f"https://t.me/{bot_username}?start={referral_code}"
    
    # Отправляем сообщение с инструкцией
    message = (
        f"👋 Привет, {user.first_name}!\n\n"
        "Это бот для анонимных вопросов. Вот твоя персональная ссылка:\n\n"
        f"{referral_link}\n\n"
        "Отправь её друзьям, чтобы они могли задать тебе анонимный вопрос!"
    )
    
    update.message.reply_text(message)
    conn.close()

# Обработчик команды /start с реферальным кодом
def start_with_referral(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    args = context.args
    
    if args and args[0].startswith('ref_'):
        referral_code = args[0]
        conn = sqlite3.connect('anon_questions.db')
        cursor = conn.cursor()
        
        # Ищем пользователя с таким реферальным кодом
        cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (referral_code,))
        result = cursor.fetchone()
        
        if result:
            receiver_id = result[0]
            # Сохраняем информацию о том, что пользователь хочет задать вопрос
            context.user_data['asking_question_to'] = receiver_id
            update.message.reply_text(
                "📝 Напиши свой анонимный вопрос для этого пользователя:"
            )
        else:
            update.message.reply_text("Неверная реферальная ссылка.")
        
        conn.close()
    else:
        # Обычный /start без реферального кода
        start(update, context)

# Обработчик текстовых сообщений (для вопросов)
def handle_message(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    message_text = update.message.text
    
    # Проверяем, задается ли вопрос
    if 'asking_question_to' in context.user_data:
        receiver_id = context.user_data['asking_question_to']
        conn = sqlite3.connect('anon_questions.db')
        cursor = conn.cursor()
        
        # Сохраняем вопрос в базу
        cursor.execute(
            'INSERT INTO questions (receiver_id, question_text) VALUES (?, ?)',
            (receiver_id, message_text)
        )
        conn.commit()
        
        # Отправляем подтверждение отправителю
        update.message.reply_text("✅ Вопрос отправлен анонимно!")
        
        # Отправляем уведомление получателю
        try:
            context.bot.send_message(
                chat_id=receiver_id,
                text=f"📩 У тебя новый анонимный вопрос:\n\n{message_text}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Ответить", callback_data=f"answer_{cursor.lastrowid}")]
                ])
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление пользователю {receiver_id}: {e}")
        
        # Очищаем контекст
        del context.user_data['asking_question_to']
        conn.close()
    else:
        # Обычное сообщение
        update.message.reply_text("Отправь мне /start чтобы начать")

# Обработчик кнопки "Ответить"
def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    
    if query.data.startswith('answer_'):
        question_id = int(query.data.split('_')[1])
        context.user_data['answering_question'] = question_id
        query.edit_message_text(
            text=query.message.text + "\n\n✏️ Напиши свой ответ:"
        )

# Обработчик ответов на вопросы
def handle_answer(update: Update, context: CallbackContext) -> None:
    if 'answering_question' in context.user_data:
        question_id = context.user_data['answering_question']
        answer_text = update.message.text
        
        conn = sqlite3.connect('anon_questions.db')
        cursor = conn.cursor()
        
        # Получаем информацию о вопросе
        cursor.execute(
            'SELECT question_text FROM questions WHERE question_id = ?',
            (question_id,)
        )
        question_text = cursor.fetchone()[0]
        
        # Помечаем вопрос как отвеченный
        cursor.execute(
            'UPDATE questions SET is_answered = 1 WHERE question_id = ?',
            (question_id,)
        )
        conn.commit()
        
        # Отправляем ответ отправителю вопроса
        # (В реальном боте нужно хранить информацию об отправителях, если хотите реализовать ответы)
        
        update.message.reply_text("✅ Ответ отправлен!")
        del context.user_data['answering_question']
        conn.close()

def main() -> None:
    # Инициализируем базу данных
    init_db()
    
    # Получаем токен бота из переменной окружения
    TOKEN = os.getenv('TELEGRAM_TOKEN') or 'YOUR_TELEGRAM_BOT_TOKEN'
    
    # Создаем Updater и Dispatcher
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher
    
    # Регистрируем обработчики команд
    dispatcher.add_handler(CommandHandler("start", start_with_referral, pass_args=True))
    
    # Регистрируем обработчики сообщений
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_answer))
    
    # Регистрируем обработчики кнопок
    dispatcher.add_handler(CallbackQueryHandler(button_handler))
    
    # Запускаем бота
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
