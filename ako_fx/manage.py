import argparse
import getpass
import sqlite3
from ako_fx.store import init, transaction, Error
from ako_fx.services.identity import register

def main():
    p=argparse.ArgumentParser(description='Local administrative setup; never exposed over HTTP')
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('init')
    admin=sub.add_parser('create-admin'); admin.add_argument('--email',required=True)
    backup=sub.add_parser('backup'); backup.add_argument('destination')
    args=p.parse_args(); init()
    if args.command=='create-admin':
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
