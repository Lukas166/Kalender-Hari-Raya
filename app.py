import os
import json
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import smtplib
from email.mime.text import MIMEText
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import streamlit as st
import pandas as pd
from threading import Thread
import calendar
from dotenv import load_dotenv
from email.mime.multipart import MIMEMultipart

# Try to load from .env.production first, then fall back to .env
if os.path.exists('.env.production'):
    load_dotenv('.env.production')
    logging.info("Loaded environment variables from .env.production")
else:
    load_dotenv()
    logging.info("Loaded environment variables from .env")

# Initialize logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
CONFIG = {
    'email_sender': os.getenv('EMAIL_SENDER', 'your_email@gmail.com'),
    'email_password': os.getenv('EMAIL_PASSWORD', 'your_app_password'),
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'default_receivers': ['team@company.com'],
    'holiday_api': 'https://api-harilibur.vercel.app/api',
    'timezone': 'Asia/Jakarta'
}

# Initialize Flask app
flask_app = Flask(__name__)
scheduler = BackgroundScheduler(timezone=CONFIG['timezone'])

# Data storage
class DataStore:
    def __init__(self):
        self.receivers = CONFIG['default_receivers']
        self.holidays = []
        self.load_data()
    
    def load_data(self):
        try:
            with open('data.json', 'r') as f:
                data = json.load(f)
                self.receivers = data.get('receivers', CONFIG['default_receivers'])
                self.holidays = data.get('holidays', [])
        except (FileNotFoundError, json.JSONDecodeError):
            self.save_data()
    
    def save_data(self):
        with open('data.json', 'w') as f:
            json.dump({
                'receivers': self.receivers,
                'holidays': self.holidays
            }, f)

data_store = DataStore()

# Holiday API Functions
def fetch_holidays(year=None):
    try:
        year = year or datetime.now().year
        response = requests.get(f"{CONFIG['holiday_api']}?year={year}")
        response.raise_for_status()
        
        # Process data from API (reverse order as per requirement)
        holidays_data = response.json()[::-1]  # Reverse the list to process from bottom
        
        processed_holidays = []
        for holiday in holidays_data:
            if holiday.get('is_national_holiday', False):
                processed_holidays.append({
                    'holiday_name': holiday['holiday_name'],
                    'holiday_date': holiday['holiday_date'],
                    'holiday_description': holiday.get('holiday_description', '')
                })

        # Sort by date (ascending)
        processed_holidays.sort(
            key=lambda x: datetime.strptime(x['holiday_date'], '%Y-%m-%d')
        )

        return processed_holidays
    except Exception as e:
        logger.error(f"Error fetching holidays: {e}")
        return []   

def update_holidays():
    try:
        current_year = datetime.now().year
        data_store.holidays = fetch_holidays(current_year) + fetch_holidays(current_year + 1)
        data_store.save_data()
        logger.info("Updated holiday data")
        return True
    except Exception as e:
        logger.error(f"Error updating holidays: {e}")
        return False

