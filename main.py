from flask import Flask, render_template, send_file
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
import base64, os
from flask_socketio import SocketIO, emit
from gevent.pywsgi import WSGIServer
from geventwebsocket.handler import WebSocketHandler
from datetime import datetime
import hashlib,time,shutil,glob
from random import randint
from cryptography.fernet import Fernet
import threading


app = Flask(__name__)
CORS(app, origins=["https://replit.com"])
app.config['SECRET_KEY'] = os.environ["SECRET_KEY"]
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///notes.db'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['REMEMBER_COOKIE_SECURE'] = True
db = SQLAlchemy(app)
import logging

class CustomLogFilter(logging.Filter):
  def filter(self, record):
    if "Sending packet MESSAGE" in record.getMessage():
      return False
    return True
logger = logging.getLogger("engineio.server")
logger.addFilter(CustomLogFilter())
socketio = SocketIO(app, cors_allowed_origins="*", allow_unsafe_werkzeug=True, max_http_buffer_size=1000000, logger=logger)
FERNET_KEY = os.environ["FERNET_KEY"].encode('utf-8')

def encrypt_data(data, key):
  f = Fernet(key)
  return f.encrypt(data.encode('utf-8'))

def decrypt_data(data, key):
  f = Fernet(key)
  if not isinstance(data, bytes):
      data = data.encode('utf-8')
  return f.decrypt(data).decode('utf-8')

def hash_user_slug(user_slug, salt):
  hasher = hashlib.sha256()
  hasher.update((user_slug + salt).encode('utf-8'))
  hashed_slug = hasher.hexdigest()
  return hashed_slug

USER_SLUG_SALT = os.environ["SECRET_SALT"]

