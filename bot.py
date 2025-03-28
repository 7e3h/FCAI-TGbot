import os
import logging
import requests
import json
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, PicklePersistence
import pandas as pd
from openpyxl import Workbook
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Store user states and data
user_states = {}
user_data = {}
# Store temporary file data
file_data = {}
# Store session data
sessions = {}

# Books and Summaries directory structure
BOOKS_DIR = "study_materials"
SUMMARIES_DIR = "study_summaries"
PLAYLISTS_DIR = "study_playlists"
os.makedirs(BOOKS_DIR, exist_ok=True)
os.makedirs(SUMMARIES_DIR, exist_ok=True)
os.makedirs(PLAYLISTS_DIR, exist_ok=True)
for year in range(1, 5):
    year_dir = os.path.join(BOOKS_DIR, f"year_{year}")
    summary_dir = os.path.join(SUMMARIES_DIR, f"year_{year}")
    playlist_dir = os.path.join(PLAYLISTS_DIR, f"year_{year}")
    os.makedirs(year_dir, exist_ok=True)
    os.makedirs(summary_dir, exist_ok=True)
    os.makedirs(playlist_dir, exist_ok=True)

# API endpoints
BASE_URL = "https://fcai.deltateach.com"
LOGIN_URL = f"{BASE_URL}/Account/Login"
STUDENT_INFO_URL = f"{BASE_URL}/Student/Index"

# Create a session to maintain cookies and tokens
session = requests.Session()

# Store playlist links
PLAYLIST_LINKS = {}

# Admin password
ADMIN_PASSWORD = "159753FCAI@"

def save_playlist_links():
    try:
        with open('playlist_links.json', 'w', encoding='utf-8') as f:
            json.dump(PLAYLIST_LINKS, f, ensure_ascii=False, indent=4)
        logger.info("Playlist links saved successfully")
    except Exception as e:
        logger.error(f"Error saving playlist links: {str(e)}")

def load_playlist_links():
    global PLAYLIST_LINKS
    try:
        with open('playlist_links.json', 'r', encoding='utf-8') as f:
            PLAYLIST_LINKS = json.load(f)
            logger.info(f"Playlist links loaded successfully: {PLAYLIST_LINKS}")
    except FileNotFoundError:
        logger.info("No playlist links file found, creating empty file")
        PLAYLIST_LINKS = {'year_1': {}}
        save_playlist_links()
    except Exception as e:
        logger.error(f"Error loading playlist links: {str(e)}")
        PLAYLIST_LINKS = {'year_1': {}}
        save_playlist_links()

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_info=None):
    if not user_info:
        keyboard = [
            [InlineKeyboardButton("Student", callback_data='student')]
        ]
        message = "Welcome! Please select your role:"
    else:
        keyboard = [
            [InlineKeyboardButton("Download Books", callback_data='download_books')],
            [InlineKeyboardButton("Download Summaries", callback_data='download_summaries')],
            [InlineKeyboardButton("Study Playlists", callback_data='study_playlists')],
            [InlineKeyboardButton("تسجيل خروج", callback_data='logout')]
        ]
        message = f"Welcome {user_info['name']}\nYour email: {user_info['email']}\nStudy group: {user_info['study_group']}"
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.message.edit_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in sessions:
        # User already logged in, show main menu with their info
        await show_main_menu(update, context, sessions[user_id])
    else:
        # New user, show login option
        await show_main_menu(update, context)

