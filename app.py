from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db_connection, init_db
from datetime import datetime
import os
import secrets
import re

app = Flask(__name__)
app.secret_key = os.environ.get('SESSION_SECRET', 'dev-secret-key-change-in-production')

init_db()

def generate_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(16)
    return session['csrf_token']

def validate_csrf_token(token):
    return token == session.get('csrf_token')

app.jinja_env.globals['csrf_token'] = generate_csrf_token

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        csrf_token = request.form.get('csrf_token')
        if not validate_csrf_token(csrf_token):
            flash('Invalid security token. Please try again.', 'danger')
            return redirect(url_for('signup'))
            
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        if not username or not email or not password:
            flash('All fields are required!', 'danger')
            return redirect(url_for('signup'))
        
        password_hash = generate_password_hash(password)
        
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)',
                        (username, email, password_hash))
            conn.commit()
            flash('Account created successfully! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash('Username or email already exists!', 'danger')
        finally:
            conn.close()
    
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        csrf_token = request.form.get('csrf_token')
        if not validate_csrf_token(csrf_token):
            flash('Invalid security token. Please try again.', 'danger')
            return redirect(url_for('login'))
            
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash(f'Welcome back, {username}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password!', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully!', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session['user_id']
    conn = get_db_connection()
    
    notes = conn.execute('SELECT * FROM notes WHERE user_id = ? ORDER BY pinned DESC, created_at DESC', 
                         (user_id,)).fetchall()
    tasks_raw = conn.execute('SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC', 
                         (user_id,)).fetchall()
    
    conn.close()
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    tasks = []
    for task in tasks_raw:
        task_dict = dict(task)
        task_dict['is_overdue'] = (task['due_date'] and task['due_date'] < today and task['status'] != 'completed')
        tasks.append(task_dict)
    
    total_tasks = len(tasks)
    completed_tasks = len([t for t in tasks if t['status'] == 'completed'])
    today_pending = len([t for t in tasks if t['status'] == 'pending' and t.get('due_date') == today])
    
    return render_template('dashboard.html', 
                          notes=notes, 
                          tasks=tasks,
                          total_tasks=total_tasks,
                          completed_tasks=completed_tasks,
                          today_pending=today_pending,
                          today=today)

@app.route('/notes')
@login_required
def notes():
    user_id = session['user_id']
    search_query = request.args.get('search', '')
    
    conn = get_db_connection()
    if search_query:
        notes = conn.execute('SELECT * FROM notes WHERE user_id = ? AND title LIKE ? ORDER BY pinned DESC, created_at DESC',
                            (user_id, f'%{search_query}%')).fetchall()
    else:
        notes = conn.execute('SELECT * FROM notes WHERE user_id = ? ORDER BY pinned DESC, created_at DESC',
                            (user_id,)).fetchall()
    conn.close()
    
    return render_template('notes.html', notes=notes, search_query=search_query)

@app.route('/add_note', methods=['POST'])
@login_required
def add_note():
    csrf_token = request.form.get('csrf_token')
    if not validate_csrf_token(csrf_token):
        flash('Invalid security token. Please try again.', 'danger')
        return redirect(url_for('notes'))
        
    title = request.form['title']
    content = request.form['content']
    user_id = session['user_id']
    
    if not title or not content:
        flash('Title and content are required!', 'danger')
        return redirect(url_for('notes'))
    
    conn = get_db_connection()
    conn.execute('INSERT INTO notes (user_id, title, content) VALUES (?, ?, ?)',
                (user_id, title, content))
    conn.commit()
    conn.close()
    
    flash('Note created successfully!', 'success')
    return redirect(url_for('notes'))

@app.route('/edit_note/<int:id>', methods=['POST'])
@login_required
def edit_note(id):
    csrf_token = request.form.get('csrf_token')
    if not validate_csrf_token(csrf_token):
        flash('Invalid security token. Please try again.', 'danger')
        return redirect(url_for('notes'))
        
    title = request.form['title']
    content = request.form['content']
    user_id = session['user_id']
    
    conn = get_db_connection()
    conn.execute('UPDATE notes SET title = ?, content = ? WHERE id = ? AND user_id = ?',
                (title, content, id, user_id))
    conn.commit()
    conn.close()
    
    flash('Note updated successfully!', 'success')
    return redirect(url_for('notes'))

@app.route('/delete_note/<int:id>', methods=['POST'])
@login_required
def delete_note(id):
    csrf_token = request.form.get('csrf_token')
    if not validate_csrf_token(csrf_token):
        flash('Invalid security token. Please try again.', 'danger')
        return redirect(url_for('notes'))
        
    user_id = session['user_id']
    
    conn = get_db_connection()
    conn.execute('DELETE FROM notes WHERE id = ? AND user_id = ?', (id, user_id))
    conn.commit()
    conn.close()
    
    flash('Note deleted successfully!', 'info')
    return redirect(url_for('notes'))

@app.route('/pin_note/<int:id>', methods=['POST'])
@login_required
def pin_note(id):
    csrf_token = request.form.get('csrf_token')
    if not validate_csrf_token(csrf_token):
        flash('Invalid security token. Please try again.', 'danger')
        return redirect(url_for('notes'))
        
    user_id = session['user_id']
    
    conn = get_db_connection()
    note = conn.execute('SELECT pinned FROM notes WHERE id = ? AND user_id = ?', 
                       (id, user_id)).fetchone()
    
    if note:
        new_pinned = 0 if note['pinned'] else 1
        conn.execute('UPDATE notes SET pinned = ? WHERE id = ? AND user_id = ?',
                    (new_pinned, id, user_id))
        conn.commit()
        flash('Note pinned!' if new_pinned else 'Note unpinned!', 'info')
    
    conn.close()
    return redirect(url_for('notes'))

@app.route('/tasks')
@login_required
def tasks():
    user_id = session['user_id']
    
    conn = get_db_connection()
    tasks_raw = conn.execute('SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC',
                        (user_id,)).fetchall()
    conn.close()
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    tasks = []
    for task in tasks_raw:
        task_dict = dict(task)
        task_dict['is_overdue'] = (task['due_date'] and task['due_date'] < today and task['status'] != 'completed')
        tasks.append(task_dict)
    
    return render_template('tasks.html', tasks=tasks, today=today)

@app.route('/add_task', methods=['POST'])
@login_required
def add_task():
    csrf_token = request.form.get('csrf_token')
    if not validate_csrf_token(csrf_token):
        flash('Invalid security token. Please try again.', 'danger')
        return redirect(url_for('tasks'))
        
    task_name = request.form['task_name']
    priority = request.form['priority']
    due_date = request.form['due_date']
    user_id = session['user_id']
    
    if not task_name or not priority or not due_date:
        flash('All fields are required!', 'danger')
        return redirect(url_for('tasks'))
    
    conn = get_db_connection()
    conn.execute('INSERT INTO tasks (user_id, task_name, priority, due_date) VALUES (?, ?, ?, ?)',
                (user_id, task_name, priority, due_date))
    conn.commit()
    conn.close()
    
    flash('Task added successfully!', 'success')
    return redirect(url_for('tasks'))

@app.route('/complete_task/<int:id>', methods=['POST'])
@login_required
def complete_task(id):
    csrf_token = request.form.get('csrf_token')
    if not validate_csrf_token(csrf_token):
        flash('Invalid security token. Please try again.', 'danger')
        return redirect(url_for('tasks'))
        
    user_id = session['user_id']
    
    conn = get_db_connection()
    task = conn.execute('SELECT status FROM tasks WHERE id = ? AND user_id = ?',
                       (id, user_id)).fetchone()
    
    if task:
        new_status = 'completed' if task['status'] == 'pending' else 'pending'
        conn.execute('UPDATE tasks SET status = ? WHERE id = ? AND user_id = ?',
                    (new_status, id, user_id))
        conn.commit()
        flash('Task marked as completed!' if new_status == 'completed' else 'Task marked as pending!', 'success')
    
    conn.close()
    return redirect(url_for('tasks'))

@app.route('/delete_task/<int:id>', methods=['POST'])
@login_required
def delete_task(id):
    csrf_token = request.form.get('csrf_token')
    if not validate_csrf_token(csrf_token):
        flash('Invalid security token. Please try again.', 'danger')
        return redirect(url_for('tasks'))
        
    user_id = session['user_id']
    
    conn = get_db_connection()
    conn.execute('DELETE FROM tasks WHERE id = ? AND user_id = ?', (id, user_id))
    conn.commit()
    conn.close()
    
    flash('Task deleted successfully!', 'info')
    return redirect(url_for('tasks'))

def analyze_text_heuristic(text):
    if not text:
        return {"summary": "No content to analyze.", "action_items": [], "tags": []}

    # 1. Summary: Just the first sentence or up to 100 characters.
    sentences = re.split(r'(?<=[.!?]) +', text.strip())
    summary = sentences[0] if sentences else text[:100]
    if len(summary) > 150: summary = summary[:147] + "..."
    
    # 2. Action Items: Sentences with keyword triggers.
    action_keywords = ["need to", "must", "should", "todo", "to-do", "action item", "remember to", "urgent"]
    action_items = []
    for s in sentences:
        if any(kw in s.lower() for kw in action_keywords):
            action_items.append(s.strip())
            
    # 3. Tags: Capitalized words or specific buzzwords
    buzzwords = ["project", "meeting", "python", "flask", "database", "api", "backend", "frontend", "design", "planning", "bug", "fix", "resume", "idea", "code"]
    tags = set()
    words = text.lower().split()
    for w in words:
        clean_w = re.sub(r'[^a-z]', '', w)
        if clean_w in buzzwords:
            tags.add(clean_w)
            
    # Also find capitalized acronyms or titles
    capitalized = re.findall(r'\b[A-Z][a-z]*\b|\b[A-Z]{2,}\b', text)
    common_starts = {"The", "A", "An", "This", "That", "It", "He", "She", "They", "We", "I", "To", "And", "Or", "If", "But", "For"}
    for c in capitalized:
        if c not in common_starts and len(c) > 2:
            tags.add(c.lower())
            
    return {
        "summary": summary,
        "action_items": action_items[:3],
        "tags": list(tags)[:5]
    }

@app.route('/api/analyze_note', methods=['POST'])
@login_required
def api_analyze_note():
    data = request.get_json()
    if not data or 'content' not in data:
        return jsonify({"error": "No content provided"}), 400
        
    analysis = analyze_text_heuristic(data['content'])
    return jsonify(analysis)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
