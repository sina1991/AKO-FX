import hashlib
import hmac
import re
import secrets
import time
import uuid
from ako_fx.store import Error, audit

DUMMY_SALT='0'*32
DUMMY_HASH=hashlib.pbkdf2_hmac('sha256',b'unknown-password',DUMMY_SALT.encode(),260000).hex()

def password_hash(password):
    if not isinstance(password,str) or not 12 <= len(password) <= 128:
        raise Error('Password length must be 12..128')
    salt=secrets.token_hex(16)
    return salt+':'+hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),260000).hex()

def email(value):
    if not isinstance(value,str) or len(value)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):
        raise Error('Invalid email')
    return value.strip().lower()

def register(db,data,role='user'):
    address=email(data.get('email'))
    hashed=password_hash(data.get('password'))
    if db.execute('SELECT 1 FROM users WHERE email=?',(address,)).fetchone():
        raise Error('Email already registered',409)
    uid=uuid.uuid4().hex
    db.execute('INSERT INTO users VALUES(?,?,?,?)',(uid,address,hashed,role))
    audit(db,uid,'register',uid)
    return {'id':uid,'email':address,'role':role}

def login(db,data):
    address=email(data.get('email'))
    now=int(time.time())
    row=db.execute('SELECT * FROM attempts WHERE subject=?',(address,)).fetchone()
    if row and row['reset_at']>now and row['count']>=10:
        return {'error':'Too many login attempts; retry in 15 minutes','status':429}
    if not row or row['reset_at']<=now:
        db.execute('INSERT OR REPLACE INTO attempts VALUES(?,0,?)',(address,now+900))
    db.execute('UPDATE attempts SET count=count+1 WHERE subject=?',(address,))
    user=db.execute('SELECT * FROM users WHERE email=?',(address,)).fetchone()
    salt,expected=(user['password'] if user else DUMMY_SALT+':'+DUMMY_HASH).split(':')
    password=data.get('password','')
    if not isinstance(password,str) or len(password)>128:
        password=''
    actual=hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),260000).hex()
    if not user or not hmac.compare_digest(actual,expected):
        return {'error':'Invalid credentials','status':401}
    db.execute('DELETE FROM attempts WHERE subject=?',(address,))
    db.execute('DELETE FROM sessions WHERE expires<=?',(now,))
    token=secrets.token_urlsafe(32)
    db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],now+28800))
    audit(db,user['id'],'login',user['id'])
    return {'token':token,'expires_in':28800,'user':{'id':user['id'],'email':address,'role':user['role']}}

def authenticate(db,token):
    row=db.execute('SELECT u.id,u.email,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>?',(hashlib.sha256(token.encode()).hexdigest(),int(time.time()))).fetchone()
    if not row:
        raise Error('Authentication required',401)
    return dict(row)