class Note(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  user_slug = db.Column(db.String(80), nullable=False)
  note_content = db.Column(db.String, nullable=False)
  done = db.Column(db.Boolean, default=False)

class Snippet(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  user_slug = db.Column(db.String(80), nullable=False)
  title = db.Column(db.String, nullable=False)
  code = db.Column(db.String, nullable=False)
  last_used = db.Column(db.DateTime, default=datetime.utcnow) 
  pinned = db.Column(db.Boolean, default=False)

@app.route('/')
def index():
  return render_template("index.html")

@app.route('/extension.json')
def manifest():
  return send_file("extension.json")

@socketio.on('connect')
def handle_connect():
  emit('connected', {'data': 'Connected'})


@socketio.on('store_note')
def handle_store_note(data):
  user_slug = data.get('user_slug')
  note = data.get('note')

  if user_slug and note:
    hashed_slug = hash_user_slug(user_slug, USER_SLUG_SALT)
    encrypted_note = encrypt_data(note, FERNET_KEY)
    new_note = Note(user_slug=hashed_slug, note_content=encrypted_note)
    db.session.add(new_note)
    db.session.commit()
    emit('note_stored', {'message': 'Note stored successfully'})
  else:
    emit('error_occurred', {'message': 'Invalid input'})

@socketio.on('get_notes')
def handle_get_notes(data):
  user_slug = data.get('user_slug')
  
  if user_slug:
    hashed_slug = hash_user_slug(user_slug, USER_SLUG_SALT)
    notes = Note.query.filter_by(user_slug=hashed_slug).all()

   
    notes_list = [{
      'id': note.id,
      'note': decrypt_data(note.note_content, FERNET_KEY),
      'done': note.done
    } for note in notes]
    emit('notes_fetched', notes_list)
  else:
    emit('error_occurred', {'message': 'Invalid input'})

@socketio.on('delete_note')
def handle_delete_note(data):
  note_id = data.get('note_id')
  user_slug = data.get('user_slug')

  if note_id and user_slug:
    hashed_slug = hash_user_slug(user_slug, USER_SLUG_SALT)
    note = Note.query.filter_by(id=note_id, user_slug=hashed_slug).first()

    if note:
      db.session.delete(note)
      db.session.commit()
      emit('note_deleted', {'message': f'Note with ID {note_id} has been deleted'})
    else:
      emit('error_occurred', {'message': f'Note with ID {note_id} not found or not owned by the user'})
  else:
    emit('error_occurred', {'message': 'Invalid input'})

@socketio.on('mark_note')
def handle_mark_note(data):
  note_id = data.get('note_id')
  is_done = data.get('is_done')
  user_slug = data.get('user_slug')
  
  if note_id is not None and is_done is not None and user_slug:
    hashed_slug = hash_user_slug(user_slug, USER_SLUG_SALT)
    note = Note.query.filter_by(id=note_id, user_slug=hashed_slug).first()
    if note:
      note.done = is_done
      db.session.commit()
      emit('note_marked', {'message': f'Note with ID {note_id} has been marked'})
    else:
      emit('error_occurred', {'message': f'Note with ID {note_id} not found or not owned by the user'})
  else:
    emit('error_occurred', {'message': 'Invalid input'})

@socketio.on('edit_note')
def handle_edit_note(data):
  note_id = data.get('note_id')
  new_text = data.get('new_text')
  user_slug = data.get('user_slug')

  if note_id and new_text and user_slug:
    hashed_slug = hash_user_slug(user_slug, USER_SLUG_SALT)
    encoded_new_text = base64.b64encode(new_text.encode('utf-8')).decode('utf-8') 
    note = Note.query.filter_by(id=note_id, user_slug=hashed_slug).first()

    if note:
      note.note_content = encoded_new_text
      db.session.commit()
      emit('note_edited', {'message': 'Note has been edited'})
    else:
      emit('error_occurred', {'message': f'Note with ID {note_id} not found or not owned by the user'})
  else:
    emit('error_occurred', {'message': 'Invalid input'})

#snippets  
@socketio.on('store_snippet')
def handle_store_snippet(data):
  user_slug = data.get('user')
  title = data.get('title')
  code = data.get('code')

  if user_slug and title and code:
    hashed_slug = hash_user_slug(user_slug, USER_SLUG_SALT)
    encrypted_code = encrypt_data(code, FERNET_KEY)
    new_snippet = Snippet(user_slug=hashed_slug, title=title, code=encrypted_code)
    db.session.add(new_snippet)
    db.session.commit()
    emit('snippet_stored', {'message': 'Snippet stored successfully'})
  else:
    emit('error_occurred', {'message': 'Invalid input'})

@socketio.on('get_snippets')
def handle_get_snippets(data):
  user_slug = data.get('user')

  if user_slug:
    try:
      hashed_slug = hash_user_slug(user_slug, USER_SLUG_SALT)
      # Order by pinned status first, then by last_used timestamp
      snippets = Snippet.query.filter_by(user_slug=hashed_slug).order_by(Snippet.pinned.desc(), Snippet.last_used.desc()).all()

      snippets_list = [{
        'id': snippet.id,
        'title': snippet.title,
        'code': decrypt_data(snippet.code, FERNET_KEY),
        'pinned': snippet.pinned
      } for snippet in snippets]

      emit('snippets_fetched', snippets_list)
    except Exception as e:
      print(f"Error in get_snippets event handler: {e}")
      emit('error_occurred', {'message': 'An internal error occurred'})
  else:
    emit('error_occurred', {'message': 'Invalid input'})

@socketio.on('delete_snippet')
def handle_delete_snippet(data):
  snippet_id = data.get('snippet_id')
  user_slug = data.get('user')

  if snippet_id and user_slug:
    hashed_slug = hash_user_slug(user_slug, USER_SLUG_SALT)
    snippet = Snippet.query.filter_by(id=snippet_id, user_slug=hashed_slug).first()

    if snippet:
      db.session.delete(snippet)
      db.session.commit()
      emit('snippet_deleted', {'message': f'Snippet with ID {snippet_id} has been deleted'})
    else:
        emit('error_occurred', {'message': f'Snippet with ID {snippet_id} not found or not owned by the user'})
  else:
    emit('error_occurred', {'message': 'Invalid input'})

@socketio.on('edit_snippet_code')
def handle_edit_snippet_code(data):
  snippet_id = data.get('snippet_id')
  new_code = data.get('new_code')
  user_slug = data.get('user')
  if snippet_id and new_code and user_slug:
    hashed_slug = hash_user_slug(user_slug, USER_SLUG_SALT)
    snippet = Snippet.query.filter_by(id=snippet_id, user_slug=hashed_slug).first()

    if snippet:
      snippet.code = new_code
      db.session.commit()
      emit('snippet_code_edited', {'message': 'Snippet content has been edited'})
    else:
        emit('error_occurred', {'message': f'Snippet with ID {snippet_id} not found or not owned by the user'})
  else:
    emit('error_occurred', {'message': 'Invalid input'})

@socketio.on('update_snippet_last_used')
def handle_update_snippet_last_used(data):
  snippet_id = data.get('snippet_id')
  user_slug = data.get('user')

  if snippet_id and user_slug:
    hashed_slug = hash_user_slug(user_slug, USER_SLUG_SALT)
    snippet = Snippet.query.filter_by(id=snippet_id, user_slug=hashed_slug).first()

    if snippet:
      snippet.last_used = datetime.utcnow()
      db.session.commit()
      emit('snippet_last_used_updated', {'message': 'Snippet last used updated'})
    else:
        emit('error_occurred', {'message': f'Snippet with ID {snippet_id} not found or not owned by the user'})
  else:
    emit('error_occurred', {'message': 'Invalid input'})

@socketio.on('toggle_pin_snippet')
def handle_toggle_pin_snippet(data):
  snippet_id = data.get('snippet_id')
  user_slug = data.get('user')

  if snippet_id and user_slug:
    hashed_slug = hash_user_slug(user_slug, USER_SLUG_SALT)
    snippet = Snippet.query.filter_by(id=snippet_id, user_slug=hashed_slug).first()

    if snippet:
      snippet.pinned = not snippet.pinned
      db.session.commit()
      emit('snippet_pin_toggled', {'message': f'Snippet with ID {snippet_id} pin status has been toggled'})
    else:
      emit('error_occurred', {'message': f'Snippet with ID {snippet_id} not found or not owned by the user'})
  else:
    emit('error_occurred', {'message': 'Invalid input'})

def database_loops():
  def remove_old_backups(max_age_days):
    now = time.time()

    for file_path in glob.glob("backups/notes_backup_*.db"):
      file_timestamp = os.path.getmtime(file_path)
      file_age_days = (now - file_timestamp) / (60 * 60 * 24)

      if file_age_days > max_age_days:
        try:
          os.remove(file_path)
          print(f"Removed old backup: {file_path}")
        except Exception as e:
          print(f"Error removing old backup {file_path}: {e}")
  def backup_database():
    try:
      timestamp = time.strftime('%Y%m%d_%H%M%S')
      backup_path = f'backups/notes_backup_{timestamp}.db'
      os.makedirs(os.path.dirname(backup_path), exist_ok=True)
      shutil.copyfile('instance/notes.db', backup_path)
      print(f"Database backup created at {backup_path}")
    except Exception as e:
      print(f"Error creating database backup: {e}")
  while True:
    remove_old_backups(7)
    time.sleep(60 * 60 * 24) # day hour
    backup_database()

if __name__ == "__main__":
  with app.app_context():
    db.create_all()
  loop_thread = threading.Thread(target=database_loops, daemon=True)
  loop_thread.start()
  now = datetime.now()
  current_time = now.strftime("%H:%M:%S")
  print(f"Running! Started at {current_time}")
  http_server = WSGIServer(('0.0.0.0', randint(1111,9999)), app, handler_class=WebSocketHandler)
  http_server.serve_forever()