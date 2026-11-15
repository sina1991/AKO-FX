import contextlib
import json
import os
import sqlite3
import time
from decimal import Decimal, InvalidOperation

class Error(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status

def money(value):
    if isinstance(value, bool):
        raise Error('Invalid amount')
    try:
        n = Decimal(str(value))
        if not n.is_finite() or n <= 0 or n > 10000000 or n != n.quantize(Decimal('.01')):
            raise Error('Amount must be positive, at most 10000000, with at most two decimals')
        return int(n * 100)
    except (InvalidOperation, ValueError, TypeError):
        raise Error('Invalid amount')

def connect():
    path = os.environ.get('AKO_DB', 'data/ako.db')
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    db = sqlite3.connect(path, timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=15000')
    return db

def init():
    with contextlib.closing(connect()) as db:
        os.chmod(os.environ.get('AKO_DB', 'data/ako.db'), 0o600)
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('user','admin')));
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS funding(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),amount INTEGER NOT NULL CHECK(amount>0),status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')));
CREATE TABLE IF NOT EXISTS balances(account TEXT PRIMARY KEY,amount INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS transactions(id TEXT PRIMARY KEY,kind TEXT NOT NULL,created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS entries(id INTEGER PRIMARY KEY,tx_id TEXT REFERENCES transactions(id),account TEXT REFERENCES balances(account),delta INTEGER NOT NULL);
CREATE TRIGGER IF NOT EXISTS entries_no_update BEFORE UPDATE ON entries BEGIN SELECT RAISE(ABORT,'Immutable ledger'); END;
CREATE TRIGGER IF NOT EXISTS entries_no_delete BEFORE DELETE ON entries BEGIN SELECT RAISE(ABORT,'Immutable ledger'); END;
CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),kind TEXT NOT NULL CHECK(kind IN ('broker','prop')),status TEXT NOT NULL DEFAULT 'active',initial_balance INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS positions(id TEXT PRIMARY KEY,account_id TEXT REFERENCES accounts(id),symbol TEXT NOT NULL,side TEXT NOT NULL,quantity INTEGER NOT NULL,entry_price INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'open',exit_price INTEGER,pnl INTEGER);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,actor TEXT NOT NULL,action TEXT NOT NULL,target TEXT NOT NULL,created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS idempotency(user_id TEXT NOT NULL,key TEXT NOT NULL,operation TEXT NOT NULL,payload TEXT NOT NULL,result TEXT NOT NULL,PRIMARY KEY(user_id,key));
CREATE TABLE IF NOT EXISTS quotes(symbol TEXT PRIMARY KEY,price INTEGER NOT NULL CHECK(price>0));
INSERT OR IGNORE INTO quotes VALUES('EURUSD',11000),('GBPUSD',12500),('USDJPY',1500000);
CREATE TABLE IF NOT EXISTS attempts(subject TEXT PRIMARY KEY,count INTEGER NOT NULL,reset_at INTEGER NOT NULL);
''')

@contextlib.contextmanager
def transaction():
    db = connect()
    try:
        db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def audit(db, actor, action, target):
    db.execute('INSERT INTO audit(actor,action,target,created) VALUES(?,?,?,?)', (actor,action,target,int(time.time())))

def balance(db, account):
    row = db.execute('SELECT amount FROM balances WHERE account=?',(account,)).fetchone()
    return row['amount'] if row else 0

def transfer(db, source, destination, amount, kind):
    import uuid
    if source == destination or not isinstance(amount,int) or amount <= 0:
        raise Error('Invalid transfer')
    for a in (source,destination):
        db.execute('INSERT OR IGNORE INTO balances(account) VALUES(?)',(a,))
    if source != 'demo:issuer' and balance(db,source) < amount:
        raise Error('Insufficient demo credit',409)
    tx = uuid.uuid4().hex
    db.execute('INSERT INTO transactions VALUES(?,?,?)',(tx,kind,int(time.time())))
    for account, delta in ((source,-amount),(destination,amount)):
        db.execute('INSERT INTO entries(tx_id,account,delta) VALUES(?,?,?)',(tx,account,delta))
        db.execute('UPDATE balances SET amount=amount+? WHERE account=?',(delta,account))
    return tx

def once(db, user, key, operation, payload, fn):
    if not isinstance(key,str) or not 8 <= len(key) <= 128:
        raise Error('An Idempotency-Key of 8..128 characters is required')
    encoded=json.dumps(payload,sort_keys=True,separators=(',',':'))
    row=db.execute('SELECT * FROM idempotency WHERE user_id=? AND key=?',(user,key)).fetchone()
    if row:
        if row['operation'] != operation or row['payload'] != encoded:
            raise Error('Idempotency key reused with a different request',409)
        return json.loads(row['result'])
    result=fn()
    db.execute('INSERT INTO idempotency VALUES(?,?,?,?,?)',(user,key,operation,encoded,json.dumps(result)))
    return result
