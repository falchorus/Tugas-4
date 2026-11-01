import os
import re
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, current_app
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import (
JWTManager, create_access_token, jwt_required, get_jwt_identity
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from marshmallow import Schema, fields, validate

--- Inisialisasi Ekstensi ---

db = SQLAlchemy()
jwt = JWTManager()

--- Tabel Pivot (Many-to-Many) ---

post_hashtags = db.Table('post_hashtags',
db.Column('post_id', db.Integer, db.ForeignKey('posts.id', ondelete='CASCADE'), primary_key=True),
db.Column('hashtag_id', db.Integer, db.ForeignKey('hashtags.id', ondelete='CASCADE'), primary_key=True)
)

follows = db.Table('follows',
db.Column('id', db.Integer, primary_key=True, autoincrement=True),
db.Column('follower_id', db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
db.Column('following_id', db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
db.Column('created_at', db.DateTime, default=datetime.utcnow),
db.UniqueConstraint('follower_id', 'following_id', name='uq_follower_following')
)

--- Models ---

class User(db.Model):
tablename = 'users'
id = db.Column(db.Integer, primary_key=True, autoincrement=True)
username = db.Column(db.String(30), unique=True, nullable=False)
email = db.Column(db.String(120), unique=True, nullable=False)
password_hash = db.Column(db.String(255), nullable=False)
full_name = db.Column(db.String(100))
bio = db.Column(db.String(150))
avatar_url = db.Column(db.String(255))
is_private = db.Column(db.Boolean, default=False)
created_at = db.Column(db.DateTime, default=datetime.utcnow)
updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

posts = db.relationship('Post', backref='author', lazy=True, cascade='all, delete-orphan')
comments = db.relationship('Comment', backref='author', lazy=True, cascade='all, delete-orphan')
likes = db.relationship('Like', backref='user', lazy=True, cascade='all, delete-orphan')

following = db.relationship(
    'User', secondary=follows,
    primaryjoin='User.id==follows.c.follower_id',
    secondaryjoin='User.id==follows.c.following_id',
    backref=db.backref('followers', lazy='dynamic'),
    lazy='dynamic'
)
notifications_received = db.relationship('Notification', foreign_keys='Notification.recipient_id', backref='recipient', lazy=True, cascade='all, delete-orphan')

def set_password(self, password):
    self.password_hash = generate_password_hash(password)

def check_password(self, password):
    return check_password_hash(self.password_hash, password)


class Post(db.Model):
tablename = 'posts'
id = db.Column(db.Integer, primary_key=True, autoincrement=True)
user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
caption = db.Column(db.Text)
image_url = db.Column(db.String(255), nullable=False)
location = db.Column(db.String(100))
likes_count = db.Column(db.Integer, default=0)
comments_count = db.Column(db.Integer, default=0)
created_at = db.Column(db.DateTime, default=datetime.utcnow)
updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

comments = db.relationship('Comment', backref='post', lazy=True, cascade='all, delete-orphan')
likes = db.relationship('Like', backref='post', lazy=True, cascade='all, delete-orphan')
hashtags = db.relationship('Hashtag', secondary=post_hashtags, backref=db.backref('posts', lazy='dynamic'), lazy='subquery')


class Comment(db.Model):
tablename = 'comments'
id = db.Column(db.Integer, primary_key=True, autoincrement=True)
post_id = db.Column(db.Integer, db.ForeignKey('posts.id', ondelete='CASCADE'), nullable=False)
user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
parent_id = db.Column(db.Integer, db.ForeignKey('comments.id', ondelete='CASCADE'), nullable=True)
content = db.Column(db.String(500), nullable=False)
created_at = db.Column(db.DateTime, default=datetime.utcnow)
updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

replies = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]), lazy='dynamic', cascade='all, delete-orphan')


class Like(db.Model):
tablename = 'likes'
id = db.Column(db.Integer, primary_key=True, autoincrement=True)
user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
post_id = db.Column(db.Integer, db.ForeignKey('posts.id', ondelete='CASCADE'), nullable=False)
created_at = db.Column(db.DateTime, default=datetime.utcnow)
table_args = (db.UniqueConstraint('user_id', 'post_id', name='uq_user_post_like'),)

class Hashtag(db.Model):
tablename = 'hashtags'
id = db.Column(db.Integer, primary_key=True, autoincrement=True)
name = db.Column(db.String(50), unique=True, nullable=False)

class Notification(db.Model):
tablename = 'notifications'
id = db.Column(db.Integer, primary_key=True, autoincrement=True)
recipient_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
actor_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
type = db.Column(db.Enum('like', 'comment', 'follow', name='notification_types'), nullable=False)
post_id = db.Column(db.Integer, db.ForeignKey('posts.id', ondelete='CASCADE'), nullable=True)
comment_id = db.Column(db.Integer, db.ForeignKey('comments.id', ondelete='CASCADE'), nullable=True)
is_read = db.Column(db.Boolean, default=False)
created_at = db.Column(db.DateTime, default=datetime.utcnow)

