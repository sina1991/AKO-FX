import argparse
import getpass
import json
import sqlite3
import sys
from ako_fx.store import init, transaction, Error
from ako_fx.services.identity import register


def main(argv=None):
    p=argparse.ArgumentParser(description='Local administrative setup; never exposed over HTTP')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('init')
    sub.add_parser('admin-status')
    admin=sub.add_parser('create-admin')
    admin.add_argument('--email',required=True)
    admin.add_argument('--password-stdin',action='store_true',help='Read one password line from a private input stream')
    backup=sub.add_parser('backup'); backup.add_argument('destination')
    args=p.parse_args(argv); init()
    if args.command=='admin-status':
        with transaction() as db:
            count=db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
        print(json.dumps({'count':count}))
    elif args.command=='create-admin':
        if args.password_stdin:
            pw=sys.stdin.readline(1024).rstrip('\r\n')
        else:
            pw=getpass.getpass('Admin password (12+ characters): ')
            if pw!=getpass.getpass('Repeat password: '): p.error('Passwords differ')
        try:
            with transaction() as db: print(register(db,{'email':args.email,'password':pw},role='admin'))
        except Error as e: p.error(str(e))
    elif args.command=='backup':
        import os
        from ako_fx.store import connect
        if os.path.exists(args.destination): p.error('Destination already exists')
        fd=os.open(args.destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600); os.close(fd)
        source=connect(); target=sqlite3.connect(args.destination)
        try: source.backup(target)
        finally: target.close(); source.close()
        print('Backup saved: '+args.destination)
    else: print('Database initialized; DEMO_ONLY')

if __name__=='__main__': main()
