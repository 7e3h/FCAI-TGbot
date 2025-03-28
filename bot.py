import os
import logging
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
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

# Books and Summaries directory structure
BOOKS_DIR = "study_materials"
SUMMARIES_DIR = "study_summaries"
os.makedirs(BOOKS_DIR, exist_ok=True)
os.makedirs(SUMMARIES_DIR, exist_ok=True)
for year in range(1, 5):
    year_dir = os.path.join(BOOKS_DIR, f"year_{year}")
    summary_dir = os.path.join(SUMMARIES_DIR, f"year_{year}")
    os.makedirs(year_dir, exist_ok=True)
    os.makedirs(summary_dir, exist_ok=True)

# API endpoints
BASE_URL = "https://fcai.deltateach.com"
LOGIN_URL = f"{BASE_URL}/Account/Login"
STUDENT_INFO_URL = f"{BASE_URL}/Student/Index"

# Create a session to maintain cookies and tokens
session = requests.Session()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Student", callback_data='student')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Welcome! Please select your role:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'student':
        await query.message.reply_text(
            "Please enter your email and password in the format:\nemail:password"
        )
        user_states[query.from_user.id] = 'waiting_student_credentials'
    
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
        else:
            await show_year_materials(update, context, year, is_book=False)
    
    elif query.data.startswith('file_'):
        # Extract file ID from callback_data
        file_id = query.data.split('_')[1]
        user_id = query.from_user.id
        
        if user_id in file_data and file_id in file_data[user_id]:
            file_info = file_data[user_id][file_id]
            base_dir = BOOKS_DIR if file_info.get('is_book', True) else SUMMARIES_DIR
            file_path = os.path.join(base_dir, f"year_{file_info['year']}", file_info['filename'])
            
            try:
                if os.path.exists(file_path):
                    # Send the file to the user
                    await query.message.reply_document(
                        document=open(file_path, 'rb'),
                        filename=file_info['filename']
                    )
                else:
                    await query.message.reply_text("عذراً، الملف غير متوفر حالياً.")
            except Exception as e:
                logger.error(f"Error sending file: {str(e)}")
                await query.message.reply_text("حدث خطأ أثناء إرسال الملف. يرجى المحاولة مرة أخرى.")
        else:
            await query.message.reply_text("عذراً، انتهت صلاحية الطلب. يرجى المحاولة مرة أخرى.")

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

async def handle_student_credentials(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        email, password = update.message.text.split(':')
        
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
        
        # Check if login was successful by looking for specific indicators in the response
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
                
                # Store user data
                user_data[update.effective_user.id] = {
                    'name': student_info['name'],
                    'email': email,
                    'study_group': student_info['study_group'],
                    'telegram_username': update.effective_user.username,
                    'national_id': student_info.get('national_id', ''),
                    'mobile': student_info.get('mobile', '')
                }
                
                # Save to Excel
                save_to_excel(user_data[update.effective_user.id])
                
                # Show welcome message with all buttons
                keyboard = [
                    [InlineKeyboardButton("Download Books", callback_data='download_books')],
                    [InlineKeyboardButton("Download Summaries", callback_data='download_summaries')],
                    [InlineKeyboardButton("Study Playlists", callback_data='study_playlists')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                welcome_message = f"Welcome {student_info['name']}\nYour email: {email}\nStudy group: {student_info['study_group']}"
                await update.message.reply_text(welcome_message, reply_markup=reply_markup)
                
                user_states[update.effective_user.id] = 'student_menu'
            else:
                logger.error(f"Failed to get student info. Status code: {student_info_response.status_code}")
                await update.message.reply_text("Failed to fetch student information. Please try again.")
        else:
            logger.error(f"Login failed. Response: {response.text[:200]}...")
            await update.message.reply_text("Invalid credentials. Please try again.")
            
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        await update.message.reply_text("An error occurred. Please try again.")

async def handle_download_books(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("الفرقة الأولى", callback_data='year_1')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("اختر الفرقة الدراسية للكتب:", reply_markup=reply_markup)

async def handle_download_summaries(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("الفرقة الأولى", callback_data='year_1')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("اختر الفرقة الدراسية للملخصات:", reply_markup=reply_markup)

async def handle_study_playlists(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("الفرقة الأولى", callback_data='year_1')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("اختر الفرقة الدراسية للفيديوهات:", reply_markup=reply_markup)

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

async def show_year_materials(update: Update, context: ContextTypes.DEFAULT_TYPE, year: str, is_book: bool = True):
    query = update.callback_query
    user_id = query.from_user.id
    
    base_dir = BOOKS_DIR if is_book else SUMMARIES_DIR
    year_dir = os.path.join(base_dir, f"year_{year}")
    if os.path.exists(year_dir):
        # Get list of files in the year directory
        files = [f for f in os.listdir(year_dir) if os.path.isfile(os.path.join(year_dir, f))]
        
        if files:
            # Initialize file data for this user
            if user_id not in file_data:
                file_data[user_id] = {}
            
            keyboard = []
            for idx, filename in enumerate(files, 1):
                # Store file info with a short ID
                file_id = str(idx)
                file_data[user_id][file_id] = {
                    'filename': filename,
                    'year': year,
                    'is_book': is_book
                }
                
                # Remove file extension for display
                display_name = os.path.splitext(filename)[0]
                keyboard.append([InlineKeyboardButton(
                    display_name,
                    callback_data=f'file_{file_id}'  # Using short ID in callback_data
                )])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("اختر الملف الذي تريد تحميله:", reply_markup=reply_markup)
        else:
            await query.message.reply_text("لا توجد ملفات متاحة لهذه الفرقة حالياً.")
    else:
        await query.message.reply_text("عذراً، محتوى هذه الفرقة غير متوفر حالياً.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id in user_states:
        if user_states[user_id] == 'waiting_student_credentials':
            await handle_student_credentials(update, context)

def main():
    application = Application.builder().token('7578113791:AAHMIehOLXZ-LQiOiLEGNmljYVs0Ywktbxs').build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    application.run_polling()

if __name__ == '__main__':
    main() 