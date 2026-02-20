import requests
import json
import socket
import time
import os
import logging
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import sqlite3
import re
from datetime import datetime
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_compress import Compress

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global timeout for all external requests - increased for yfinance
socket.setdefaulttimeout(15)

# Check if Ollama service is running
def check_ollama_service():
    try:
        response = requests.get('http://localhost:11434/api/tags', timeout=2)
        return response.status_code == 200
    except:
        return False

# Fallback chat response when Ollama is unavailable
def get_fallback_response(message):
    return "I'm currently offline. Please ensure Ollama is running on localhost:11434 to use the chat feature."

# Database path fix
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database", "finance.db")

try:
    from pycoingecko import CoinGeckoAPI
except ImportError:
    CoinGeckoAPI = None

try:
    import yfinance as yf
except ImportError:
    yf = None

app = Flask(__name__)
# Secure secret key
app.secret_key = "finance-app-secret-key-2024"

# Production optimizations
limiter = Limiter(get_remote_address, app=app)
Compress(app)

# Market data cache - increased to 60 seconds
market_cache = {}

def get_cached(key):
    data = market_cache.get(key)
    if data and time.time() - data["time"] < 10:  # Reduced to 10 sec for testing
        return data["value"]
    return None

def set_cache(key, value):
    # Clean old cache entries
    now = time.time()
    for k in list(market_cache.keys()):
        if now - market_cache[k]["time"] > 120:
            del market_cache[k]
    market_cache[key] = {"value": value, "time": time.time()}

# Safe yfinance wrapper with better error handling
def safe_yf_download(symbol):
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d", timeout=10)
        if hist.empty:
            # Try alternative period
            hist = ticker.history(period="1mo", timeout=10)
        return hist
    except Exception as e:
        print(f"YF ERROR for {symbol}: {e}")
        return None

# Get real-time price with fallback
def get_real_price(symbol, yf_symbol, fallback_price):
    try:
        ticker = yf.Ticker(yf_symbol)
        hist = ticker.history(period="1d", timeout=5)
        if not hist.empty:
            return float(hist['Close'].iloc[-1])
        return fallback_price
    except:
        return fallback_price