actor = db.relationship('User', foreign_keys=[actor_id])
post = db.relationship('Post', foreign_keys=[post_id])
comment = db.relationship('Comment', foreign_keys=[comment_id])


--- Utils & Helpers ---

def success_response(data=None, message="Berhasil", status_code=200, meta=None):
res = {"success": True, "message": message}
if data is not None:
res["data"] = data
if meta is not None:
res["meta"] = meta
return jsonify(res), status_code

def error_response(message="Gagal", status_code=400, errors=None):
res = {"success": False, "message": message}
if errors is not None:
res["errors"] = errors
return jsonify(res), status_code

def paginate_query(query, page, per_page):
paginated = query.paginate(page=page, per_page=per_page, error_out=False)
meta = {
"page": paginated.page,
"per_page": paginated.per_page,
"total": paginated.total,
"pages": paginated.pages
}
return paginated.items, meta

def allowed_file(filename):
return '.' in filename and filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']

def save_image(file_storage):
if not file_storage or file_storage.filename == '':
return None, "File tidak ditemukan"
if not allowed_file(file_storage.filename):
return None, "Format file tidak didukung"
filename = secure_filename(file_storage.filename)
unique_filename = f"{uuid.uuid4().hex}_{filename}"
upload_folder = current_app.config['UPLOAD_FOLDER']
os.makedirs(upload_folder, exist_ok=True)
file_path = os.path.join(upload_folder, unique_filename)
file_storage.save(file_path)
return f"/static/uploads/{unique_filename}", None

def extract_hashtags(caption):
if not caption:
return []
tags = re.findall(r"#(\w+)", caption)
return list(set([t.lower() for t in tags]))

--- App Factory & Routes Setup ---

def create_app():
app = Flask(name)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key')
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'jwt-dev-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('SQLALCHEMY_DATABASE_URI', 'mysql+pymysql://root:@localhost:3306/mini_instagram_db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'app/static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 5242880
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

db.init_app(app)
jwt.init_app(app)

# --- Endpoints ---

# Auth
@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    if not data.get('username') or not data.get('email') or not data.get('password'):
        return error_response("Validasi gagal", 422, {"general": ["Field wajib diisi"]})
    if User.query.filter_by(username=data['username']).first() or User.query.filter_by(email=data['email']).first():
        return error_response("Username atau email sudah terdaftar", 409)
    user = User(username=data['username'], email=data['email'], full_name=data.get('full_name', ''))
    user.set_password(data['password'])
    db.session.add(user)
    db.session.commit()
    return success_response({"id": user.id, "username": user.username}, "Registrasi berhasil", 201)

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    identity = data.get('identity')
    user = User.query.filter((User.username == identity) | (User.email == identity)).first()
    if not user or not user.check_password(data.get('password', '')):
        return error_response("Username/email atau password salah", 401)
    access_token = create_access_token(identity=str(user.id))
    return success_response({"access_token": access_token}, "Login berhasil")

@app.route('/api/auth/me', methods=['GET'])
@jwt_required()
def me():
    user = User.query.get(get_jwt_identity())
    return success_response({
        "id": user.id, "username": user.username, "email": user.email,
        "full_name": user.full_name, "bio": user.bio, "avatar_url": user.avatar_url,
        "is_private": user.is_private, "followers_count": user.followers.count(),
        "following_count": user.following.count()
    })

# Users & Follow
@app.route('/api/users/search', methods=['GET'])
def search_users():
    q = request.args.get('q', '')
    page, per_page = int(request.args.get('page', 1)), int(request.args.get('per_page', 10))
    items, meta = paginate_query(User.query.filter(User.username.like(f"%{q}%")), page, per_page)
    res = [{"id": u.id, "username": u.username, "full_name": u.full_name, "avatar_url": u.avatar_url} for u in items]
    return success_response(res, meta=meta)

@app.route('/api/users/<username>', methods=['GET'])
def get_user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    return success_response({
        "id": user.id, "username": user.username, "full_name": user.full_name,
        "bio": user.bio, "avatar_url": user.avatar_url, "is_private": user.is_private,
        "posts_count": len(user.posts), "followers_count": user.followers.count(),
        "following_count": user.following.count()
    })

@app.route('/api/users/me', methods=['PATCH'])
@jwt_required()
def update_profile():
    user = User.query.get(get_jwt_identity())
    form = request.form.to_dict()
    file = request.files.get('avatar')
    if 'full_name' in form: user.full_name = form['full_name']
    if 'bio' in form: user.bio = form['bio']
    if 'is_private' in form: user.is_private = str(form['is_private']).lower() == 'true'
    if file:
        url, err = save_image(file)
        if err: return error_response(err, 400)
        user.avatar_url = url
    db.session.commit()
    return success_response(message="Profil berhasil diperbarui")

