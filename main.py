from flask import Flask, render_template, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
import base64, os
from flask_socketio import SocketIO, emit
from gevent.pywsgi import WSGIServer
from geventwebsocket.handler import WebSocketHandler
from datetime import datetime
import hashlib


app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ["SECRET_KEY"]
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///notes.db'
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*", allow_unsafe_werkzeug=True)

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

with app.app_context():
    db.create_all()


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
        encoded_note = base64.b64encode(note.encode('utf-8')).decode('utf-8') # base64 isn't for security but incase someone injects some crypto url and the repl will freeze by replit;
        new_note = Note(user_slug=hashed_slug, note_content=encoded_note)
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

        # Check if this is the first time fetching notes for the user slug
       
        notes_list = [{
            'id': note.id,
            'note': base64.b64decode(note.note_content.encode('utf-8')).decode('utf-8'),
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


if __name__ == "__main__":
  now = datetime.now()
  current_time = now.strftime("%H:%M:%S")
  print(f"Running! Started at {current_time}")
  http_server = WSGIServer(('0.0.0.0', 8080), app, handler_class=WebSocketHandler)
  http_server.serve_forever()