# Database with absolute path
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db:
        db.close()

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE,
        email TEXT UNIQUE,
        password_hash TEXT,
        theme TEXT DEFAULT 'dark'
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS wallets (
        id INTEGER PRIMARY KEY,
        user_id INTEGER UNIQUE,
        balance REAL DEFAULT 0
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        type TEXT,
        amount REAL,
        description TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        category TEXT,
        amount REAL,
        notes TEXT,
        expense_date DATE
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS savings_goals (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        goal_name TEXT,
        target_amount REAL,
        current_amount REAL DEFAULT 0,
        deadline DATE
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS budgets (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        category TEXT,
        monthly_limit REAL
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS assets (
        id INTEGER PRIMARY KEY,
        symbol TEXT NOT NULL,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        current_price REAL
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        asset_id INTEGER,
        type TEXT NOT NULL,
        quantity REAL NOT NULL,
        price REAL NOT NULL,
        total REAL NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS portfolio (
        id INTEGER PRIMARY KEY,
        user_id INTEGER,
        asset_type TEXT DEFAULT 'stocks',
        symbol TEXT,
        quantity REAL,
        buy_price REAL,
        current_price REAL,
        purchase_date DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Insert sample assets
    sample_assets = [
        # Indian Stocks - Banking & Financial
        ('RELIANCE', 'Reliance Industries Ltd.', 'stock', 2456.75),
        ('TCS', 'Tata Consultancy Services', 'stock', 3678.90),
        ('INFY', 'Infosys Ltd.', 'stock', 1456.30),
        ('HDFCBANK', 'HDFC Bank Ltd.', 'stock', 1589.25),
        ('SBIN', 'State Bank of India', 'stock', 598.75),
        ('ICICIBANK', 'ICICI Bank Ltd.', 'stock', 945.60),
        ('KOTAKBANK', 'Kotak Mahindra Bank', 'stock', 1789.35),
        ('AXISBANK', 'Axis Bank Ltd.', 'stock', 756.40),
        ('BAJFINANCE', 'Bajaj Finance Ltd.', 'stock', 6789.40),
        ('INDUSINDBK', 'IndusInd Bank Ltd.', 'stock', 1234.50),
        ('FEDERALBNK', 'Federal Bank Ltd.', 'stock', 145.60),
        ('BANDHANBNK', 'Bandhan Bank Ltd.', 'stock', 234.80),
        ('IDFCFIRSTB', 'IDFC First Bank Ltd.', 'stock', 89.45),
        ('PNB', 'Punjab National Bank', 'stock', 67.80),
        ('CANBK', 'Canara Bank', 'stock', 345.60),
        ('BANKBARODA', 'Bank of Baroda', 'stock', 189.25),
        ('UNIONBANK', 'Union Bank of India', 'stock', 78.90),
        ('INDIANB', 'Indian Bank', 'stock', 456.75),
        ('CENTRALBK', 'Central Bank of India', 'stock', 34.50),
        
        # IT Services
        ('HCLTECH', 'HCL Technologies Ltd.', 'stock', 1234.50),
        ('WIPRO', 'Wipro Ltd.', 'stock', 456.75),
        ('TECHM', 'Tech Mahindra Ltd.', 'stock', 1089.60),
        ('LTIM', 'LTI Mindtree Ltd.', 'stock', 4567.80),
        ('MPHASIS', 'Mphasis Ltd.', 'stock', 2345.60),
        ('PERSISTENT', 'Persistent Systems Ltd.', 'stock', 5678.90),
        ('COFORGE', 'Coforge Ltd.', 'stock', 4321.50),
        ('LTTS', 'L&T Technology Services', 'stock', 3456.70),
        ('OFSS', 'Oracle Financial Services', 'stock', 6789.40),
        ('CYIENT', 'Cyient Ltd.', 'stock', 1567.80),
        
        # Consumer Goods & FMCG
        ('HINDUNILVR', 'Hindustan Unilever Ltd.', 'stock', 2789.45),
        ('ITC', 'ITC Ltd.', 'stock', 456.80),
        ('BRITANNIA', 'Britannia Industries Ltd.', 'stock', 4567.25),
        ('NESTLEIND', 'Nestle India Ltd.', 'stock', 23456.75),
        ('DABUR', 'Dabur India Ltd.', 'stock', 567.80),
        ('GODREJCP', 'Godrej Consumer Products', 'stock', 1234.50),
        ('MARICO', 'Marico Ltd.', 'stock', 567.80),
        ('COLPAL', 'Colgate Palmolive India', 'stock', 1789.60),
        ('EMAMILTD', 'Emami Ltd.', 'stock', 456.70),
        ('VBLLTD', 'Varun Beverages Ltd.', 'stock', 1234.80),
        ('TATACONSUM', 'Tata Consumer Products', 'stock', 890.50),
        ('UBL', 'United Breweries Ltd.', 'stock', 1567.40),
        
        # Automotive
        ('MARUTI', 'Maruti Suzuki India Ltd.', 'stock', 10567.25),
        ('TATAMOTORS', 'Tata Motors Ltd.', 'stock', 567.80),
        ('M&M', 'Mahindra & Mahindra Ltd.', 'stock', 1456.90),
        ('BAJAJ-AUTO', 'Bajaj Auto Ltd.', 'stock', 6789.50),
        ('EICHERMOT', 'Eicher Motors Ltd.', 'stock', 3456.70),
        ('HEROMOTOCO', 'Hero MotoCorp Ltd.', 'stock', 2789.40),
        ('TVSMOTORS', 'TVS Motor Company Ltd.', 'stock', 1234.60),
        ('ASHOKLEY', 'Ashok Leyland Ltd.', 'stock', 189.50),
        ('MOTHERSON', 'Motherson Sumi Systems', 'stock', 145.60),
        ('BOSCHLTD', 'Bosch Ltd.', 'stock', 18567.80),
        ('MRF', 'MRF Ltd.', 'stock', 89567.50),
        ('APOLLOTYRE', 'Apollo Tyres Ltd.', 'stock', 456.70),
        ('CEAT', 'CEAT Ltd.', 'stock', 2345.80),
        ('BALKRISIND', 'Balkrishna Industries', 'stock', 2567.90),
        ('EXIDEIND', 'Exide Industries Ltd.', 'stock', 234.50),
        
        # Telecom
        ('BHARTIARTL', 'Bharti Airtel Ltd.', 'stock', 1156.75),
        ('JIOFINANCE', 'Jio Financial Services', 'stock', 345.60),
        ('IDEA', 'Vodafone Idea Ltd.', 'stock', 12.45),
        
        # Infrastructure & Construction
        ('LT', 'Larsen & Toubro Ltd.', 'stock', 3245.67),
        ('ULTRACEMCO', 'UltraTech Cement Ltd.', 'stock', 8567.90),
        ('GRASIM', 'Grasim Industries Ltd.', 'stock', 1789.50),
        ('ADANIPORTS', 'Adani Ports & SEZ Ltd.', 'stock', 1234.60),
        ('POWERGRID', 'Power Grid Corporation', 'stock', 234.50),
        ('ADANIENT', 'Adani Enterprises Ltd.', 'stock', 2567.80),
        ('ADANIGREEN', 'Adani Green Energy Ltd.', 'stock', 1789.40),
        ('ADANITRANS', 'Adani Transmission Ltd.', 'stock', 890.60),
        ('ADANIPOWER', 'Adani Power Ltd.', 'stock', 456.70),
        ('AMBUJCEM', 'Ambuja Cements Ltd.', 'stock', 567.80),
        ('ACC', 'ACC Ltd.', 'stock', 2345.60),
        ('SHREECEM', 'Shree Cement Ltd.', 'stock', 25678.90),
        ('RAMCOCEM', 'Ramco Cements Ltd.', 'stock', 890.50),
        ('DLF', 'DLF Ltd.', 'stock', 567.80),
        ('GODREJPROP', 'Godrej Properties Ltd.', 'stock', 2345.60),
        ('OBEROIRLTY', 'Oberoi Realty Ltd.', 'stock', 1567.80),
        
        # Pharmaceuticals & Healthcare
        ('SUNPHARMA', 'Sun Pharmaceutical Ind.', 'stock', 1234.50),
        ('DRREDDY', 'Dr Reddys Laboratories', 'stock', 5678.90),
        ('CIPLA', 'Cipla Ltd.', 'stock', 1456.70),
        ('DIVISLAB', 'Divis Laboratories Ltd.', 'stock', 3567.80),
        ('APOLLOHOSP', 'Apollo Hospitals Ent.', 'stock', 5678.90),
        ('LUPIN', 'Lupin Ltd.', 'stock', 1234.50),
        ('BIOCON', 'Biocon Ltd.', 'stock', 345.60),
        ('CADILAHC', 'Cadila Healthcare Ltd.', 'stock', 567.80),
        ('AUROPHARMA', 'Aurobindo Pharma Ltd.', 'stock', 890.50),
        ('TORNTPHARM', 'Torrent Pharmaceuticals', 'stock', 2345.60),
        ('GLENMARK', 'Glenmark Pharmaceuticals', 'stock', 789.40),
        ('ALKEM', 'Alkem Laboratories Ltd.', 'stock', 3456.70),
        ('ABBOTINDIA', 'Abbott India Ltd.', 'stock', 23456.80),
        ('PFIZER', 'Pfizer Ltd.', 'stock', 4567.90),
        ('FORTIS', 'Fortis Healthcare Ltd.', 'stock', 456.70),
        
        # Metals & Mining
        ('TATASTEEL', 'Tata Steel Ltd.', 'stock', 145.60),
        ('HINDALCO', 'Hindalco Industries Ltd.', 'stock', 456.80),
        ('JSWSTEEL', 'JSW Steel Ltd.', 'stock', 789.25),
        ('COALINDIA', 'Coal India Ltd.', 'stock', 234.50),
        ('VEDL', 'Vedanta Ltd.', 'stock', 234.90),
        ('HINDZINC', 'Hindustan Zinc Ltd.', 'stock', 298.45),
        ('NMDC', 'NMDC Ltd.', 'stock', 156.75),
        ('SAIL', 'Steel Authority of India', 'stock', 89.45),
        ('JINDALSTEL', 'Jindal Steel & Power', 'stock', 567.80),
        ('NATIONALUM', 'National Aluminium Co.', 'stock', 89.50),
        
        # Energy & Oil
        ('ONGC', 'Oil & Natural Gas Corp.', 'stock', 234.50),
        ('IOC', 'Indian Oil Corporation', 'stock', 145.60),
        ('BPCL', 'Bharat Petroleum Corp.', 'stock', 456.70),
        ('HPCL', 'Hindustan Petroleum', 'stock', 345.80),
        ('GAIL', 'GAIL India Ltd.', 'stock', 189.50),
        ('OIL', 'Oil India Ltd.', 'stock', 456.70),
        ('PETRONET', 'Petronet LNG Ltd.', 'stock', 234.80),
        ('IGL', 'Indraprastha Gas Ltd.', 'stock', 456.90),
        ('MGL', 'Mahanagar Gas Ltd.', 'stock', 1234.50),
        
        # Power & Utilities
        ('NTPC', 'NTPC Ltd.', 'stock', 234.56),
        ('TATAPOWER', 'Tata Power Co. Ltd.', 'stock', 345.60),
        ('TORNTPOWER', 'Torrent Power Ltd.', 'stock', 789.40),
        ('CESC', 'CESC Ltd.', 'stock', 890.50),
        ('NHPC', 'NHPC Ltd.', 'stock', 67.80),
        ('SJVN', 'SJVN Ltd.', 'stock', 89.50),
        ('THERMAX', 'Thermax Ltd.', 'stock', 2345.60),
        ('BHEL', 'Bharat Heavy Electricals', 'stock', 145.60),
        
        # Textiles & Apparel
        ('RAYMOND', 'Raymond Ltd.', 'stock', 1789.50),
        ('ARVIND', 'Arvind Ltd.', 'stock', 456.70),
        ('WELSPUNIND', 'Welspun India Ltd.', 'stock', 145.60),
        ('VARDHMAN', 'Vardhman Textiles Ltd.', 'stock', 456.80),
        ('TRIDENT', 'Trident Ltd.', 'stock', 45.60),
        ('PAGEIND', 'Page Industries Ltd.', 'stock', 45678.90),
        
        # Chemicals & Fertilizers
        ('UPL', 'UPL Ltd.', 'stock', 567.80),
        ('PIDILITIND', 'Pidilite Industries Ltd.', 'stock', 2789.50),
        ('DEEPAKNTR', 'Deepak Nitrite Ltd.', 'stock', 2345.60),
        ('GNFC', 'Gujarat Narmada Valley Fertilizers', 'stock', 567.80),
        ('RCF', 'Rashtriya Chemicals & Fertilizers', 'stock', 145.60),
        ('CHAMBLFERT', 'Chambal Fertilizers Ltd.', 'stock', 456.70),
        ('COROMANDEL', 'Coromandel International', 'stock', 1234.50),
        ('NFL', 'National Fertilizers Ltd.', 'stock', 89.50),
        
        # Others
        ('ASIANPAINT', 'Asian Paints Ltd.', 'stock', 3234.56),
        ('TITAN', 'Titan Company Ltd.', 'stock', 3456.78),
        ('BAJAJFINSV', 'Bajaj Finserv Ltd.', 'stock', 1567.80),
        ('HDFCLIFE', 'HDFC Life Insurance Co.', 'stock', 678.90),
        ('SBILIFE', 'SBI Life Insurance Co.', 'stock', 1234.50),
        ('ICICIPRULI', 'ICICI Prudential Life', 'stock', 567.80),
        ('SHRIRAMFIN', 'Shriram Finance Ltd.', 'stock', 2345.60),
        ('CHOLAFIN', 'Cholamandalam Investment', 'stock', 1234.50),
        ('PFC', 'Power Finance Corporation', 'stock', 345.60),
        ('RECLTD', 'REC Ltd.', 'stock', 456.70),
        ('DMART', 'Avenue Supermarts Ltd.', 'stock', 4567.80),
        ('TRENT', 'Trent Ltd.', 'stock', 6789.50),
        ('JUBLFOOD', 'Jubilant FoodWorks Ltd.', 'stock', 567.80),
        
        # Crypto
        ('BTC', 'Bitcoin', 'crypto', 45000.00),
        ('ETH', 'Ethereum', 'crypto', 2800.00),
        ('BNB', 'Binance Coin', 'crypto', 320.00),
        ('ADA', 'Cardano', 'crypto', 0.45),
        ('SOL', 'Solana', 'crypto', 95.00),
        ('DOT', 'Polkadot', 'crypto', 6.80),
        ('MATIC', 'Polygon', 'crypto', 0.85),
        ('AVAX', 'Avalanche', 'crypto', 38.00),
        ('LINK', 'Chainlink', 'crypto', 15.50),
        ('UNI', 'Uniswap', 'crypto', 8.20),
        ('LTC', 'Litecoin', 'crypto', 95.00),
        ('XRP', 'Ripple', 'crypto', 0.52),
        ('DOGE', 'Dogecoin', 'crypto', 0.08),
        ('SHIB', 'Shiba Inu', 'crypto', 0.000025),
        
        # Commodities
        ('GOLD', 'Gold', 'commodity', 62500.00),
        ('SILVER', 'Silver', 'commodity', 75000.00),
        ('CRUDEOIL', 'Crude Oil', 'commodity', 6450.00),
        ('NATURALGAS', 'Natural Gas', 'commodity', 245.00),
        ('COPPER', 'Copper', 'commodity', 698.00),
        ('PLATINUM', 'Platinum', 'commodity', 275000.00),
        ('PALLADIUM', 'Palladium', 'commodity', 195000.00),
        ('WHEAT', 'Wheat', 'commodity', 2500.00),
        ('CORN', 'Corn', 'commodity', 1800.00),
        ('SOYBEANS', 'Soybeans', 'commodity', 4200.00),
        ('RICE', 'Rice', 'commodity', 3200.00),
        ('SUGAR', 'Sugar', 'commodity', 4500.00),
        ('COFFEE', 'Coffee', 'commodity', 18500.00),
        ('COCOA', 'Cocoa', 'commodity', 28500.00),
        ('COTTON', 'Cotton', 'commodity', 6200.00),
        ('ZINC', 'Zinc', 'commodity', 234.00),
        ('ALUMINIUM', 'Aluminium', 'commodity', 198.00),
        ('NICKEL', 'Nickel', 'commodity', 1456.00),
        ('LEAD', 'Lead', 'commodity', 189.00),
        
        # ETFs
        ('GOLDBEES', 'Gold BeES ETF', 'etf', 45.67),
        ('NIFTYBEES', 'Nifty BeES ETF', 'etf', 234.56),
        ('BANKBEES', 'Bank BeES ETF', 'etf', 456.78),
        ('JUNIORBEES', 'Junior BeES ETF', 'etf', 567.89),
        ('LIQUIDBEES', 'Liquid BeES ETF', 'etf', 1000.00),
        ('SILVERBEES', 'Silver BeES ETF', 'etf', 67.89),
        ('PSUBNKBEES', 'PSU Bank BeES ETF', 'etf', 12.45),
        ('PVTBNKBEES', 'Private Bank BeES ETF', 'etf', 234.56),
        ('ITBEES', 'IT BeES ETF', 'etf', 345.67),
        ('PHARMABEES', 'Pharma BeES ETF', 'etf', 456.78),
        ('FMCGBEES', 'FMCG BeES ETF', 'etf', 567.89),
        ('AUTOBEES', 'Auto BeES ETF', 'etf', 123.45),
        ('REALTYBEES', 'Realty BeES ETF', 'etf', 89.50),
        ('ENERGYBEES', 'Energy BeES ETF', 'etf', 234.60),
        ('METALBEES', 'Metal BeES ETF', 'etf', 345.70),
        ('INFRABEES', 'Infrastructure BeES ETF', 'etf', 456.80),
        ('MIDCAPBEES', 'Midcap BeES ETF', 'etf', 567.90),
        ('SMALLCAPBEES', 'Smallcap BeES ETF', 'etf', 123.40),
        ('DIVOPPBEES', 'Dividend Opportunities BeES ETF', 'etf', 234.50),
        ('QUALITYBEES', 'Quality BeES ETF', 'etf', 345.60),
        ('LOWVOLBEES', 'Low Volatility BeES ETF', 'etf', 456.70),
        ('MOMENTUMBEES', 'Momentum BeES ETF', 'etf', 567.80),
        ('VALUEBEES', 'Value BeES ETF', 'etf', 123.90),
        ('GROWTHBEES', 'Growth BeES ETF', 'etf', 234.10)
    ]
    
    # Insert sample assets only if empty
    if c.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0:
        c.executemany('INSERT OR IGNORE INTO assets (symbol, name, type, current_price) VALUES (?, ?, ?, ?)', sample_assets)
    
    conn.commit()
    conn.close()

# Auth decorator
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# Validation
def validate_email(email):
    return re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email)

def validate_password(password):
    return (
        len(password) >= 8 and
        re.search(r'[A-Z]', password) and
        re.search(r'[a-z]', password) and
        re.search(r'\d', password)
    )

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        
        if not username or not validate_email(email) or not validate_password(password):
            flash('Invalid input', 'error')
            return redirect(url_for('register'))
        
        try:
            conn = get_db()
            c = conn.cursor()
            
            # Check if user exists
            existing = c.execute('SELECT id FROM users WHERE username=? OR email=?', 
                               (username, email)).fetchone()
            if existing:
                flash('User already exists', 'error')
                return redirect(url_for('register'))
            
            # Create user
            password_hash = generate_password_hash(password)
            c.execute('INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)',
                     (username, email, password_hash))
            user_id = c.lastrowid
            
            # Create wallet
            c.execute('INSERT INTO wallets (user_id, balance) VALUES (?, 0)', (user_id,))
            
            conn.commit()
            
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
            
        except Exception as e:
            flash('Registration failed', 'error')
            return redirect(url_for('register'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password = request.form.get('password', '')
        
        if not identifier or not password:
            flash('Please enter username/email and password', 'error')
            return redirect(url_for('login'))
        
        try:
            conn = get_db()
            user = conn.execute('SELECT * FROM users WHERE username=? OR email=?',
                              (identifier, identifier)).fetchone()
            
            if user and check_password_hash(user['password_hash'], password):
                session['user_id'] = user['id']
                session['username'] = user['username']
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid credentials', 'error')
        except Exception as e:
            flash('Login failed', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session['user_id']
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Get wallet
        wallet_data = c.execute('SELECT * FROM wallets WHERE user_id=?', (user_id,)).fetchone()
        if not wallet_data:
            c.execute('INSERT INTO wallets (user_id, balance) VALUES (?, 0)', (user_id,))
            conn.commit()
            wallet_data = c.execute('SELECT * FROM wallets WHERE user_id=?', (user_id,)).fetchone()
        
        # Create wallet structure expected by templates
        wallet = {
            'main_balance': wallet_data['balance'],
            'investment_balance': 0,  # Can be calculated from portfolio later
            'savings_balance': 0      # Can be calculated from savings goals later
        }
        
        # Get recent transactions
        transactions = c.execute('SELECT * FROM transactions WHERE user_id=? ORDER BY timestamp DESC LIMIT 5',
                                (user_id,)).fetchall()
        
        # Get expenses
        expenses = c.execute('SELECT * FROM expenses WHERE user_id=? ORDER BY expense_date DESC LIMIT 5',
                           (user_id,)).fetchall()
        
        # Calculate monthly expenses
        monthly_expenses = c.execute('''
            SELECT COALESCE(SUM(amount), 0) as total 
            FROM expenses 
            WHERE user_id=? AND strftime('%Y-%m', expense_date) = strftime('%Y-%m', 'now')
        ''', (user_id,)).fetchone()['total'] or 0
        
        return render_template('dashboard.html', 
                             wallet=wallet, 
                             transactions=transactions,
                             expenses=expenses,
                             monthly_expenses=monthly_expenses)
    except Exception as e:
        print(f"Dashboard error: {str(e)}")
        flash('Error loading dashboard', 'error')
        return render_template('dashboard.html', 
                             wallet={'main_balance': 0, 'investment_balance': 0, 'savings_balance': 0}, 
                             transactions=[], 
                             expenses=[],
                             monthly_expenses=0)

@app.route('/wallet/add', methods=['GET', 'POST'])
@login_required
def add_funds():
    if request.method == 'POST':
        try:
            amount = float(request.form.get('amount', 0))
            if amount <= 0:
                flash('Invalid amount', 'error')
                return redirect(url_for('add_funds'))
            
            user_id = session['user_id']
            
            conn = get_db()
            conn.execute("BEGIN IMMEDIATE")
            c = conn.cursor()
            
            # Update wallet
            c.execute('UPDATE wallets SET balance = balance + ? WHERE user_id=?', 
                     (amount, user_id))
            
            # Add transaction
            c.execute('INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)',
                     (user_id, 'deposit', amount, 'Funds added'))
            
            conn.commit()
            
            flash(f'₹{amount:.2f} added successfully!', 'success')
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            flash('Transaction failed', 'error')
    
    return render_template('add_funds.html')

@app.route('/expenses/add', methods=['GET', 'POST'])
@login_required
def add_expense():
    if request.method == 'POST':
        try:
            amount = float(request.form.get('amount', 0))
            category = request.form.get('category', '').strip()
            notes = request.form.get('notes', '').strip()
            expense_date = request.form.get('expense_date', '')
            
            if amount <= 0 or not category:
                flash('Invalid input', 'error')
                return redirect(url_for('add_expense'))
            
            user_id = session['user_id']
            
            conn = get_db()
            conn.execute("BEGIN IMMEDIATE")
            c = conn.cursor()
            
            # Check balance
            wallet = c.execute('SELECT balance FROM wallets WHERE user_id=?', (user_id,)).fetchone()
            if not wallet or wallet['balance'] < amount:
                flash('Insufficient balance', 'error')
                return redirect(url_for('add_expense'))
            
            # Update wallet
            c.execute('UPDATE wallets SET balance = balance - ? WHERE user_id=?', 
                     (amount, user_id))
            
            # Add expense
            c.execute('INSERT INTO expenses (user_id, category, amount, notes, expense_date) VALUES (?, ?, ?, ?, ?)',
                     (user_id, category, amount, notes, expense_date or datetime.now().date()))
            
            # Add transaction
            c.execute('INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)',
                     (user_id, 'expense', amount, f'{category} expense'))
            
            conn.commit()
            
            flash(f'Expense of ₹{amount:.2f} added!', 'success')
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            flash('Failed to add expense', 'error')
    
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('add_expense.html', today=today)

@app.route('/expenses')
@login_required
def expenses():
    user_id = session['user_id']
    
    try:
        conn = get_db()
        all_expenses = conn.execute('SELECT * FROM expenses WHERE user_id=? ORDER BY expense_date DESC',
                                  (user_id,)).fetchall()
        
        return render_template('expenses.html', expenses=all_expenses)
    except Exception as e:
        flash('Error loading expenses', 'error')
        return redirect(url_for('dashboard'))

@app.route('/wallet')
@login_required
def wallet():
    user_id = session['user_id']
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        wallet_data = c.execute('SELECT * FROM wallets WHERE user_id=?', (user_id,)).fetchone()
        
        # Create wallet structure expected by templates
        wallet = {
            'main_balance': wallet_data['balance'] if wallet_data else 0,
            'investment_balance': 0,  # Can be calculated from portfolio later
            'savings_balance': 0      # Can be calculated from savings goals later
        }
        
        transactions = c.execute('SELECT * FROM transactions WHERE user_id=? ORDER BY timestamp DESC',
                                (user_id,)).fetchall()
        
        conn.close()
        
        return render_template('wallet.html', wallet=wallet, transactions=transactions)
    except Exception as e:
        flash('Error loading wallet', 'error')
        return redirect(url_for('dashboard'))

@app.route('/portfolio')
@login_required
def portfolio():
    user_id = session['user_id']
    
    try:
        conn = get_db()
        # Add asset_type column if it doesn't exist
        try:
            conn.execute('ALTER TABLE portfolio ADD COLUMN asset_type TEXT DEFAULT "stocks"')
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        holdings = conn.execute('SELECT * FROM portfolio WHERE user_id=? ORDER BY purchase_date DESC',
                              (user_id,)).fetchall()
        conn.close()
        
        return render_template('portfolio.html', holdings=holdings)
    except Exception as e:
        flash('Error loading portfolio', 'error')
        return render_template('portfolio.html', holdings=[])

@app.route('/analytics')
@login_required
def analytics():
    user_id = session['user_id']
    
    try:
        conn = get_db()
        
        # Expenses by category
        expenses_by_category = conn.execute('''
            SELECT category, SUM(amount) as total 
            FROM expenses WHERE user_id=? 
            GROUP BY category
        ''', (user_id,)).fetchall()
        
        conn.close()
        
        return render_template('analytics.html', 
                             expenses_by_category=expenses_by_category,
                             monthly_expenses=[])
    except Exception as e:
        flash('Error loading analytics', 'error')
        return redirect(url_for('dashboard'))

@app.route('/trade')
@login_required
def trade():
    return render_template('trade.html')

@app.route('/savings')
@login_required
def savings():
    user_id = session['user_id']
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Ensure savings_goals table exists
        c.execute('''CREATE TABLE IF NOT EXISTS savings_goals (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            goal_name TEXT,
            target_amount REAL,
            current_amount REAL DEFAULT 0,
            deadline DATE
        )''')
        conn.commit()
        
        goals = c.execute('SELECT * FROM savings_goals WHERE user_id=? ORDER BY deadline ASC',
                         (user_id,)).fetchall()
        conn.close()
        
        return render_template('savings.html', goals=goals)
    except Exception as e:
        print(f"Savings error: {str(e)}")
        flash('Error loading savings goals', 'error')
        return render_template('savings.html', goals=[])

# =========================
# AI INSIGHTS (LLM via Ollama)
# =========================
@app.route('/ai-insights')
@login_required
def ai_insights():
    user_id = session['user_id']
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        wallet_data = c.execute('SELECT * FROM wallets WHERE user_id=?', (user_id,)).fetchone()
        
        wallet = {
            'main_balance': wallet_data['balance'] if wallet_data else 0,
            'investment_balance': 0,
            'savings_balance': 0
        }
        
        expenses_by_cat = c.execute(
            'SELECT category, SUM(amount) as total FROM expenses WHERE user_id=? GROUP BY category',
            (user_id,)
        ).fetchall()
        
        monthly_expenses = c.execute('''
            SELECT COALESCE(SUM(amount), 0) as total 
            FROM expenses 
            WHERE user_id=? AND strftime('%Y-%m', expense_date) = strftime('%Y-%m', 'now')
        ''', (user_id,)).fetchone()['total'] or 0
        
        balance = wallet['main_balance']
        total_expenses = sum(exp['total'] for exp in expenses_by_cat)
        portfolio_value = c.execute(
            'SELECT SUM(quantity * current_price) as total FROM portfolio WHERE user_id=?',
            (user_id,)
        ).fetchone()
        investments = portfolio_value['total'] if portfolio_value and portfolio_value['total'] else 0
        
        conn.close()
        
        ai_insights = []
        health_scores = {'savings': 50, 'expense': 50, 'investment': 50, 'goal': 50}
        
        try:
            context = f"""Generate 3 personalized financial insights for user with:
Balance: ₹{balance}
Monthly Expenses: ₹{monthly_expenses}
Total Expenses: ₹{total_expenses}
Investments: ₹{investments}

Provide specific, actionable advice in this format:
1. [Icon] [Title]: [Brief advice]
2. [Icon] [Title]: [Brief advice]
3. [Icon] [Title]: [Brief advice]

Also provide 4 health scores (0-100) for: savings_rate, expense_control, investment_mix, goal_progress"""
            
            response = requests.post(
                'http://localhost:11434/api/generate',
                json={
                    'model': 'llama3',
                    'prompt': context,
                    'stream': False
                },
                timeout=20
            )
            
            if response.status_code == 200:
                ai_response = response.json().get('response', '')
                lines = [line.strip() for line in ai_response.split('\n') if line.strip()]
                
                for line in lines[:3]:
                    if ':' in line:
                        parts = line.split(':', 1)
                        title = parts[0].strip()
                        advice = parts[1].strip()
                        ai_insights.append({'title': title, 'advice': advice})
                
                import re
                scores = re.findall(r'(\d+)', ai_response)
                if len(scores) >= 4:
                    health_scores = {
                        'savings': min(100, max(0, int(scores[-4]))),
                        'expense': min(100, max(0, int(scores[-3]))),
                        'investment': min(100, max(0, int(scores[-2]))),
                        'goal': min(100, max(0, int(scores[-1])))
                    }
        except:
            pass
        
        if not ai_insights:
            ai_insights = [
                {'title': '💰 Optimize Your Savings', 'advice': f'Your current balance is ₹{balance:.0f}. Consider automating savings.'},
                {'title': '📊 Expense Management', 'advice': f'Monthly expenses: ₹{monthly_expenses:.0f}. Track categories for better control.'},
                {'title': '🎯 Investment Growth', 'advice': f'Portfolio value: ₹{investments:.0f}. Diversify for better returns.'}
            ]
        
        return render_template(
            'ai_insights.html',
            wallet=wallet,
            monthly_expenses=monthly_expenses,
            expenses_by_cat=expenses_by_cat,
            ai_insights=ai_insights,
            health_scores=health_scores
        )
    except Exception as e:
        flash('Error loading insights', 'error')
        return redirect(url_for('dashboard'))

@app.route('/notifications')
@login_required
def notifications():
    return render_template('notifications.html')

@app.route('/profile')
@login_required
def profile():
    try:
        user_id = session['user_id']
        conn = sqlite3.connect(DB_PATH, timeout=1)
        conn.row_factory = sqlite3.Row
        user = conn.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        conn.close()
        
        if not user:
            return "User not found", 404
        
        # Convert to dict and add missing fields for template
        user_dict = dict(user)
        if 'created_at' not in user_dict or not user_dict['created_at']:
            user_dict['created_at'] = '2024-01-01 00:00:00'
        if 'pin_hash' not in user_dict:
            user_dict['pin_hash'] = None
            
        return render_template('profile.html', user=user_dict)
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/api/theme', methods=['POST'])
@login_required
def toggle_theme():
    try:
        user_id = session['user_id']
        data = request.get_json()
        theme = data.get('theme', 'dark')
        
        if theme not in ['light', 'dark']:
            theme = 'dark'
        
        conn = get_db()
        conn.execute('UPDATE users SET theme = ? WHERE id = ?', (theme, user_id))
        conn.commit()
        
        return jsonify({'success': True, 'theme': theme})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        if email:
            flash('Password reset link sent (demo feature)', 'info')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')

# Additional routes for all navbar and button elements

# Wallet routes
@app.route('/wallet/withdraw', methods=['GET', 'POST'])
@login_required
def withdraw_funds():
    if request.method == 'POST':
        try:
            amount = float(request.form.get('amount', 0))
            if amount <= 0:
                flash('Invalid amount', 'error')
                return redirect(url_for('withdraw_funds'))
            
            user_id = session['user_id']
            conn = get_db()
            conn.execute("BEGIN IMMEDIATE")
            c = conn.cursor()
            
            wallet = c.execute('SELECT balance FROM wallets WHERE user_id=?', (user_id,)).fetchone()
            if not wallet or wallet['balance'] < amount:
                flash('Insufficient balance', 'error')
                return redirect(url_for('withdraw_funds'))
            
            c.execute('UPDATE wallets SET balance = balance - ? WHERE user_id=?', (amount, user_id))
            c.execute('INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)',
                     (user_id, 'withdrawal', amount, 'Funds withdrawn'))
            
            conn.commit()
            conn.close()
            
            flash(f'₹{amount:.2f} withdrawn successfully!', 'success')
            return redirect(url_for('wallet'))
        except Exception as e:
            flash('Withdrawal failed', 'error')
    
    return render_template('withdraw_funds.html')

# Trading routes
@app.route('/api/assets')
@login_required
def get_assets():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM assets LIMIT 200')
    assets = c.fetchall()
    
    return jsonify([{
        'id': asset['id'],
        'symbol': asset['symbol'],
        'name': asset['name'],
        'type': asset['type'],
        'price': asset['current_price']
    } for asset in assets])



@app.route('/trade/execute', methods=['POST'])
@login_required
def execute_trade():
    try:
        data = request.get_json() or request.form
        asset_type = data.get('asset_type', 'stocks')
        symbol = data.get('symbol', '').strip()
        action = data.get('action', '').strip() or data.get('type', '').strip()
        quantity = float(data.get('quantity', 0))
        price = float(data.get('price', 0))
        
        if not symbol or action not in ['buy', 'sell'] or quantity <= 0 or price <= 0:
            return jsonify({'success': False, 'message': 'Invalid input'})
        
        user_id = session['user_id']
        total_value = quantity * price
        
        conn = get_db()
        conn.execute("BEGIN IMMEDIATE")
        c = conn.cursor()
        
        if action == 'buy':
            wallet = c.execute('SELECT balance FROM wallets WHERE user_id=?', (user_id,)).fetchone()
            if not wallet or wallet['balance'] < total_value:
                conn.close()
                return jsonify({'success': False, 'message': 'Insufficient balance'})
            
            # Update wallet
            c.execute('UPDATE wallets SET balance = balance - ? WHERE user_id=?', (total_value, user_id))
            
            # Check if stock already exists in portfolio
            existing = c.execute(
                'SELECT * FROM portfolio WHERE user_id=? AND symbol=?',
                (user_id, symbol)
            ).fetchone()
            
            if existing:
                new_qty = existing['quantity'] + quantity
                avg_price = ((existing['quantity'] * existing['buy_price']) + (quantity * price)) / new_qty
                c.execute('UPDATE portfolio SET quantity=?, buy_price=?, current_price=? WHERE id=?',
                         (new_qty, avg_price, price, existing['id']))
            else:
                c.execute('INSERT INTO portfolio (user_id, asset_type, symbol, quantity, buy_price, current_price) VALUES (?, ?, ?, ?, ?, ?)',
                         (user_id, asset_type, symbol, quantity, price, price))
            
            # Add transaction
            c.execute('INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)',
                     (user_id, 'trade_buy', total_value, f'Bought {quantity} {symbol}'))
        
        elif action == 'sell':
            holding = c.execute(
                'SELECT * FROM portfolio WHERE user_id=? AND symbol=?',
                (user_id, symbol)
            ).fetchone()

            if not holding or holding['quantity'] < quantity:
                conn.rollback()
                return jsonify({'success': False, 'message': 'Not enough holdings'})

            total_value = quantity * price

            new_qty = holding['quantity'] - quantity
            if new_qty == 0:
                c.execute('DELETE FROM portfolio WHERE id=?', (holding['id'],))
            else:
                c.execute('UPDATE portfolio SET quantity=? WHERE id=?',
                         (new_qty, holding['id']))

            c.execute('UPDATE wallets SET balance = balance + ? WHERE user_id=?',
                     (total_value, user_id))

            c.execute('INSERT INTO transactions (user_id,type,amount,description) VALUES (?,?,?,?)',
                     (user_id,'trade_sell',total_value,f'Sold {quantity} {symbol}'))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'Trade executed: {action} {quantity} {symbol}'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Trade failed: {str(e)}'})

@app.route('/trade/history')
@login_required
def trade_history():
    user_id = session['user_id']
    try:
        conn = get_db()
        trades = conn.execute('SELECT * FROM transactions WHERE user_id=? AND type LIKE "trade_%" ORDER BY timestamp DESC',
                            (user_id,)).fetchall()
        conn.close()
        return render_template('trade_history.html', trades=trades)
    except Exception as e:
        flash('Error loading trade history', 'error')
        return redirect(url_for('trade'))

# Savings routes
@app.route('/savings/add-goal', methods=['GET', 'POST'])
@login_required
def add_savings_goal():
    if request.method == 'POST':
        try:
            goal_name = request.form.get('goal_name', '').strip()
            target_amount = float(request.form.get('target_amount', 0))
            deadline = request.form.get('deadline', '')
            
            if not goal_name or target_amount <= 0:
                flash('Invalid input', 'error')
                return redirect(url_for('add_savings_goal'))
            
            user_id = session['user_id']
            conn = get_db()
            c = conn.cursor()
            
            c.execute('INSERT INTO savings_goals (user_id, goal_name, target_amount, deadline) VALUES (?, ?, ?, ?)',
                     (user_id, goal_name, target_amount, deadline or None))
            
            conn.commit()
            conn.close()
            
            flash('Savings goal created!', 'success')
            return redirect(url_for('savings'))
        except Exception as e:
            flash('Failed to create goal', 'error')
    
    return render_template('add_savings_goal.html')

# PIN and security routes
@app.route('/set-pin', methods=['GET', 'POST'])
@login_required
def set_pin():
    if request.method == 'POST':
        try:
            pin = request.form.get('pin', '').strip()
            confirm_pin = request.form.get('confirm_pin', '').strip()
            
            if not pin or len(pin) < 4 or not pin.isdigit():
                flash('PIN must be 4-6 digits', 'error')
                return redirect(url_for('set_pin'))
            
            if pin != confirm_pin:
                flash('PINs do not match', 'error')
                return redirect(url_for('set_pin'))
            
            user_id = session['user_id']
            pin_hash = generate_password_hash(pin)
            
            conn = get_db()
            c = conn.cursor()
            try:
                c.execute('ALTER TABLE users ADD COLUMN pin_hash TEXT')
            except sqlite3.OperationalError:
                pass  # Column already exists
            c.execute('UPDATE users SET pin_hash = ? WHERE id = ?', (pin_hash, user_id))
            conn.commit()
            conn.close()
            
            flash('PIN set successfully!', 'success')
            return redirect(url_for('profile'))
        except Exception as e:
            flash('Failed to set PIN', 'error')
    
    return render_template('set_pin.html')

# Budget routes
@app.route('/budgets', methods=['GET', 'POST'])
@login_required
def budgets():
    user_id = session['user_id']
    
    if request.method == 'POST':
        try:
            category = request.form.get('category', '').strip()
            monthly_limit = float(request.form.get('monthly_limit', 0))
            
            if not category or monthly_limit <= 0:
                flash('Invalid input', 'error')
                return redirect(url_for('budgets'))
            
            conn = get_db()
            c = conn.cursor()
            c.execute('INSERT INTO budgets (user_id, category, monthly_limit) VALUES (?, ?, ?)',
                     (user_id, category, monthly_limit))
            conn.commit()
            conn.close()
            
            flash('Budget set successfully!', 'success')
        except Exception as e:
            flash('Failed to set budget', 'error')
    
    try:
        conn = get_db()
        all_budgets = conn.execute('SELECT * FROM budgets WHERE user_id=?', (user_id,)).fetchall()
        conn.close()
        return render_template('budgets.html', budgets=all_budgets)
    except Exception as e:
        return render_template('budgets.html', budgets=[])

# Settings routes
@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html')

@app.route('/help')
@login_required
def help_page():
    return render_template('help.html')

# API routes for AJAX calls
@app.route('/api/wallet-balance')
@login_required
def api_wallet_balance():
    try:
        user_id = session['user_id']
        conn = get_db()
        wallet_data = conn.execute('SELECT balance FROM wallets WHERE user_id=?', (user_id,)).fetchone()
        conn.close()
        
        return jsonify({
            'balance': wallet_data['balance'] if wallet_data else 0,
            'main_balance': wallet_data['balance'] if wallet_data else 0,
            'investment_balance': 0,
            'savings_balance': 0
        })
    except Exception as e:
        return jsonify({'balance': 0, 'main_balance': 0, 'investment_balance': 0, 'savings_balance': 0})

@app.route('/api/recent-transactions')
@login_required
def api_recent_transactions():
    try:
        user_id = session['user_id']
        conn = get_db()
        transactions = conn.execute('SELECT * FROM transactions WHERE user_id=? ORDER BY timestamp DESC LIMIT 10',
                                  (user_id,)).fetchall()
        conn.close()
        return jsonify({'transactions': [dict(tx) for tx in transactions]})
    except Exception as e:
        return {'transactions': []}

# Report routes
@app.route('/reports')
@login_required
def reports():
    user_id = session['user_id']
    try:
        conn = get_db()
        
        # Monthly summary
        current_month = datetime.now().strftime('%Y-%m')
        monthly_income = conn.execute('SELECT SUM(amount) as total FROM transactions WHERE user_id=? AND type="deposit" AND strftime("%Y-%m", timestamp)=?',
                                    (user_id, current_month)).fetchone()
        monthly_expenses = conn.execute('SELECT SUM(amount) as total FROM expenses WHERE user_id=? AND strftime("%Y-%m", expense_date)=?',
                                      (user_id, current_month)).fetchone()
        
        conn.close()
        
        return render_template('reports.html', 
                             monthly_income=monthly_income['total'] or 0,
                             monthly_expenses=monthly_expenses['total'] or 0)
    except Exception as e:
        return render_template('reports.html', monthly_income=0, monthly_expenses=0)

# Additional comprehensive routes

# Investment and Portfolio Management
@app.route('/portfolio/add', methods=['GET', 'POST'])
@login_required
def add_investment():
    if request.method == 'POST':
        try:
            asset_type = request.form.get('asset_type', 'stocks')
            symbol = request.form.get('symbol', '').strip().upper()
            quantity = float(request.form.get('quantity', 0))
            buy_price = float(request.form.get('buy_price', 0))
            
            if not symbol or quantity <= 0 or buy_price <= 0:
                flash('Invalid input', 'error')
                return redirect(url_for('add_investment'))
            
            user_id = session['user_id']
            total_cost = quantity * buy_price
            
            conn = get_db()
            c = conn.cursor()
            
            # Check wallet balance
            wallet = c.execute('SELECT balance FROM wallets WHERE user_id=?', (user_id,)).fetchone()
            if not wallet or wallet['balance'] < total_cost:
                flash('Insufficient balance', 'error')
                return redirect(url_for('add_investment'))
            
            # Add to portfolio table
            c.execute('INSERT INTO portfolio (user_id, asset_type, symbol, quantity, buy_price, current_price) VALUES (?, ?, ?, ?, ?, ?)',
                     (user_id, asset_type, symbol, quantity, buy_price, buy_price))
            
            # Update wallet
            c.execute('UPDATE wallets SET balance = balance - ? WHERE user_id=?', (total_cost, user_id))
            
            # Add transaction
            c.execute('INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)',
                     (user_id, 'investment', total_cost, f'Bought {quantity} shares of {symbol}'))
            
            conn.commit()
            conn.close()
            
            flash(f'Investment added: {quantity} shares of {symbol}', 'success')
            return redirect(url_for('portfolio'))
        except Exception as e:
            flash('Failed to add investment', 'error')
    
    return render_template('add_investment.html')

@app.route('/portfolio/sell/<int:investment_id>', methods=['POST'])
@login_required
def sell_investment(investment_id):
    try:
        quantity_to_sell = float(request.form.get('quantity', 0))
        sell_price = float(request.form.get('sell_price', 0))
        
        if quantity_to_sell <= 0 or sell_price <= 0:
            flash('Invalid input', 'error')
            return redirect(url_for('portfolio'))
        
        user_id = session['user_id']
        conn = get_db()
        c = conn.cursor()
        
        # Get investment details
        investment = c.execute('SELECT * FROM portfolio WHERE id=? AND user_id=?', 
                             (investment_id, user_id)).fetchone()
        
        if not investment or investment['quantity'] < quantity_to_sell:
            flash('Invalid sale quantity', 'error')
            return redirect(url_for('portfolio'))
        
        total_value = quantity_to_sell * sell_price
        
        # Update portfolio
        new_quantity = investment['quantity'] - quantity_to_sell
        if new_quantity == 0:
            c.execute('DELETE FROM portfolio WHERE id=?', (investment_id,))
        else:
            c.execute('UPDATE portfolio SET quantity=? WHERE id=?', (new_quantity, investment_id))
        
        # Update wallet
        c.execute('UPDATE wallets SET balance = balance + ? WHERE user_id=?', (total_value, user_id))
        
        # Add transaction
        c.execute('INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)',
                 (user_id, 'sale', total_value, f'Sold {quantity_to_sell} shares of {investment["symbol"]}'))
        
        conn.commit()
        conn.close()
        
        flash(f'Sold {quantity_to_sell} shares for ₹{total_value:.2f}', 'success')
    except Exception as e:
        flash('Sale failed', 'error')
    
    return redirect(url_for('portfolio'))

# Expense Management
@app.route('/expenses/edit/<int:expense_id>', methods=['GET', 'POST'])
@login_required
def edit_expense(expense_id):
    user_id = session['user_id']
    
    if request.method == 'POST':
        try:
            category = request.form.get('category', '').strip()
            amount = float(request.form.get('amount', 0))
            notes = request.form.get('notes', '').strip()
            expense_date = request.form.get('expense_date', '')
            
            if not category or amount <= 0:
                flash('Invalid input', 'error')
                return redirect(url_for('edit_expense', expense_id=expense_id))
            
            conn = get_db()
            c = conn.cursor()
            
            # Get original expense
            original = c.execute('SELECT * FROM expenses WHERE id=? AND user_id=?', 
                               (expense_id, user_id)).fetchone()
            
            if not original:
                flash('Expense not found', 'error')
                return redirect(url_for('expenses'))
            
            # Calculate difference
            difference = amount - original['amount']
            
            # Check if user has enough balance for increase
            if difference > 0:
                wallet = c.execute('SELECT balance FROM wallets WHERE user_id=?', (user_id,)).fetchone()
                if not wallet or wallet['balance'] < difference:
                    flash('Insufficient balance for increase', 'error')
                    return redirect(url_for('edit_expense', expense_id=expense_id))
            
            # Update expense
            c.execute('UPDATE expenses SET category=?, amount=?, notes=?, expense_date=? WHERE id=?',
                     (category, amount, notes, expense_date, expense_id))
            
            # Update wallet balance
            c.execute('UPDATE wallets SET balance = balance - ? WHERE user_id=?', (difference, user_id))
            
            # Add transaction for the difference
            if difference != 0:
                desc = f'Expense adjustment: {category}'
                c.execute('INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)',
                         (user_id, 'expense_adjustment', abs(difference), desc))
            
            conn.commit()
            conn.close()
            
            flash('Expense updated successfully', 'success')
            return redirect(url_for('expenses'))
        except Exception as e:
            flash('Failed to update expense', 'error')
    
    try:
        conn = get_db()
        expense = conn.execute('SELECT * FROM expenses WHERE id=? AND user_id=?', 
                             (expense_id, user_id)).fetchone()
        conn.close()
        
        if not expense:
            flash('Expense not found', 'error')
            return redirect(url_for('expenses'))
        
        return render_template('edit_expense.html', expense=expense)
    except Exception as e:
        flash('Error loading expense', 'error')
        return redirect(url_for('expenses'))

@app.route('/expenses/delete/<int:expense_id>', methods=['POST'])
@login_required
def delete_expense(expense_id):
    try:
        user_id = session['user_id']
        conn = get_db()
        c = conn.cursor()
        
        # Get expense details
        expense = c.execute('SELECT * FROM expenses WHERE id=? AND user_id=?', 
                          (expense_id, user_id)).fetchone()
        
        if not expense:
            flash('Expense not found', 'error')
            return redirect(url_for('expenses'))
        
        # Delete expense
        c.execute('DELETE FROM expenses WHERE id=?', (expense_id,))
        
        # Refund to wallet
        c.execute('UPDATE wallets SET balance = balance + ? WHERE user_id=?', 
                 (expense['amount'], user_id))
        
        # Add refund transaction
        c.execute('INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)',
                 (user_id, 'refund', expense['amount'], f'Deleted expense: {expense["category"]}'))
        
        conn.commit()
        conn.close()
        
        flash('Expense deleted and amount refunded', 'success')
    except Exception as e:
        flash('Failed to delete expense', 'error')
    
    return redirect(url_for('expenses'))

# Savings Goal Management
@app.route('/savings/contribute/<int:goal_id>', methods=['POST'])
@login_required
def contribute_to_goal(goal_id):
    try:
        amount = float(request.form.get('amount', 0))
        
        if amount <= 0:
            flash('Invalid amount', 'error')
            return redirect(url_for('savings'))
        
        user_id = session['user_id']
        conn = get_db()
        c = conn.cursor()
        
        # Check wallet balance
        wallet = c.execute('SELECT balance FROM wallets WHERE user_id=?', (user_id,)).fetchone()
        if not wallet or wallet['balance'] < amount:
            flash('Insufficient balance', 'error')
            return redirect(url_for('savings'))
        
        # Get goal details
        goal = c.execute('SELECT * FROM savings_goals WHERE id=? AND user_id=?', 
                        (goal_id, user_id)).fetchone()
        
        if not goal:
            flash('Goal not found', 'error')
            return redirect(url_for('savings'))
        
        # Update goal
        new_amount = goal['current_amount'] + amount
        c.execute('UPDATE savings_goals SET current_amount=? WHERE id=?', (new_amount, goal_id))
        
        # Update wallet
        c.execute('UPDATE wallets SET balance = balance - ? WHERE user_id=?', (amount, user_id))
        
        # Add transaction
        c.execute('INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)',
                 (user_id, 'savings', amount, f'Contribution to {goal["goal_name"]}'))
        
        conn.commit()
        conn.close()
        
        flash(f'₹{amount:.2f} contributed to {goal["goal_name"]}', 'success')
    except Exception as e:
        flash('Contribution failed', 'error')
    
    return redirect(url_for('savings'))

@app.route('/savings/withdraw/<int:goal_id>', methods=['POST'])
@login_required
def withdraw_from_goal(goal_id):
    try:
        amount = float(request.form.get('amount', 0))
        
        if amount <= 0:
            flash('Invalid amount', 'error')
            return redirect(url_for('savings'))
        
        user_id = session['user_id']
        conn = get_db()
        c = conn.cursor()
        
        # Get goal details
        goal = c.execute('SELECT * FROM savings_goals WHERE id=? AND user_id=?', 
                        (goal_id, user_id)).fetchone()
        
        if not goal or goal['current_amount'] < amount:
            flash('Insufficient savings amount', 'error')
            return redirect(url_for('savings'))
        
        # Update goal
        new_amount = goal['current_amount'] - amount
        c.execute('UPDATE savings_goals SET current_amount=? WHERE id=?', (new_amount, goal_id))
        
        # Update wallet
        c.execute('UPDATE wallets SET balance = balance + ? WHERE user_id=?', (amount, user_id))
        
        # Add transaction
        c.execute('INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)',
                 (user_id, 'savings_withdrawal', amount, f'Withdrawal from {goal["goal_name"]}'))
        
        conn.commit()
        conn.close()
        
        flash(f'₹{amount:.2f} withdrawn from {goal["goal_name"]}', 'success')
    except Exception as e:
        flash('Withdrawal failed', 'error')
    
    return redirect(url_for('savings'))

# User Profile Management
@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    user_id = session['user_id']
    
    if request.method == 'POST':
        try:
            username = request.form.get('username', '').strip()
            email = request.form.get('email', '').strip()
            
            if not username or not validate_email(email):
                flash('Invalid input', 'error')
                return redirect(url_for('edit_profile'))
            
            conn = get_db()
            c = conn.cursor()
            
            # Check if username/email already exists for other users
            existing = c.execute('SELECT id FROM users WHERE (username=? OR email=?) AND id!=?', 
                               (username, email, user_id)).fetchone()
            
            if existing:
                flash('Username or email already exists', 'error')
                return redirect(url_for('edit_profile'))
            
            # Update user
            c.execute('UPDATE users SET username=?, email=? WHERE id=?', 
                     (username, email, user_id))
            
            conn.commit()
            conn.close()
            
            session['username'] = username
            flash('Profile updated successfully', 'success')
            return redirect(url_for('profile'))
        except Exception as e:
            flash('Failed to update profile', 'error')
    
    try:
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        conn.close()
        return render_template('edit_profile.html', user=user)
    except Exception as e:
        flash('Error loading profile', 'error')
        return redirect(url_for('profile'))

@app.route('/profile/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        try:
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')
            
            if not current_password or not new_password or not confirm_password:
                flash('All fields are required', 'error')
                return redirect(url_for('change_password'))
            
            if new_password != confirm_password:
                flash('New passwords do not match', 'error')
                return redirect(url_for('change_password'))
            
            if not validate_password(new_password):
                flash('Password must be at least 8 characters with uppercase, lowercase, and number', 'error')
                return redirect(url_for('change_password'))
            
            user_id = session['user_id']
            conn = get_db()
            c = conn.cursor()
            
            # Verify current password
            user = c.execute('SELECT password_hash FROM users WHERE id=?', (user_id,)).fetchone()
            
            if not user or not check_password_hash(user['password_hash'], current_password):
                flash('Current password is incorrect', 'error')
                return redirect(url_for('change_password'))
            
            # Update password
            new_hash = generate_password_hash(new_password)
            c.execute('UPDATE users SET password_hash=? WHERE id=?', (new_hash, user_id))
            
            conn.commit()
            conn.close()
            
            flash('Password changed successfully', 'success')
            return redirect(url_for('profile'))
        except Exception as e:
            flash('Failed to change password', 'error')
    
    return render_template('change_password.html')

# Advanced Analytics
@app.route('/analytics/detailed')
@login_required
def detailed_analytics():
    user_id = session['user_id']
    
    try:
        conn = get_db()
        
        # Monthly expense trends (last 12 months)
        monthly_trends = conn.execute('''
            SELECT strftime('%Y-%m', expense_date) as month, 
                   SUM(amount) as total,
                   COUNT(*) as count
            FROM expenses 
            WHERE user_id=? AND expense_date >= date('now', '-12 months')
            GROUP BY month
            ORDER BY month
        ''', (user_id,)).fetchall()
        
        # Category-wise spending
        category_spending = conn.execute('''
            SELECT category, 
                   SUM(amount) as total,
                   COUNT(*) as count,
                   AVG(amount) as average
            FROM expenses 
            WHERE user_id=?
            GROUP BY category
            ORDER BY total DESC
        ''', (user_id,)).fetchall()
        
        # Income vs Expenses
        income_data = conn.execute('''
            SELECT SUM(amount) as total_income
            FROM transactions 
            WHERE user_id=? AND type IN ('deposit', 'sale', 'savings_withdrawal')
        ''', (user_id,)).fetchone()
        
        expense_data = conn.execute('''
            SELECT SUM(amount) as total_expenses
            FROM expenses 
            WHERE user_id=?
        ''', (user_id,)).fetchone()
        
        conn.close()
        
        return render_template('detailed_analytics.html',
                             monthly_trends=monthly_trends,
                             category_spending=category_spending,
                             total_income=income_data['total_income'] or 0,
                             total_expenses=expense_data['total_expenses'] or 0)
    except Exception as e:
        flash('Error loading analytics', 'error')
        return redirect(url_for('analytics'))

# Transaction Management
@app.route('/transactions')
@login_required
def all_transactions():
    user_id = session['user_id']
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    try:
        conn = get_db()
        
        # Get total count
        total = conn.execute('SELECT COUNT(*) as count FROM transactions WHERE user_id=?', 
                           (user_id,)).fetchone()['count']
        
        # Get paginated transactions
        offset = (page - 1) * per_page
        transactions = conn.execute('''
            SELECT * FROM transactions 
            WHERE user_id=? 
            ORDER BY timestamp DESC 
            LIMIT ? OFFSET ?
        ''', (user_id, per_page, offset)).fetchall()
        
        conn.close()
        
        # Calculate pagination info
        total_pages = (total + per_page - 1) // per_page
        has_prev = page > 1
        has_next = page < total_pages
        
        return render_template('all_transactions.html',
                             transactions=transactions,
                             page=page,
                             total_pages=total_pages,
                             has_prev=has_prev,
                             has_next=has_next)
    except Exception as e:
        flash('Error loading transactions', 'error')
        return redirect(url_for('dashboard'))

# Export Data
@app.route('/export/transactions')
@login_required
def export_transactions():
    try:
        user_id = session['user_id']
        conn = get_db()
        
        transactions = conn.execute('''
            SELECT type, amount, description, timestamp
            FROM transactions 
            WHERE user_id=? 
            ORDER BY timestamp DESC
        ''', (user_id,)).fetchall()
        
        conn.close()
        
        # Create CSV content
        import io
        import csv
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Type', 'Amount', 'Description', 'Date'])
        
        for tx in transactions:
            writer.writerow([tx['type'], tx['amount'], tx['description'], tx['timestamp']])
        
        from flask import Response
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=transactions.csv'}
        )
    except Exception as e:
        flash('Export failed', 'error')
        return redirect(url_for('all_transactions'))

@app.route('/export/expenses')
@login_required
def export_expenses():
    try:
        user_id = session['user_id']
        conn = get_db()
        
        expenses = conn.execute('''
            SELECT category, amount, notes, expense_date
            FROM expenses 
            WHERE user_id=? 
            ORDER BY expense_date DESC
        ''', (user_id,)).fetchall()
        
        conn.close()
        
        # Create CSV content
        import io
        import csv
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Category', 'Amount', 'Notes', 'Date'])
        
        for expense in expenses:
            writer.writerow([expense['category'], expense['amount'], expense['notes'], expense['expense_date']])
        
        from flask import Response
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=expenses.csv'}
        )
    except Exception as e:
        flash('Export failed', 'error')
        return redirect(url_for('expenses'))

# API endpoints from temp file
@app.route('/api/wallet')
@login_required
def api_wallet():
    user_id = session['user_id']
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT balance FROM wallets WHERE user_id = ?', (user_id,))
    wallet = c.fetchone()
    conn.close()
    
    return jsonify({'balance': wallet['balance'] if wallet else 0})

@app.route('/api/expenses', methods=['GET', 'POST'])
@login_required
def api_expenses():
    user_id = session['user_id']
    
    if request.method == 'POST':
        data = request.get_json()
        conn = get_db()
        c = conn.cursor()
        c.execute('INSERT INTO expenses (user_id, category, amount, expense_date, notes) VALUES (?, ?, ?, ?, ?)',
                 (user_id, data['category'], data['amount'], data['date'], data.get('description', '')))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM expenses WHERE user_id = ? ORDER BY expense_date DESC', (user_id,))
    expenses = c.fetchall()
    conn.close()
    
    return jsonify([{
        'id': exp['id'],
        'category': exp['category'],
        'amount': exp['amount'],
        'date': exp['expense_date'],
        'description': exp['notes']
    } for exp in expenses])

@app.route('/api/trade', methods=['POST'])
@login_required
def api_trade():
    try:
        data = request.get_json()
        symbol = data['symbol']
        trade_type = data['type']
        quantity = int(data['quantity'])
        price = float(data['price'])
        total = quantity * price
        
        user_id = session['user_id']
        conn = get_db()
        c = conn.cursor()
        
        if trade_type == 'buy':
            # Check balance
            wallet = c.execute('SELECT balance FROM wallets WHERE user_id=?', (user_id,)).fetchone()
            if not wallet or wallet['balance'] < total:
                conn.close()
                return jsonify({'success': False, 'message': 'Insufficient funds'})
            
            # Update wallet
            c.execute('UPDATE wallets SET balance = balance - ? WHERE user_id=?', (total, user_id))
            
            # Add to portfolio
            c.execute('INSERT INTO portfolio (user_id, symbol, quantity, buy_price, current_price) VALUES (?, ?, ?, ?, ?)',
                     (user_id, symbol, quantity, price, price))
        
        # Add transaction
        c.execute('INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)',
                 (user_id, f'trade_{trade_type}', total, f'{trade_type.title()} {quantity} {symbol}'))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/test-ollama')
@login_required
def test_ollama():
    try:
        response = requests.post(
            'http://localhost:11434/api/generate',
            json={
                'model': 'llama3',
                'prompt': 'Say hello in one word.',
                'stream': False
            },
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            return jsonify({
                'status': 'success',
                'response': data.get('response', 'No response'),
                'model': 'llama3'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': f'HTTP {response.status_code}',
                'response': response.text
            })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        })

# =========================
# AI CHAT API
# =========================
@app.route('/api/chat', methods=['POST'])
@login_required
def chat_with_ai():
    try:
        data = request.get_json()
        user_message = data.get('message', '')
        
        print(f"Received chat message: {user_message}")
        
        if not user_message:
            return jsonify({'error': 'No message provided'})
        
        user_id = session['user_id']
        conn = get_db()
        
        wallet = conn.execute(
            'SELECT balance FROM wallets WHERE user_id=?', (user_id,)
        ).fetchone()
        recent_expenses = conn.execute(
            'SELECT category, amount FROM expenses WHERE user_id=? ORDER BY expense_date DESC LIMIT 5',
            (user_id,)
        ).fetchall()
        portfolio = conn.execute(
            'SELECT symbol, quantity FROM portfolio WHERE user_id=?', (user_id,)
        ).fetchall()
        
        conn.close()
        
        context = f"""You are a financial advisor chatbot. User has:
- Wallet balance: ₹{wallet['balance'] if wallet else 0}
- Recent expenses: {[dict(exp) for exp in recent_expenses]}
- Portfolio: {[dict(p) for p in portfolio]}

Provide helpful financial advice. Keep responses under 100 words."""
        
        print(f"Sending to Ollama: {context}")
        
        try:
            print(f"Testing Ollama connection...")
            test_response = requests.get('http://localhost:11434/api/tags', timeout=5)
            print(f"Ollama tags response: {test_response.status_code}")
            if test_response.status_code != 200:
                return jsonify({'error': 'Ollama service not responding properly'})
        except Exception as e:
            print(f"Ollama connection test failed: {e}")
            return jsonify({'error': 'Cannot connect to Ollama service'})
        
        ollama_response = requests.post(
            'http://localhost:11434/api/generate', 
            json={
                'model': 'llama3',
                'prompt': f"{context}\n\nUser: {user_message}\nAssistant:",
                'stream': False
            },
            timeout=30
        )
        
        print(f"Ollama response status: {ollama_response.status_code}")
        
        if ollama_response.status_code == 200:
            response_data = ollama_response.json()
            ai_response = response_data.get('response', 'Sorry, I could not process your request.')
            print(f"AI Response: {ai_response[:100]}...")
            
            return jsonify({'response': ai_response})
        else:
            print(f"Ollama error: {ollama_response.text}")
            return jsonify({'error': 'AI service unavailable'})
            
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        return jsonify({'error': 'Ollama not running. Please start Ollama service.'})
    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({'error': f'Chat error: {str(e)}'})

# =========================
# AI FINANCIAL ADVISOR API
# =========================
@app.route('/api/ai-advisor')
@login_required
def ai_advisor():
    try:
        user_id = session['user_id']
        conn = get_db()
        
        wallet = conn.execute(
            'SELECT balance FROM wallets WHERE user_id=?', (user_id,)
        ).fetchone()
        
        monthly_expenses = conn.execute('''
            SELECT category, SUM(amount) as total 
            FROM expenses aa
            WHERE user_id=? AND expense_date >= date('now', '-30 days')
            GROUP BY category
        ''', (user_id,)).fetchall()
        
        portfolio = conn.execute(
            'SELECT symbol, quantity, buy_price, current_price FROM portfolio WHERE user_id=?',
            (user_id,)
        ).fetchall()
        
        recent_transactions = conn.execute(
            'SELECT type, amount FROM transactions WHERE user_id=? ORDER BY timestamp DESC LIMIT 10',
            (user_id,)
        ).fetchall()
        
        conn.close()
        
        balance = wallet['balance'] if wallet else 0
        total_expenses = sum(exp['total'] for exp in monthly_expenses)
        expense_breakdown = {exp['category']: exp['total'] for exp in monthly_expenses}
        portfolio_value = sum(p['quantity'] * p['current_price'] for p in portfolio)
        
        context = f"""Analyze this user's financial situation and provide specific advice:

Current Balance: ₹{balance}
Monthly Expenses: ₹{total_expenses}
Expense Categories: {expense_breakdown}
Portfolio Value: ₹{portfolio_value}
Portfolio Holdings: {[{'symbol': p['symbol'], 'qty': p['quantity'], 'value': p['quantity'] * p['current_price']} for p in portfolio]}

Provide 3 specific financial advice points and 2 investment suggestions. Be concise and actionable."""
        
        response = requests.post(
            'http://localhost:11434/api/generate',
            json={
                'model': 'llama3',
                'prompt': context,
                'stream': False
            },
            timeout=30
        )
        
        if response.status_code == 200:
            ai_response = response.json().get('response', '')
            
            lines = [line.strip() for line in ai_response.split('\n') if line.strip()]
            
            finance_advice = []
            market_advice = []
            
            for line in lines[:5]:
                if any(word in line.lower() for word in ['buy', 'sell', 'invest', 'stock', 'portfolio']):
                    market_advice.append(line)
                else:
                    finance_advice.append(line)
            
            if not finance_advice:
                finance_advice = [
                    "Monitor your spending patterns closely.",
                    "Consider building an emergency fund."
                ]
            if not market_advice:
                market_advice = [
                    "Diversify your investment portfolio.",
                    "Consider long-term investment strategies."
                ]
            
            return jsonify({
                'finance_advice': finance_advice[:3],
                'market_advice': market_advice[:2]
            })
        else:
            raise Exception("AI service error")
            
    except requests.exceptions.RequestException:
        return jsonify({
            'finance_advice': ["AI advisor temporarily unavailable. Please try again later."],
            'market_advice': ["AI advisor temporarily unavailable. Please try again later."]
        })
    except Exception as e:
        return jsonify({
            'finance_advice': [f"Error getting advice: {str(e)}"],
            'market_advice': ["Please check your financial data and try again."]
        })

@app.route('/api/market-data/<category>')
@login_required
@limiter.limit("20/minute")
def get_market_data(category):
    try:
        # Check cache first
        cached = get_cached(f"market_{category}")
        if cached:
            return jsonify(cached)
        
        if category == 'crypto':
            crypto_data = []
            if CoinGeckoAPI:
                try:
                    cg = CoinGeckoAPI()
                    coins = cg.get_coins_markets(vs_currency='usd', order='market_cap_desc', per_page=20, page=1)
                    for coin in coins:
                        crypto_data.append({
                            'symbol': coin['symbol'].upper(),
                            'name': coin['name'],
                            'price': coin['current_price'],
                            'change_24h': coin['price_change_percentage_24h'] or 0,
                            'market_cap': coin['market_cap'],
                            'id': coin['id']
                        })
                except:
                    pass
            set_cache(f"market_{category}", crypto_data)
            return jsonify(crypto_data)
        
        elif category == 'stocks':
            stock_data = []
            stock_symbols = ['RELIANCE.NS', 'TCS.NS', 'INFY.NS', 'HDFCBANK.NS', 'ICICIBANK.NS', 
                           'SBIN.NS', 'BHARTIARTL.NS', 'ITC.NS', 'LT.NS', 'MARUTI.NS']
            
            for yf_symbol in stock_symbols:
                try:
                    current_price = get_real_price(yf_symbol.replace('.NS', ''), yf_symbol, 100)
                    stock_data.append({
                        'symbol': yf_symbol.replace('.NS', ''),
                        'name': f"{yf_symbol.replace('.NS', '')} Ltd",
                        'price': round(current_price, 2),
                        'change_24h': 0,
                        'market_cap': 0
                    })
                except:
                    continue
            
            set_cache(f"market_{category}", stock_data)
            return jsonify(stock_data)
        
        elif category == 'commodities':
            commodity_data = []
            commodities = {'GOLD': 'GC=F', 'SILVER': 'SI=F', 'CRUDEOIL': 'CL=F', 'COPPER': 'HG=F'}
            
            for symbol, yf_symbol in commodities.items():
                try:
                    usd_price = get_real_price(symbol, yf_symbol, 50)
                    inr_price = usd_price * 83
                    commodity_data.append({
                        'symbol': symbol,
                        'name': f'{symbol} Futures',
                        'price': round(inr_price, 2),
                        'change_24h': 0,
                        'market_cap': 0
                    })
                except:
                    continue
            
            set_cache(f"market_{category}", commodity_data)
            return jsonify(commodity_data)
        
        else:
            return jsonify({'error': 'Invalid category'})
    
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/chart/<category>/<symbol>/<period>')
@login_required
@limiter.limit("30/minute")
def get_chart_data(category, symbol, period):
    try:
        if category == 'crypto':
            if CoinGeckoAPI:
                cg = CoinGeckoAPI()
                # Map period to days
                days_map = {'1D': 1, '1W': 7, '1M': 30, '3M': 90, '1Y': 365}
                days = days_map.get(period, 7)
                
                # Find coin ID by symbol
                coins_list = cg.get_coins_list()
                coin_id = None
                for coin in coins_list:
                    if coin['symbol'].upper() == symbol.upper():
                        coin_id = coin['id']
                        break
                
                if coin_id:
                    chart_data = cg.get_coin_market_chart_by_id(id=coin_id, vs_currency='usd', days=days)
                    prices = chart_data['prices']
                    
                    # Sample data points based on period
                    step = max(1, len(prices) // 50)  # Max 50 points
                    
                    formatted_data = {
                        'labels': [datetime.fromtimestamp(price[0]/1000).strftime('%m/%d %H:%M' if days <= 7 else '%m/%d') for price in prices[::step]],
                        'prices': [price[1] for price in prices[::step]]
                    }
                    
                    return jsonify(formatted_data)
            
            # Fallback mock data for crypto
            return generate_mock_chart_data(symbol, period, 'crypto')
        
        elif category == 'stocks':
            try:
                # Expanded stock symbol mapping
                stock_map = {
                    'HDFCBANK': 'HDFCBANK.NS', 'ICICIBANK': 'ICICIBANK.NS', 'KOTAKBANK': 'KOTAKBANK.NS',
                    'SBIN': 'SBIN.NS', 'AXISBANK': 'AXISBANK.NS', 'INDUSINDBK': 'INDUSINDBK.NS',
                    'BAJFINANCE': 'BAJFINANCE.NS', 'BAJAJFINSV': 'BAJAJFINSV.NS',
                    'TCS': 'TCS.NS', 'INFY': 'INFY.NS', 'HCLTECH': 'HCLTECH.NS',
                    'WIPRO': 'WIPRO.NS', 'TECHM': 'TECHM.NS', 'LTI': 'LTIM.NS',
                    'RELIANCE': 'RELIANCE.NS', 'ONGC': 'ONGC.NS', 'IOC': 'IOC.NS',
                    'BPCL': 'BPCL.NS', 'HINDPETRO': 'HINDPETRO.NS',
                    'HINDUNILVR': 'HINDUNILVR.NS', 'ITC': 'ITC.NS', 'NESTLEIND': 'NESTLEIND.NS',
                    'BRITANNIA': 'BRITANNIA.NS', 'DABUR': 'DABUR.NS',
                    'MARUTI': 'MARUTI.NS', 'TATAMOTORS': 'TATAMOTORS.NS', 'M&M': 'M&M.NS',
                    'BAJAJ-AUTO': 'BAJAJ-AUTO.NS', 'EICHERMOT': 'EICHERMOT.NS',
                    'BHARTIARTL': 'BHARTIARTL.NS', 'JIOFINANCE': 'JIOFINANCE.NS',
                    'LT': 'LT.NS', 'ULTRACEMCO': 'ULTRACEMCO.NS', 'GRASIM': 'GRASIM.NS',
                    'ADANIPORTS': 'ADANIPORTS.NS', 'POWERGRID': 'POWERGRID.NS',
                    'SUNPHARMA': 'SUNPHARMA.NS', 'DRREDDY': 'DRREDDY.NS', 'CIPLA': 'CIPLA.NS',
                    'DIVISLAB': 'DIVISLAB.NS', 'APOLLOHOSP': 'APOLLOHOSP.NS',
                    'TATASTEEL': 'TATASTEEL.NS', 'HINDALCO': 'HINDALCO.NS', 'JSWSTEEL': 'JSWSTEEL.NS',
                    'COALINDIA': 'COALINDIA.NS', 'VEDL': 'VEDL.NS',
                    'ASIANPAINT': 'ASIANPAINTS.NS', 'TITAN': 'TITAN.NS', 'NTPC': 'NTPC.NS'
                }
                
                yf_symbol = stock_map.get(symbol, f"{symbol}.NS")
                ticker = yf.Ticker(yf_symbol)
                
                # Map period to yfinance period
                period_map = {'1D': '1d', '1W': '5d', '1M': '1mo', '3M': '3mo', '1Y': '1y'}
                yf_period = period_map.get(period, '5d')
                
                hist = ticker.history(period=yf_period, interval='1h' if period == '1D' else '1d')
                
                if not hist.empty:
                    labels = []
                    prices = hist['Close'].tolist()
                    
                    for i, date in enumerate(hist.index):
                        if period == '1D':
                            labels.append(date.strftime('%H:%M'))
                        else:
                            labels.append(date.strftime('%m/%d'))
                    
                    return jsonify({'labels': labels, 'prices': prices})
            except:
                pass
            return generate_mock_chart_data(symbol, period, 'stocks')
        
        elif category == 'commodities':
            try:
                # Map commodity symbols
                commodity_map = {
                    'GOLD': 'GC=F', 'SILVER': 'SI=F', 'PLATINUM': 'PL=F', 'PALLADIUM': 'PA=F',
                    'CRUDEOIL': 'CL=F', 'BRENTOIL': 'BZ=F', 'NATURALGAS': 'NG=F', 'HEATING_OIL': 'HO=F',
                    'GASOLINE': 'RB=F', 'COPPER': 'HG=F', 'WHEAT': 'ZW=F',
                    'CORN': 'ZC=F', 'SOYBEANS': 'ZS=F', 'SUGAR': 'SB=F',
                    'COFFEE': 'KC=F', 'COCOA': 'CC=F', 'COTTON': 'CT=F', 'CATTLE': 'LE=F', 'HOGS': 'HE=F'
                }
                
                yf_symbol = commodity_map.get(symbol)
                if yf_symbol:
                    ticker = yf.Ticker(yf_symbol)
                    
                    period_map = {'1D': '1d', '1W': '5d', '1M': '1mo', '3M': '3mo', '1Y': '1y'}
                    yf_period = period_map.get(period, '5d')
                    
                    hist = ticker.history(period=yf_period, interval='1h' if period == '1D' else '1d')
                    
                    if not hist.empty:
                        labels = []
                        prices = [p * 83 for p in hist['Close'].tolist()]  # Convert to INR
                        
                        for i, date in enumerate(hist.index):
                            if period == '1D':
                                labels.append(date.strftime('%H:%M'))
                            else:
                                labels.append(date.strftime('%m/%d'))
                        
                        return jsonify({'labels': labels, 'prices': prices})
            except:
                pass
            return generate_mock_chart_data(symbol, period, 'commodities')
        
        else:
            return jsonify({'error': 'Invalid category'})
    
    except Exception as e:
        return jsonify({'error': str(e)})

def generate_mock_chart_data(symbol, period, category):
    return jsonify({'labels': [], 'prices': []})

@app.errorhandler(Exception)
def handle_all_errors(e):
    logger.exception("Unhandled error")
    return "Internal server error", 500

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

if __name__ == '__main__':
    init_db()
    # Production settings
    app.run(debug=False, host='localhost', port=5000)

@app.route('/api/chat', methods=['POST'])
def chat():
    if not check_ollama_service():
        return jsonify({'response': get_fallback_response('')}), 200
    
    try:
        data = request.get_json()
        message = data.get('message', '')
        
        # Use llama3:latest model
        response = requests.post('http://localhost:11434/api/generate', 
                               json={
                                   'model': 'llama3:latest', 
                                   'prompt': message,
                                   'stream': False
                               })
        
        if response.status_code == 200:
            result = response.json()
            return jsonify({'response': result.get('response', 'No response')})
        else:
            return jsonify({'response': get_fallback_response(message)})
            
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return jsonify({'response': get_fallback_response('')}), 200