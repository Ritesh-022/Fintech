from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import sqlite3
import hashlib
import datetime
import json
import random

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'

def init_db():
    conn = sqlite3.connect('databse/finance.db')
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Wallets table
    c.execute('''CREATE TABLE IF NOT EXISTS wallets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        balance REAL DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )''')
    
    # Expenses table
    c.execute('''CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        category TEXT NOT NULL,
        amount REAL NOT NULL,
        date TEXT NOT NULL,
        description TEXT,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )''')
    
    # Trades table
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        symbol TEXT NOT NULL,
        type TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        price REAL NOT NULL,
        total REAL NOT NULL,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )''')
    
    conn.commit()
    conn.close()

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()
        
        conn = sqlite3.connect('databse/finance.db')
        c = conn.cursor()
        c.execute('SELECT id FROM users WHERE username = ? AND password = ?', (username, password))
        user = c.fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user[0]
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Invalid credentials')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = hashlib.sha256(request.form['password'].encode()).hexdigest()
        
        conn = sqlite3.connect('databse/finance.db')
        c = conn.cursor()
        try:
            c.execute('INSERT INTO users (username, email, password) VALUES (?, ?, ?)', 
                     (username, email, password))
            user_id = c.lastrowid
            c.execute('INSERT INTO wallets (user_id, balance) VALUES (?, ?)', (user_id, 10000))
            conn.commit()
            session['user_id'] = user_id
            return redirect(url_for('index'))
        except sqlite3.IntegrityError:
            return render_template('register.html', error='Username or email already exists')
        finally:
            conn.close()
    
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/trade')
def trade():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('trade.html')

@app.route('/expenses')
def expenses():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('expenses.html')

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('profile.html')

@app.route('/learn')
def learn():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('learn.html')

# API Routes
@app.route('/api/wallet')
def get_wallet():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    conn = sqlite3.connect('databse/finance.db')
    c = conn.cursor()
    c.execute('SELECT balance FROM wallets WHERE user_id = ?', (session['user_id'],))
    balance = c.fetchone()
    conn.close()
    
    return jsonify({'balance': balance[0] if balance else 0})

@app.route('/api/expenses', methods=['GET', 'POST'])
def handle_expenses():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    conn = sqlite3.connect('databse/finance.db')
    c = conn.cursor()
    
    if request.method == 'POST':
        data = request.json
        c.execute('INSERT INTO expenses (user_id, category, amount, date, description) VALUES (?, ?, ?, ?, ?)',
                 (session['user_id'], data['category'], data['amount'], data['date'], data['description']))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    
    c.execute('SELECT id, category, amount, date, description FROM expenses WHERE user_id = ? ORDER BY date DESC',
             (session['user_id'],))
    expenses = c.fetchall()
    conn.close()
    
    return jsonify([{'id': e[0], 'category': e[1], 'amount': e[2], 'date': e[3], 'description': e[4]} for e in expenses])

@app.route('/api/expenses/<int:expense_id>', methods=['PUT', 'DELETE'])
def handle_expense(expense_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    conn = sqlite3.connect('databse/finance.db')
    c = conn.cursor()
    
    if request.method == 'PUT':
        data = request.json
        c.execute('UPDATE expenses SET category = ?, amount = ?, date = ?, description = ? WHERE id = ? AND user_id = ?',
                 (data['category'], data['amount'], data['date'], data['description'], expense_id, session['user_id']))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    
    elif request.method == 'DELETE':
        c.execute('DELETE FROM expenses WHERE id = ? AND user_id = ?', (expense_id, session['user_id']))
        conn.commit()
        conn.close()
        return jsonify({'success': True})

@app.route('/api/expenses/weekly')
def weekly_expenses():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    conn = sqlite3.connect('databse/finance.db')
    c = conn.cursor()
    c.execute('''SELECT category, SUM(amount) FROM expenses 
                 WHERE user_id = ? AND date >= date('now', '-7 days') 
                 GROUP BY category''', (session['user_id'],))
    data = c.fetchall()
    conn.close()
    
    return jsonify({category: amount for category, amount in data})

@app.route('/api/trade', methods=['POST'])
def execute_trade():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.json
    symbol = data['symbol']
    trade_type = data['type']
    quantity = int(data['quantity'])
    price = float(data['price'])
    total = quantity * price
    
    conn = sqlite3.connect('databse/finance.db')
    c = conn.cursor()
    
    # Check wallet balance for buy orders
    if trade_type == 'buy':
        c.execute('SELECT balance FROM wallets WHERE user_id = ?', (session['user_id'],))
        balance = c.fetchone()[0]
        if balance < total:
            conn.close()
            return jsonify({'error': 'Insufficient funds'}), 400
        
        # Update wallet balance
        c.execute('UPDATE wallets SET balance = balance - ? WHERE user_id = ?', (total, session['user_id']))
    else:
        # For sell orders, add to wallet balance
        c.execute('UPDATE wallets SET balance = balance + ? WHERE user_id = ?', (total, session['user_id']))
    
    # Record trade
    c.execute('INSERT INTO trades (user_id, symbol, type, quantity, price, total) VALUES (?, ?, ?, ?, ?, ?)',
             (session['user_id'], symbol, trade_type, quantity, price, total))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': f'{trade_type.title()} order executed successfully'})

@app.route('/api/market-data')
def market_data():
    # Mock market data
    stocks = ['AAPL', 'GOOGL', 'MSFT', 'TSLA', 'AMZN']
    crypto = ['BTC', 'ETH', 'ADA', 'DOT', 'SOL']
    
    data = {}
    for symbol in stocks + crypto:
        data[symbol] = {
            'price': round(random.uniform(50, 500), 2),
            'change': round(random.uniform(-5, 5), 2)
        }
    
    return jsonify(data)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)