@app.route('/api/users/<username>/posts', methods=['GET'])
def get_user_posts(username):
    user = User.query.filter_by(username=username).first_or_404()
    page, per_page = int(request.args.get('page', 1)), int(request.args.get('per_page', 10))
    items, meta = paginate_query(Post.query.filter_by(user_id=user.id).order_by(Post.created_at.desc()), page, per_page)
    res = [{"id": p.id, "image_url": p.image_url, "caption": p.caption, "likes_count": p.likes_count, "comments_count": p.comments_count} for p in items]
    return success_response(res, meta=meta)

@app.route('/api/users/<username>/follow', methods=['POST'])
@jwt_required()
def follow_user(username):
    current_id = int(get_jwt_identity())
    target = User.query.filter_by(username=username).first_or_404()
    if target.id == current_id: return error_response("Tidak bisa follow diri sendiri", 400)
    existing = db.session.execute(follows.select().where((follows.c.follower_id == current_id) & (follows.c.following_id == target.id))).first()
    if existing: return error_response("Sudah mengikuti", 409)
    db.session.execute(follows.insert().values(follower_id=current_id, following_id=target.id))
    db.session.add(Notification(recipient_id=target.id, actor_id=current_id, type='follow'))
    db.session.commit()
    return success_response(message="Berhasil mengikuti")

@app.route('/api/users/<username>/follow', methods=['DELETE'])
@jwt_required()
def unfollow_user(username):
    current_id = int(get_jwt_identity())
    target = User.query.filter_by(username=username).first_or_404()
    res = db.session.execute(follows.delete().where((follows.c.follower_id == current_id) & (follows.c.following_id == target.id)))
    db.session.commit()
    if res.rowcount == 0: return error_response("Belum mengikuti", 400)
    return success_response(message="Berhasil berhenti mengikuti")

# Posts & Likes
@app.route('/api/posts', methods=['POST'])
@jwt_required()
def create_post():
    user_id = get_jwt_identity()
    caption = request.form.get('caption', '')
    location = request.form.get('location', '')
    file = request.files.get('image')
    if not file: return error_response("Gambar wajib diisi", 400)
    image_url, err = save_image(file)
    if err: return error_response(err, 400)
    post = Post(user_id=user_id, caption=caption, location=location, image_url=image_url)
    for tag_name in extract_hashtags(caption):
        hashtag = Hashtag.query.filter_by(name=tag_name).first() or Hashtag(name=tag_name)
        post.hashtags.append(hashtag)
    db.session.add(post)
    db.session.commit()
    return success_response({"id": post.id}, "Postingan dibuat", 201)

@app.route('/api/posts/feed', methods=['GET'])
@jwt_required()
def get_feed():
    user = User.query.get(int(get_jwt_identity()))
    following_ids = [f.id for f in user.following] + [user.id]
    page, per_page = int(request.args.get('page', 1)), int(request.args.get('per_page', 10))
    items, meta = paginate_query(Post.query.filter(Post.user_id.in_(following_ids)).order_by(Post.created_at.desc()), page, per_page)
    res = [{"id": p.id, "author": {"username": p.author.username, "avatar_url": p.author.avatar_url}, "image_url": p.image_url, "caption": p.caption} for p in items]
    return success_response(res, meta=meta)

@app.route('/api/posts/<int:id>/like', methods=['POST'])
@jwt_required()
def like_post(id):
    user_id = int(get_jwt_identity())
    post = Post.query.get_or_404(id)
    if Like.query.filter_by(user_id=user_id, post_id=post.id).first():
        return error_response("Sudah disukai", 409)
    db.session.add(Like(user_id=user_id, post_id=post.id))
    post.likes_count += 1
    if post.user_id != user_id:
        db.session.add(Notification(recipient_id=post.user_id, actor_id=user_id, type='like', post_id=post.id))
    db.session.commit()
    return success_response(message="Postingan disukai")

@app.route('/api/posts/<int:id>/like', methods=['DELETE'])
@jwt_required()
def unlike_post(id):
    user_id = int(get_jwt_identity())
    post = Post.query.get_or_404(id)
    like = Like.query.filter_by(user_id=user_id, post_id=post.id).first()
    if not like: return error_response("Belum disukai", 400)
    db.session.delete(like)
    post.likes_count = max(0, post.likes_count - 1)
    db.session.commit()
    return success_response(message="Like dibatalkan")

# Error Handlers
@app.errorhandler(404)
def not_found(e): return error_response("Not found", 404)

return app


if name == 'main':
app = create_app()
app.run(debug=True, port=5000)