async def handle_download_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("الفرقة الأولى", callback_data='year_1')],
        [InlineKeyboardButton("رجوع", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text("اختر الفرقة الدراسية للكتب:", reply_markup=reply_markup)

async def handle_download_summaries(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("الفرقة الأولى", callback_data='year_1')],
        [InlineKeyboardButton("رجوع", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text("اختر الفرقة الدراسية للملخصات:", reply_markup=reply_markup)

async def handle_study_playlists(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("الفرقة الأولى", callback_data='year_1')],
        [InlineKeyboardButton("رجوع", callback_data='back_to_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text("اختر الفرقة الدراسية للفيديوهات:", reply_markup=reply_markup)

async def show_year_materials(update: Update, context: ContextTypes.DEFAULT_TYPE, year: str, is_book: bool = True):
    query = update.callback_query
    user_id = query.from_user.id
    
    base_dir = BOOKS_DIR if is_book else SUMMARIES_DIR
    year_dir = os.path.join(base_dir, f"year_{year}")
    
    # Store the current directory and type in context
    context.user_data['current_dir'] = year_dir
    context.user_data['is_book'] = is_book
    context.user_data['year'] = year
    context.user_data['dir_stack'] = [year_dir]  # Initialize directory stack
    
    if os.path.exists(year_dir):
        # Get list of items in the year directory
        items = os.listdir(year_dir)
        
        if items:
            keyboard = []
            for idx, item in enumerate(items, 1):
                item_path = os.path.join(year_dir, item)
                if os.path.isdir(item_path):
                    keyboard.append([InlineKeyboardButton(
                        f"📁 {item}",
                        callback_data=f"d{idx}"  # d for directory
                    )])
                else:
                    # Remove file extension for display
                    display_name = os.path.splitext(item)[0]
                    keyboard.append([InlineKeyboardButton(
                        f"📄 {display_name}",
                        callback_data=f"f{idx}"  # f for file
                    )])
            
            # Store paths in context
            context.user_data['paths'] = {f"d{idx}": os.path.join(year_dir, item) 
                                        for idx, item in enumerate(items, 1) 
                                        if os.path.isdir(os.path.join(year_dir, item))}
            context.user_data['paths'].update({f"f{idx}": os.path.join(year_dir, item) 
                                             for idx, item in enumerate(items, 1) 
                                             if os.path.isfile(os.path.join(year_dir, item))})
            
            # Add back button
            keyboard.append([InlineKeyboardButton("رجوع", callback_data='back_to_menu')])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text("اختر الملف أو المجلد الذي تريد تحميله:", reply_markup=reply_markup)
        else:
            keyboard = [[InlineKeyboardButton("رجوع", callback_data='back_to_menu')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text("لا توجد ملفات أو مجلدات متاحة لهذه الفرقة حالياً.", reply_markup=reply_markup)
    else:
        keyboard = [[InlineKeyboardButton("رجوع", callback_data='back_to_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("عذراً، محتوى هذه الفرقة غير متوفر حالياً.", reply_markup=reply_markup)

async def show_playlist_links(update: Update, context: ContextTypes.DEFAULT_TYPE, year: str):
    query = update.callback_query
    await query.answer()
    
    try:
        # Read directly from JSON file
        with open('playlist_links.json', 'r', encoding='utf-8') as f:
            playlist_data = json.load(f)
            
        year_key = f'year_{year}'
        if year_key in playlist_data:
            message = f"روابط الفيديوهات للفرقة {year}:\n\n"
            for subject, link in playlist_data[year_key].items():
                message += f"📚 {subject}:\n{link}\n\n"
            
            keyboard = [[InlineKeyboardButton("رجوع", callback_data='study_playlists')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(message, reply_markup=reply_markup)
        else:
            keyboard = [[InlineKeyboardButton("رجوع", callback_data='study_playlists')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text("عذراً، محتوى هذه الفرقة غير متوفر حالياً.", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error reading playlist links: {str(e)}")
        keyboard = [[InlineKeyboardButton("رجوع", callback_data='study_playlists')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text("عذراً، حدث خطأ أثناء قراءة الروابط. يرجى المحاولة مرة أخرى.", reply_markup=reply_markup)

async def handle_logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id in sessions:
        # Clear user session
        del sessions[user_id]
        # Clear any temporary file data
        if user_id in file_data:
            del file_data[user_id]
        # Clear user state
        if user_id in user_states:
            del user_states[user_id]
    
    # Show login menu
    keyboard = [
        [InlineKeyboardButton("Student", callback_data='student')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text("تم تسجيل الخروج بنجاح. يمكنك تسجيل الدخول مرة أخرى:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    logger.info(f"Button pressed: {query.data} by user {user_id}")
    logger.info(f"Current user state: {user_states.get(user_id)}")
    
    if query.data == 'student':
        if user_id in sessions:
            # User already logged in
            await show_main_menu(update, context, sessions[user_id])
        else:
            await query.message.edit_text(
                "Please enter your email and password in the format:\nemail:password"
            )
            user_states[user_id] = 'waiting_student_credentials'
    
    elif query.data == 'logout':
        await handle_logout(update, context)
    
    elif query.data == 'back_to_menu':
        if user_id in sessions:
            await show_main_menu(update, context, sessions[user_id])
        else:
            await show_main_menu(update, context)
    
    elif query.data == 'back_to_years':
        # Determine which menu to show based on the current message
        current_text = query.message.text
        if "للكتب" in current_text:
            await handle_download_books(update, context)
        elif "للملخصات" in current_text:
            await handle_download_summaries(update, context)
        else:
            await handle_study_playlists(update, context)
    
    elif query.data == 'download_books':
        await handle_download_books(update, context)
    
    elif query.data == 'download_summaries':
        await handle_download_summaries(update, context)
    
    elif query.data == 'study_playlists':
        await handle_study_playlists(update, context)
    
    elif query.data.startswith('year_'):
        year = query.data.split('_')[1]
        if query.message.text.startswith("اختر الفرقة الدراسية للكتب"):
            await show_year_materials(update, context, year, is_book=True)
        elif query.message.text.startswith("اختر الفرقة الدراسية للملخصات"):
            await show_year_materials(update, context, year, is_book=False)
        else:
            await show_playlist_links(update, context, year)
    
    elif query.data.startswith('d'):  # Directory
        path = context.user_data.get('paths', {}).get(query.data)
        if path and os.path.exists(path):
            items = os.listdir(path)
            if items:
                keyboard = []
                for idx, item in enumerate(items, 1):
                    item_path = os.path.join(path, item)
                    if os.path.isdir(item_path):
                        keyboard.append([InlineKeyboardButton(
                            f"📁 {item}",
                            callback_data=f"d{idx}"
                        )])
                    else:
                        # Remove file extension for display
                        display_name = os.path.splitext(item)[0]
                        keyboard.append([InlineKeyboardButton(
                            f"📄 {display_name}",
                            callback_data=f"f{idx}"
                        )])
                
                # Store paths in context
                context.user_data['paths'] = {f"d{idx}": os.path.join(path, item) 
                                            for idx, item in enumerate(items, 1) 
                                            if os.path.isdir(os.path.join(path, item))}
                context.user_data['paths'].update({f"f{idx}": os.path.join(path, item) 
                                                 for idx, item in enumerate(items, 1) 
                                                 if os.path.isfile(os.path.join(path, item))})
                
                # Update directory stack
                dir_stack = context.user_data.get('dir_stack', [])
                dir_stack.append(path)
                context.user_data['dir_stack'] = dir_stack
                context.user_data['current_dir'] = path
                
                # Add back button
                keyboard.append([InlineKeyboardButton("رجوع", callback_data='back_to_parent')])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.edit_text(f"اختر الملف أو المجلد من {os.path.basename(path)}:", reply_markup=reply_markup)
            else:
                keyboard = [[InlineKeyboardButton("رجوع", callback_data='back_to_parent')]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.edit_text("لا توجد ملفات أو مجلدات في هذا المجلد حالياً.", reply_markup=reply_markup)
        else:
            keyboard = [[InlineKeyboardButton("رجوع", callback_data='back_to_parent')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text("عذراً، هذا المجلد غير متوفر حالياً.", reply_markup=reply_markup)
    
    elif query.data == 'back_to_parent':
        dir_stack = context.user_data.get('dir_stack', [])
        if len(dir_stack) > 1:
            # Remove current directory from stack
            dir_stack.pop()
            # Get parent directory
            parent_dir = dir_stack[-1]
            context.user_data['dir_stack'] = dir_stack
            context.user_data['current_dir'] = parent_dir
            
            # Show contents of parent directory
            items = os.listdir(parent_dir)
            if items:
                keyboard = []
                for idx, item in enumerate(items, 1):
                    item_path = os.path.join(parent_dir, item)
                    if os.path.isdir(item_path):
                        keyboard.append([InlineKeyboardButton(
                            f"📁 {item}",
                            callback_data=f"d{idx}"
                        )])
                    else:
                        # Remove file extension for display
                        display_name = os.path.splitext(item)[0]
                        keyboard.append([InlineKeyboardButton(
                            f"📄 {display_name}",
                            callback_data=f"f{idx}"
                        )])
                
                # Store paths in context
                context.user_data['paths'] = {f"d{idx}": os.path.join(parent_dir, item) 
                                            for idx, item in enumerate(items, 1) 
                                            if os.path.isdir(os.path.join(parent_dir, item))}
                context.user_data['paths'].update({f"f{idx}": os.path.join(parent_dir, item) 
                                                 for idx, item in enumerate(items, 1) 
                                                 if os.path.isfile(os.path.join(parent_dir, item))})
                
                # Add back button
                if len(dir_stack) == 1:  # If we're back at the year directory
                    keyboard.append([InlineKeyboardButton("رجوع", callback_data='back_to_menu')])
                else:
                    keyboard.append([InlineKeyboardButton("رجوع", callback_data='back_to_parent')])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.edit_text("اختر الملف أو المجلد الذي تريد تحميله:", reply_markup=reply_markup)
            else:
                keyboard = [[InlineKeyboardButton("رجوع", callback_data='back_to_menu')]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.edit_text("لا توجد ملفات أو مجلدات متاحة حالياً.", reply_markup=reply_markup)
    
    elif query.data.startswith('f'):  # File
        path = context.user_data.get('paths', {}).get(query.data)
        try:
            if path and os.path.exists(path):
                await query.message.reply_document(
                    document=open(path, 'rb'),
                    filename=os.path.basename(path)
                )
            else:
                await query.message.edit_text(
                    "عذراً، الملف غير متوفر حالياً.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("رجوع", callback_data='back_to_menu')]])
                )
        except Exception as e:
            logger.error(f"Error sending file: {str(e)}")
            await query.message.edit_text(
                "حدث خطأ أثناء إرسال الملف. يرجى المحاولة مرة أخرى.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("رجوع", callback_data='back_to_menu')]])
            )

async def handle_student_credentials(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        email, password = update.message.text.split(':')
        user_id = update.effective_user.id
        
        # Get login token first
        token = await get_login_token()
        if not token:
            await update.message.reply_text("Failed to initialize login. Please try again.")
            return
        
        # Prepare login data with correct format
        login_data = {
            "Email": email,
            "Password": password,
            "__RequestVerificationToken": token,
            "RememberMe": "false"
        }
        
        # Set headers
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': LOGIN_URL,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Origin': BASE_URL,
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        # Perform login
        response = session.post(LOGIN_URL, data=login_data, headers=headers, allow_redirects=True)
        
        if response.status_code == 200 and "Invalid login attempt" not in response.text:
            # Get student information
            student_info_response = session.get(STUDENT_INFO_URL)
            if student_info_response.status_code == 200:
                # Parse student info from the response
                soup = BeautifulSoup(student_info_response.text, 'html.parser')
                
                # Log the HTML content for debugging
                logger.info(f"Student info page content: {student_info_response.text[:500]}...")
                
                # Extract student information
                student_info = {}
                
                # Find all tables in the page
                tables = soup.find_all('table')
                for table in tables:
                    rows = table.find_all('tr')
                    for row in rows:
                        cols = row.find_all(['td', 'th'])
                        if len(cols) >= 2:
                            label = cols[0].text.strip()
                            value = cols[1].text.strip()
                            
                            # Map Arabic labels to English keys
                            if 'الاسم' in label or 'اسم الطالب' in label:
                                student_info['name'] = value
                            elif 'الرقم القومي' in label:
                                student_info['national_id'] = value
                            elif 'الموبايل' in label or 'رقم الهاتف' in label:
                                student_info['mobile'] = value
                            elif 'الايميل' in label or 'البريد الإلكتروني' in label:
                                student_info['email'] = value
                            elif 'الفرقة' in label or 'المستوى' in label or 'البرنامج' in label:
                                student_info['study_group'] = value
                
                # If we couldn't find the information in tables, try alternative methods
                if not student_info.get('name'):
                    # Try to find name in any element containing the email
                    for element in soup.find_all(text=lambda t: email in str(t)):
                        student_info['name'] = element.find_parent().text.strip()
                        break
                
                if not student_info.get('study_group'):
                    # Try to find study group in any element containing "المستوى" or "برنامج"
                    for element in soup.find_all(text=lambda t: 'المستوى' in str(t) or 'برنامج' in str(t)):
                        student_info['study_group'] = element.find_parent().text.strip()
                        break
                
                # Set default values if information is missing
                student_info['name'] = student_info.get('name', "Student")
                student_info['study_group'] = student_info.get('study_group', "Not specified")
                
                # Store session data
                sessions[user_id] = {
                    'name': student_info['name'],
                    'email': email,
                    'study_group': student_info['study_group'],
                    'telegram_username': update.effective_user.username,
                    'national_id': student_info.get('national_id', ''),
                    'mobile': student_info.get('mobile', '')
                }
                
                # Save to Excel
                save_to_excel(sessions[user_id])
                
                # Show main menu
                await show_main_menu(update, context, sessions[user_id])
                
                user_states[user_id] = 'student_menu'
            else:
                logger.error(f"Failed to get student info. Status code: {student_info_response.status_code}")
                await update.message.reply_text("Failed to fetch student information. Please try again.")
        else:
            logger.error(f"Login failed. Response: {response.text[:200]}...")
            await update.message.reply_text("Invalid credentials. Please try again.")
            
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        await update.message.reply_text("An error occurred. Please try again.")

async def get_login_token():
    try:
        response = session.get(LOGIN_URL)
        if response.status_code == 200:
            # Extract token from the response HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            token = soup.find('input', {'name': '__RequestVerificationToken'})['value']
            return token
    except Exception as e:
        logger.error(f"Error getting login token: {e}")
    return None

def save_to_excel(user_data):
    try:
        df = pd.read_excel('users.xlsx')
    except FileNotFoundError:
        df = pd.DataFrame(columns=['Telegram Username', 'Name', 'Email', 'Study Group', 'National ID', 'Mobile', 'Timestamp'])
    
    new_row = pd.DataFrame([{
        'Telegram Username': user_data['telegram_username'],
        'Name': user_data['name'],
        'Email': user_data['email'],
        'Study Group': user_data['study_group'],
        'National ID': user_data.get('national_id', ''),
        'Mobile': user_data.get('mobile', ''),
        'Timestamp': datetime.now()
    }])
    
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_excel('users.xlsx', index=False)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id in user_states:
        if user_states[user_id] == 'waiting_student_credentials':
            await handle_student_credentials(update, context)

def main():
    # Load playlist links at startup
    load_playlist_links()
    
    application = Application.builder().token('').persistence(PicklePersistence(filepath='bot_persistence')).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    application.run_polling()

if __name__ == '__main__':
    main() 