def send_notification(holidays, receivers=None):
    """
    Enhanced email notification function with:
    - Better HTML formatting
    - Proper email headers
    - Error handling
    - Anti-spam measures
    """
    if not holidays:
        logger.warning("No holidays to send notifications for")
        return False
    
    receivers = receivers or data_store.receivers
    if not receivers:
        logger.error("No receivers specified")
        return False
    
    try:
        today = datetime.now().date()
        
        # Create email content
        subject = "📅 Informasi Hari Libur Nasional Mendatang"
        
        # HTML Content
        html = f"""<html>
<head>
<style>
  body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
  .header {{ color: #2c3e50; border-bottom: 1px solid #eee; padding-bottom: 10px; }}
  .holiday-list {{ margin: 15px 0; }}
  .holiday-item {{ margin: 10px 0; padding: 10px; background: #f9f9f9; border-radius: 5px; }}
  .holiday-name {{ font-weight: bold; color: white; }}
  .holiday-date {{ color: #555; }}
  .days-left {{ color: #d10000; font-weight: bold; }}
  .footer {{ color: #7f8c8d; font-size: 0.9em; margin-top: 20px; border-top: 1px solid #eee; padding-top: 10px; }}
</style>
</head>
<body>
  <div class="header">
    <h2>Informasi Hari Libur Nasional</h2>
    <p>Berikut daftar hari libur yang akan datang:</p>
  </div>
  
  <div class="holiday-list">
    {"".join(
        f'<div class="holiday-item">'
        f'<div class="holiday-name">{h["holiday_name"]}</div>'
        f'<div class="holiday-date">{datetime.strptime(h["holiday_date"], "%Y-%m-%d").strftime("%A, %d %B %Y")}</div>'
        f'<div class="days-left">{get_time_status(datetime.strptime(h["holiday_date"], "%Y-%m-%d").date(), today)}</div>'
        f'</div>'
        for h in holidays
    )}
  </div>
  
  <div class="footer">
    <p>Email ini dikirim secara otomatis oleh sistem Holiday Reminder.</p>
    <p>Untuk berhenti menerima email ini, silakan hubungi administrator.</p>
  </div>
</body>
</html>"""
        
        # Plain text content
        text = "Informasi Hari Libur Nasional\n\n"
        text += "Berikut daftar hari libur yang akan datang:\n\n"
        text += "\n".join(
            f"- {h['holiday_name']} ({datetime.strptime(h['holiday_date'], '%Y-%m-%d').strftime('%A, %d %B %Y')}) "
            f"({get_time_status(datetime.strptime(h['holiday_date'], '%Y-%m-%d').date(), today)})"
            for h in holidays
        )
        text += "\n\nEmail ini dikirim secara otomatis oleh sistem Holiday Reminder."

        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"Holiday Reminder <{CONFIG['email_sender']}>"
        msg['To'] = ", ".join(receivers)
        msg['Reply-To'] = CONFIG['email_sender']
        msg['Return-Path'] = CONFIG['email_sender']
        msg['X-Mailer'] = 'HolidayReminder/1.0'
        msg['X-Priority'] = '3'  # Normal priority
        
        # Attach both versions
        part1 = MIMEText(text, 'plain')
        part2 = MIMEText(html, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        # Send email
        with smtplib.SMTP(CONFIG['smtp_server'], CONFIG['smtp_port'], timeout=30) as server:
            logger.info(f"Connecting to SMTP server {CONFIG['smtp_server']}:{CONFIG['smtp_port']}...")
            server.ehlo()
            server.starttls()
            logger.info(f"Logging in as {CONFIG['email_sender']}...")
            server.login(CONFIG['email_sender'], CONFIG['email_password'])
            logger.info(f"Sending email to {len(receivers)} recipients...")
            server.sendmail(CONFIG['email_sender'], receivers, msg.as_string())
        
        logger.info(f"Email notification sent successfully to {len(receivers)} receivers")
        return True
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error occurred: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending email: {str(e)}")
        return False

def send_manual_notification(days_range=3, test_email=None):
    today = datetime.now().date()
    
    # Get holidays within the specified range
    upcoming = [
        h for h in data_store.holidays 
        if 0 <= (datetime.strptime(h['holiday_date'], '%Y-%m-%d').date() - today).days <= days_range
    ]
    
    if not upcoming:
        return False, f"Tidak ada hari libur dalam {days_range} hari ke depan"
    
    receivers = [test_email] if test_email else data_store.receivers
    if not receivers:
        return False, "Tidak ada penerima yang terdaftar"
    
    try:
        if send_notification(upcoming, receivers):
            return True, f"Notifikasi berhasil dikirim untuk {len(upcoming)} hari libur"
        else:
            return False, "Gagal mengirim notifikasi"
    except Exception as e:
        return False, f"Error: {str(e)}"
    
# Test email function
def test_email_connection(receiver_email=None):
    try:
        receivers = [receiver_email] if receiver_email else data_store.receivers
        
        if not receivers:
            return False, "No receivers configured"
        
        # Log credentials being used (masked password)
        logger.info(f"Attempting to send test email using sender: {CONFIG['email_sender']}")
        password_length = len(CONFIG['email_password']) if CONFIG['email_password'] else 0
        logger.info(f"Using password with length: {password_length}")
        
        subject = "🧪 Test Email - Holiday Reminder App"
        body = f"""
        This is a test email from your Holiday Reminder application.
        
        Configuration details:
        - SMTP Server: {CONFIG['smtp_server']}
        - SMTP Port: {CONFIG['smtp_port']}
        - Sender: {CONFIG['email_sender']}
        
        If you received this email, your email configuration is working correctly!
        
        Sent at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = CONFIG['email_sender']
        msg['To'] = ", ".join(receivers)
        
        # More verbose debugging for email sending process
        logger.info(f"Connecting to SMTP server {CONFIG['smtp_server']}:{CONFIG['smtp_port']}...")
        
        with smtplib.SMTP(CONFIG['smtp_server'], CONFIG['smtp_port'], timeout=30) as server:
            logger.info("SMTP connection established, initiating TLS...")
            server.set_debuglevel(1)  # Enable debug output
            server.starttls()
            logger.info("TLS started, attempting login...")
            server.login(CONFIG['email_sender'], CONFIG['email_password'])
            logger.info("Login successful, sending email...")
            server.sendmail(CONFIG['email_sender'], receivers, msg.as_string())
            logger.info("Email send command completed")
        
        logger.info(f"Sent test email to {len(receivers)} receivers: {', '.join(receivers)}")
        return True, f"Test email sent successfully to {', '.join(receivers)}"
    except Exception as e:
        error_message = str(e)
        logger.error(f"Failed to send test email: {error_message}")
        return False, f"Failed to send test email: {error_message}"

# Scheduled Tasks
def daily_check():
    """Cek hari libur dan kirim notifikasi H-3 dan H-1"""
    logger.info("Starting daily check for holiday notifications...")
    print("Starting daily check for holiday notifications...")
    today = datetime.now().date()
    
    # Auto-update data jika diperlukan
    if not data_store.holidays or datetime.now().day == 1:  # Update tiap tanggal 1
        logger.info("Updating holiday data during daily check...")
        update_holidays()
    
    # Kirim notifikasi untuk H-3 dan H-1
    for days_before in [3, 1]:
        target_dates = [
            h for h in data_store.holidays
            if (datetime.strptime(h['holiday_date'], '%Y-%m-%d').date() - today).days == days_before
        ]
        if target_dates:
            logger.info(f"Found {len(target_dates)} holidays {days_before} days from now, sending notification...")
            send_notification(target_dates)
            logger.info(f"H-{days_before} notification sent for {len(target_dates)} holidays")
        else:
            logger.info(f"No holidays found {days_before} days from now")
            
# Flask API Endpoints
@flask_app.route('/api/test-notification/<int:days_before>')
def test_notification(days_before):
    """Endpoint untuk trigger manual"""
    today = datetime.now().date()
    holidays = [
        h for h in data_store.holidays
        if (datetime.strptime(h['holiday_date'], '%Y-%m-%d').date() - today).days == days_before
    ]
    
    if holidays:
        logger.info(f"Manual trigger: Sending H-{days_before} notification")
        success = send_notification(holidays)
        return jsonify({
            'success': success,
            'message': f"Notifikasi H-{days_before} {'terkirim' if success else 'gagal'}"
        })
    else:
        logger.warning(f"No H-{days_before} holidays found")
        return jsonify({
            'success': False,
            'message': f"Tidak ada hari libur H-{days_before} ditemukan"
        })
            
# Flask API Endpoints
@flask_app.route('/api/receivers', methods=['GET', 'POST'])
def manage_receivers():
    if request.method == 'POST':
        email = request.json.get('email')
        if email and email not in data_store.receivers:
            data_store.receivers.append(email)
            data_store.save_data()
        return jsonify({'receivers': data_store.receivers})
    return jsonify({'receivers': data_store.receivers})

@flask_app.route('/api/holidays')
def get_holidays():
    return jsonify({'holidays': data_store.holidays})

@flask_app.route('/api/update-holidays')
def api_update_holidays():
    try:
        update_holidays()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Helper functions for calendar display
def get_day_events(day, month, year, holidays):
    date_str = f"{year}-{month:02d}-{day:02d}"
    events = []
    
    for holiday in holidays:
        if holiday['holiday_date'] == date_str:
            events.append(holiday['holiday_name'])
    
    return events

def generate_month_calendar(month, year, holidays):
    cal = calendar.monthcalendar(year, month)
    month_name = calendar.month_name[month]
    
    # Create month header
    st.subheader(month_name)
    
    # Create weekday headers
    cols = st.columns(7)
    weekdays = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    for i, day_name in enumerate(weekdays):
        cols[i].markdown(f"**{day_name}**")
    
    # Fill in the calendar days
    today = datetime.now().date()
    
    for week in cal:
        cols = st.columns(7)
        for i, day in enumerate(week):
            if day == 0:
                cols[i].write("")  # Empty day
                continue
                
            # Check if this day has any holidays
            date_obj = datetime(year, month, day).date()
            events = get_day_events(day, month, year, holidays)
            
            # Format based on whether it's today, a holiday, or a regular day
            if date_obj == today:
                # Today's date
                if events:
                    cols[i].markdown(f"**{day}** 🎉", help="\n".join(events))
                else:
                    cols[i].markdown(f"**{day}** 📌")
            elif events:
                # Holiday
                cols[i].markdown(f"{day} 🎉", help="\n".join(events))
            else:
                # Regular day
                cols[i].write(str(day))

def display_events_widget():
    try:
        today = datetime.now().date()
        # Get upcoming holidays (next 30 days)
        upcoming_holidays = [
            h for h in data_store.holidays 
            if 0 <= (datetime.strptime(h['holiday_date'], '%Y-%m-%d').date() - today).days <= 30
        ]
        
        if not upcoming_holidays:
            st.info("No upcoming holidays in the next 30 days")
            return
            
        # Display upcoming holidays
        for holiday in upcoming_holidays:
            holiday_date = datetime.strptime(holiday['holiday_date'], '%Y-%m-%d')
            days_left = (holiday_date.date() - today).days
            
            if days_left == 0:
                status = "🎯 TODAY"
            else:
                status = f"sisa {days_left} hari"
                
            st.write(f"**{holiday['holiday_name']}** - {holiday_date.strftime('%d %B %Y')} ({status})")
            
    except Exception as e:
        st.error(f"Error displaying upcoming holidays: {str(e)}")

# Helper function to get appropriate time status text
def get_time_status(date, today):
    days_diff = (date - today).days
    
    if days_diff < 0:
        return f"Sudah lewat {abs(days_diff)} hari"
    elif days_diff == 0:
        return "Hari Ini"
    else:
        return f"{days_diff} hari lagi"

# Streamlit UI
def streamlit_ui():
    st.set_page_config(page_title="Holiday Reminder", layout="wide")
    st.title("Kalender Hari Libur Nasional")
    st.write("Sistem notifikasi otomatis untuk postingan media sosial")
    
    # Tab layout (added tab 3 for manual notifications)
    tab1, tab2, tab3 = st.tabs(["Kalender", "Pengaturan", "Notifikasi Manual"])
    
    with tab1:
        # Countdown Section
        st.header("⏳ Hari Libur Mendatang")
        today = datetime.now().date()
        
        # Filter to only show upcoming holidays (not past ones)
        upcoming_df = pd.DataFrame([
            {
                'Hari Libur': h['holiday_name'],
                'Tanggal': datetime.strptime(h['holiday_date'], '%Y-%m-%d').strftime('%d %B %Y'),
                'Hari': datetime.strptime(h['holiday_date'], '%Y-%m-%d').strftime('%A'),
                'Status': get_time_status(datetime.strptime(h['holiday_date'], '%Y-%m-%d').date(), today)
            }
            for h in data_store.holidays
        ])
        
        if not upcoming_df.empty:
            # Sort by date (closest first)
            upcoming_df['Sort Date'] = pd.to_datetime(upcoming_df['Tanggal'], format='%d %B %Y')
            upcoming_df = upcoming_df.sort_values('Sort Date')
            
            # Filter to only show future and today events for the main table
            future_df = upcoming_df[upcoming_df['Status'] != 'Sudah lewat']
            
            if not future_df.empty:
                # Drop the sorting column before display
                future_df = future_df.drop(columns=['Sort Date'])
                
                # Style the status column
                def style_status(val):
                    if val == 'Hari Ini':
                        return 'background-color: #ffeb3b; color: black; font-weight: bold'
                    elif 'hari lagi' in val and int(val.split()[0]) <= 3:
                        return 'background-color: #ff9800; color: white; font-weight: bold'
                    else:
                        return ''
                
                st.dataframe(
                    future_df.style.applymap(style_status, subset=['Status']),
                    height=300,
                    use_container_width=True
                )
            else:
                st.warning("Tidak ada hari libur yang akan datang")
            
            st.divider()
            # Calendar View (traditional calendar grid)
            st.header("📅 Kalender Hari Libur")
            
            # Year and month selector
            current_year = datetime.now().year
            current_month = datetime.now().month
            
            col1, col2 = st.columns(2)
            with col1:
                selected_year = st.selectbox("Tahun", 
                                          options=range(current_year-1, current_year+2),
                                          index=1)
            with col2:
                selected_month = st.selectbox("Bulan", 
                                           options=range(1, 13),
                                           index=current_month-1,
                                           format_func=lambda x: calendar.month_name[x])
            
            # Display calendar in grid format
            generate_month_calendar(selected_month, selected_year, data_store.holidays)
            
            st.divider()
            # Upcoming Events Widget
            st.header("Acara Mendatang")
            display_events_widget()
            
            if st.button("Perbarui Data Hari Libur"):
                with st.spinner('Memperbarui data hari libur...'):
                    update_holidays()
                st.success("Data hari libur berhasil diperbarui!")
            
            st.divider()
            # Holiday Details (only show upcoming holidays in dropdown)
            st.header("Detail Hari Libur")
            
            # Filter to only upcoming holidays for the dropdown
            future_holidays = [h for h in data_store.holidays 
                               if datetime.strptime(h['holiday_date'], '%Y-%m-%d').date() >= today]
            
            if future_holidays:
                selected_holiday = st.selectbox(
                    "Pilih hari libur untuk melihat detail",
                    options=[h['holiday_name'] for h in future_holidays],
                    key="holiday_select"
                )
                
                holiday_detail = next(
                    (h for h in future_holidays if h['holiday_name'] == selected_holiday),
                    None
                )
                
                if holiday_detail:
                    cols = st.columns(3)
                    with cols[0]:
                        st.metric(
                            label="Tanggal",
                            value=datetime.strptime(holiday_detail['holiday_date'], '%Y-%m-%d').strftime('%d %B %Y')
                        )
                    with cols[1]:
                        holiday_date = datetime.strptime(holiday_detail['holiday_date'], '%Y-%m-%d').date()
                        days_left = (holiday_date - today).days
                        status_text = get_time_status(holiday_date, today)
                        st.metric(
                            label="Status",
                            value=status_text
                        )
                    with cols[2]:
                        st.metric(
                            label="Hari",
                            value=datetime.strptime(holiday_detail['holiday_date'], '%Y-%m-%d').strftime('%A')
                        )
            else:
                st.warning("Tidak ada hari libur yang akan datang")
    
    with tab2:
        # Receiver Management
        st.header("Kelola Penerima Notifikasi")
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Tambahkan Penerima Baru")
            new_email = st.text_input("Email penerima", key="new_email")
            if st.button("Tambahkan") and new_email:
                if "@" in new_email:
                    if new_email not in data_store.receivers:
                        data_store.receivers.append(new_email)
                        data_store.save_data()
                        st.success(f"Email {new_email} berhasil ditambahkan")
                    else:
                        st.warning("Email sudah terdaftar")
                else:
                    st.error("Format email tidak valid")
        
        with col2:
            st.subheader("Kelola Penerima")
            if data_store.receivers:
                selected = st.multiselect(
                    "Pilih email untuk dihapus",
                    options=data_store.receivers,
                    key="email_select"
                )
                if st.button("Hapus yang dipilih"):
                    data_store.receivers = [e for e in data_store.receivers if e not in selected]
                    data_store.save_data()
                    st.success(f"Berhasil menghapus {len(selected)} email")
        
        st.divider()
        st.subheader("Daftar Penerima Saat Ini")
        if data_store.receivers:
            for i, receiver in enumerate(data_store.receivers, 1):
                st.write(f"{i}. {receiver}")
        else:
            st.warning("Belum ada penerima terdaftar")
            
        st.divider()
        
        # Holiday Management
        st.header("🔄 Perbarui Data Hari Libur")
        if st.button("Perbarui dari API"):
            with st.spinner('Memperbarui data hari libur...'):
                update_holidays()
            st.success("Data hari libur berhasil diperbarui!")
        
        st.divider()
        st.subheader("Status Terakhir")
        
        if data_store.holidays:
            last_update = datetime.fromtimestamp(os.path.getmtime('data.json')).strftime('%d %B %Y %H:%M:%S')
            st.write(f"Data terakhir diperbarui: {last_update}")
            st.write(f"Total hari libur: {len(data_store.holidays)}")
        else:
            st.warning("Belum ada data hari libur")
    
    with tab3:
        # Manual Notification Tab
        st.header("📨 Kirim Notifikasi Manual")
        
        # Section 1: Configuration info
        st.subheader("Konfigurasi Email")
    
        test_email = st.text_input("Masukkan alamat email untuk tes", 
                                 placeholder="contoh@email.com",
                                 help="Email ini akan menerima pesan tes")
        
        if st.button("Kirim Email Tes", key="send_test_email"):
            with st.spinner("Mengirim email tes..."):
                success, message = test_email_connection(test_email if test_email else None)
                
                if success:
                    st.success(message)
                else:
                    st.error(message)
        
        # Divider
        st.divider()
        
        # Section 3: Manual Holiday Notification
        st.subheader("Kirim Notifikasi Hari Libur")
        
        # Option to select notification range
        days_range = st.slider("Rentang hari untuk notifikasi", 
                              min_value=1, 
                              max_value=30, 
                              value=3,
                              help="Kirim notifikasi untuk hari libur dalam rentang hari yang dipilih")
        
        # Option to send to specific email or all subscribers
        use_test_email = st.checkbox("Kirim hanya ke email tertentu", 
                                   help="Jika dicentang, notifikasi akan dikirim hanya ke email yang ditentukan, bukan ke semua pelanggan")
        
        notification_email = None
        if use_test_email:
            notification_email = st.text_input("Email untuk notifikasi", 
                                            value=test_email if test_email else "",
                                            placeholder="contoh@email.com")
        
        if st.button("Kirim Notifikasi Hari Libur"):
            with st.spinner("Memproses notifikasi..."):
                success, message = send_manual_notification(
                    days_range=days_range,
                    test_email=notification_email if use_test_email else None
                )
                
                if success:
                    st.success(message)
                else:
                    st.error(message)

# Start scheduler
def start_scheduler():
    scheduler.add_job(daily_check, 'cron', hour=8, minute=0)  # Run daily at 8:00 AM
    scheduler.start()
    logger.info("Scheduler started")

# Run Flask in a separate thread
def run_flask():
    flask_app.run(host='0.0.0.0', port=5000)

# Main entry point
if __name__ == "__main__":
    # Initialize data and scheduler
    update_holidays()   
    
    # Start Flask in a separate thread
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("Flask API started")
    
    # Start scheduler
    start_scheduler()

    # Run Streamlit UI
    try:
        streamlit_ui()
    except KeyboardInterrupt:
        logger.info("Application shutdown requested")
        scheduler.shutdown()