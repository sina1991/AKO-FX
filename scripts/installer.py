"""Single-host demo installer. Only AKO-owned resources may be replaced."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request

SOURCE = Path(__file__).resolve().parent.parent
SERVICES = ('identity', 'wallet', 'broker', 'prop', 'gateway')
MARKER = '# Managed by AKO-FX install.sh\n'

class InstallError(Exception):
    pass

def run(args, *, input=None, check=True, env=None, umask=-1):
    result = subprocess.run([str(a) for a in args], input=input, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, umask=umask)
    if check and result.returncode:
        # Command arguments never include passwords. Suppress stdout on failure.
        raise InstallError(f'{args[0]} failed: {result.stderr.strip()[-1800:]}')
    return result

def domain_name(value):
    value = value.strip().lower()
    if len(value) > 253 or '.' not in value or not all(
        re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part)
        for part in value.split('.')
    ) or re.fullmatch(r'[0-9.]+', value):
        raise InstallError('Use a valid DNS hostname, without scheme, path or port.')
    return value

def free_port(port):
    sockets = []
    try:
        for family, address in ((socket.AF_INET, '0.0.0.0'), (socket.AF_INET6, '::')):
            if family == socket.AF_INET6 and not socket.has_ipv6:
                continue
            sock = socket.socket(family, socket.SOCK_STREAM)
            sockets.append(sock)
            if family == socket.AF_INET6:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            try:
                sock.bind((address, port))
            except OSError as e:
                if family == socket.AF_INET6 and e.errno in (97, 99):
                    continue
                return False
        return True
    finally:
        for sock in sockets:
            sock.close()

def choose_port(requested, start, *, reserved=()):
    if requested is not None:
        if not 1024 <= requested <= 65535 or requested in reserved or not free_port(requested):
            raise InstallError(f'Port {requested} is not available. No service was stopped.')
        return requested
    for port in range(start, min(start + 100, 65536)):
        if port not in reserved and free_port(port):
            return port
    raise InstallError(f'No free port in {start}..{start+99}')

def atomic_write(path, content, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.ako-', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def root_owned(path):
    return Path(path).stat().st_uid == 0

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def check_owned(path, recorded_hash=None):
    path = Path(path)
    if path.is_symlink():
        raise InstallError(f'Refusing a symlink at managed file {path}')
    if path.exists():
        if not path.read_text().startswith(MARKER):
            raise InstallError(f'Refusing to overwrite an unrelated file: {path}')
        if recorded_hash and sha256(path) != recorded_hash:
            raise InstallError(f'Managed config was edited; review it before continuing: {path}')

def certificate_valid(cert, key, domain):
    cert, key = Path(cert), Path(key)
    if not cert.is_file() or not key.is_file():
        return False
    if run(['openssl', 'x509', '-in', cert, '-noout', '-checkhost', domain], check=False).returncode:
        return False
    if run(['openssl', 'x509', '-in', cert, '-noout', '-checkend', '86400'], check=False).returncode:
        return False
    public = run(['openssl', 'x509', '-in', cert, '-pubkey', '-noout'], check=False)
    private = run(['openssl', 'pkey', '-in', key, '-pubout', '-passin', 'pass:'], check=False)
    return public.returncode == private.returncode == 0 and public.stdout == private.stdout

def find_certificate(domain, explicit_cert=None, explicit_key=None, base=Path('/etc/letsencrypt/live')):
    if explicit_cert or explicit_key:
        if not explicit_cert or not explicit_key:
            raise InstallError('--cert and --key must be supplied together')
        if not certificate_valid(explicit_cert, explicit_key, domain):
            raise InstallError('Certificate/key must match, cover the domain and remain valid for 24h.')
        return str(Path(explicit_cert).absolute()), str(Path(explicit_key).absolute())
    for cert in sorted(base.glob('*/fullchain.pem')):
        key = cert.parent / 'privkey.pem'
        if certificate_valid(cert, key, domain):
            return str(cert), str(key)
    return None

def docker_environment():
    env = dict(os.environ, LC_ALL='C')
    for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        env.pop(key, None)
    return env

class Docker:
    def __init__(self, endpoint):
        if not endpoint.startswith('unix:///'):
            raise InstallError('Installer requires a local unix Docker endpoint; remote contexts are unsupported.')
        self.endpoint = endpoint
    def __call__(self, *args, **kwargs):
        # Explicit endpoint pins the daemon for every install/resume command.
        return run(['docker', '--host', self.endpoint, *args], env=docker_environment(), **kwargs)
    def json(self, *args):
        return json.loads(self(*args).stdout)

def docker_endpoint():
    if os.environ.get('DOCKER_CONTEXT'):
        context = os.environ['DOCKER_CONTEXT']
    elif os.environ.get('DOCKER_HOST'):
        return os.environ['DOCKER_HOST']
    else:
        context = run(['docker', 'context', 'show']).stdout.strip()
    data = json.loads(run(['docker', 'context', 'inspect', context]).stdout)
    return data[0]['Endpoints']['docker']['Host']

def inspect_install(docker, expected_volume=None):
    ids = docker('ps', '-a', '--filter', 'label=com.docker.compose.project=ako-fx',
                 '--format', '{{.ID}}').stdout.split()
    containers = docker.json('inspect', *ids) if ids else []
    volumes = set()
    for container in containers:
        labels = container['Config'].get('Labels') or {}
        service = labels.get('com.docker.compose.service')
        if service == 'proxy':
            if container['State']['Running']:
                raise InstallError('An AKO Caddy proxy is running. Review its use before adopting this installation.')
            continue
        if service not in SERVICES or 'ako_fx.server' not in container['Config'].get('Cmd', []):
            raise InstallError('Unrecognized container uses the ako-fx project name; refusing adoption.')
        mounts = [m for m in container.get('Mounts', []) if m['Destination'] == '/data']
        if len(mounts) != 1 or mounts[0]['Type'] != 'volume':
            raise InstallError('Existing AKO data is not a recognized named volume; refusing migration.')
        volumes.add(mounts[0]['Name'])
    if len(volumes) > 1:
        raise InstallError('AKO services use different data volumes; manual reconciliation is required.')
    volume = next(iter(volumes), expected_volume or 'ako-fx_ako-data')
    result = docker('volume', 'inspect', volume, check=False)
    if volumes and result.returncode:
        raise InstallError('An existing container references a missing data volume; refusing replacement.')
    if result.returncode == 0 and not volumes and not expected_volume:
        labels = json.loads(result.stdout)[0].get('Labels') or {}
        if labels.get('com.docker.compose.project') != 'ako-fx' or labels.get('com.docker.compose.volume') != 'ako-data':
            raise InstallError('Existing default volume is not owned by the AKO Compose project.')
    return containers, volume, bool(volumes) or result.returncode == 0

def compose_config(release, commit, volume, backend):
    base = {
        'image': 'ako-fx:' + commit[:12],
        'build': {'context': str(release)},
        'restart': 'unless-stopped', 'user': '10001:10001',
        'read_only': True, 'cap_drop': ['ALL'],
        'security_opt': ['no-new-privileges:true'], 'pids_limit': 128,
        'tmpfs': ['/tmp'], 'volumes': ['ako-data:/data'], 'networks': ['internal']
    }
    services = {}
    for role, port in zip(SERVICES, (8101, 8102, 8103, 8104, 8080)):
        item = dict(base)
        item['command'] = ['python', '-m', 'ako_fx.server', '--host', '0.0.0.0', '--service', role]
        item['environment'] = {'AKO_DB': '/data/ako.db', 'HEALTH_PORT': str(port)}
        item['healthcheck'] = {'test': ['CMD', 'python', '-c',
            f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{port}/health',timeout=3)"],
            'interval': '10s', 'timeout': '5s', 'retries': 12}
        if role == 'gateway':
            item['networks'] = ['internal', 'host-access']
            item['ports'] = [f'127.0.0.1:{backend}:8080']
            item['environment'].update({'AKO_' + s.upper() + '_HOST': s for s in SERVICES[:-1]})
            item['depends_on'] = {s: {'condition': 'service_healthy'} for s in SERVICES[:-1]}
        services[role] = item
    return {'name': 'ako-fx', 'services': services,
            'volumes': {'ako-data': {'name': volume, 'external': True}},
            'networks': {'internal': {'internal': True}, 'host-access': {'driver': 'bridge'}}}

def nginx_config(domain, port, backend, cert, key):
    # All interpolated values are validated; preserve Host INCLUDING nonstandard port.
    return MARKER + f'''server {{
    listen {port} ssl;
    listen [::]:{port} ssl;
    server_name {domain};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_certificate "{cert}";
    ssl_certificate_key "{key}";
    client_max_body_size 32k;
    access_log off;
    error_log /var/log/nginx/ako-fx-error.log warn;
    location / {{
        proxy_pass http://127.0.0.1:{backend};
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header Authorization $http_authorization;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_connect_timeout 5s;
        proxy_read_timeout 30s;
        proxy_send_timeout 30s;
    }}
}}
'''

def safe_path(value):
    path = Path(value).absolute()
    if any(c in str(path) for c in ('"', "'", '\n', '\r', '$', ';', '{', '}')):
        raise InstallError('Unsupported characters in certificate path')
    return str(path)

class Installer:
    def __init__(self, args, *, root=Path('/'), source=SOURCE):
        self.args, self.root, self.source = args, root, source
        self.etc = root / 'etc/ako-fx'
        self.prefix = root / 'opt/ako-fx'
        self.state_file = self.etc / 'install.json'
        self.compose_file = self.etc / 'compose.json'
        self.site = root / 'etc/nginx/sites-available/ako-fx-installer'
        self.enabled = root / 'etc/nginx/sites-enabled/ako-fx-installer'
        self.acme_site = root / 'etc/nginx/sites-available/ako-fx-acme'
        self.acme_enabled = root / 'etc/nginx/sites-enabled/ako-fx-acme'
        self.state = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        if self.state and self.state.get('owner') != 'AKO-FX installer v1':
            raise InstallError('Unrecognized installer state')
        self.docker = None

    def save(self, **values):
        self.state.update(values)
        atomic_write(self.state_file, json.dumps(self.state, indent=2) + '\n')

    def prompt(self, flag, label, default=None):
        value = getattr(self.args, flag)
        if value: return value
        if default: return default
        if self.args.non_interactive:
            raise InstallError(f'Missing --{flag.replace("_", "-")}')
        try:
            with open('/dev/tty', 'r+') as tty:
                tty.write(label + ': '); tty.flush()
                value = tty.readline().strip()
        except OSError:
            raise InstallError('Interactive input needs a TTY; use explicit flags.')
        if not value: raise InstallError(f'{label} is required')
        return value

    def preflight(self):
        domain = domain_name(self.prompt('domain', 'Domain', self.state.get('domain')))
        if self.state and self.state['domain'] != domain:
            raise InstallError('Changing the installed domain requires a planned migration.')
        for path in (self.etc, self.prefix):
            if path.is_symlink() or path.exists() and not root_owned(path):
                raise InstallError(f'Installer directory must be root-owned, not a symlink: {path}')
        if self.state_file.is_symlink() or self.compose_file.is_symlink():
            raise InstallError('Refusing symlinked installer state/config')
        check_owned(self.site, self.state.get('nginx_sha256'))
        check_owned(self.acme_site, self.state.get('acme_sha256'))
        for link, target in ((self.enabled,self.site),(self.acme_enabled,self.acme_site)):
            if link.is_symlink() and link.resolve() != target or link.exists() and not link.is_symlink():
                raise InstallError(f'Refusing unrelated enabled site {link}')
        missing = [x for x in ('docker', 'nginx', 'openssl', 'certbot') if not shutil.which(x)]
        self.domain = domain
        self.missing = missing
        self.commit = run(['git', '-C', self.source, 'rev-parse', 'HEAD']).stdout.strip()
        if not re.fullmatch('[a-f0-9]{40}', self.commit): raise InstallError('Invalid source commit')
        if run(['git', '-C', self.source, 'status', '--porcelain', '--untracked-files=no']).stdout.strip():
            raise InstallError('Tracked source files are modified. Use a clean checkout or the GitHub bootstrap command.')
        self.containers, self.volume, self.existing_data = [], 'ako-fx_ako-data', False
        if 'docker' not in missing:
            endpoint = self.state.get('docker_endpoint') or docker_endpoint()
            self.docker = Docker(endpoint)
            info = self.docker.json('info', '--format', '{{json .}}')
            if '30na-sandbox' in info.get('DockerRootDir','').lower():
                raise InstallError('Refusing the dedicated 30nA sandbox Docker daemon. Select a separate application daemon.')
            socket_path = Path(endpoint.removeprefix('unix://'))
            if socket_path.exists():
                import pwd
                if pwd.getpwuid(socket_path.stat().st_uid).pw_name == '30na-sandbox':
                    raise InstallError('Dedicated 30nA sandbox Docker socket cannot host AKO-FX.')
            if self.state.get('docker_id') and info['ID'] != self.state['docker_id']:
                raise InstallError('Docker daemon identity changed; refusing to create an empty replacement database.')
            self.docker_id = info['ID']
            self.docker('compose', 'version')
            self.containers, self.volume, self.existing_data = inspect_install(self.docker, self.state.get('volume'))
            if not self.existing_data and (self.state.get('data_preexisting') or self.state.get('volume_initialized')):
                raise InstallError('Stored database volume is missing; refusing an empty replacement.')
            if self.state.get('volume') and self.state['volume'] != self.volume:
                raise InstallError('Data volume changed; refusing to replace stored accounts.')
        elif (self.root / 'etc/30na').exists() or self.state:
            raise InstallError('Existing 30nA/AKO host has no usable Docker CLI. Refusing to provision a replacement daemon.')
        owned_backend = False
        old_backend = self.state.get('backend_port')
        if old_backend:
            for c in self.containers:
                if (c['Config'].get('Labels') or {}).get('com.docker.compose.service') == 'gateway':
                    bindings = c.get('NetworkSettings',{}).get('Ports') or {}
                    owned_backend = c['State']['Running'] and any(b.get('HostIp')=='127.0.0.1' and b.get('HostPort')==str(old_backend)
                                        for b in bindings.get('8080/tcp',[]) or [])
        if self.state:
            if self.args.port and self.args.port != self.state['port'] or self.args.backend_port and self.args.backend_port != old_backend:
                raise InstallError('Installed ports are fixed; explicit port migration is required.')
            self.port, self.backend = self.state['port'], old_backend
            if not free_port(self.backend) and not owned_backend:
                raise InstallError('Stored backend port is now used by an unrelated listener.')
            if not free_port(self.port) and not (self.enabled.is_symlink() and self.site.exists()):
                raise InstallError('Stored HTTPS port is now used by an unrelated listener.')
        else:
            self.port = choose_port(self.args.port, 8443)
            self.backend = choose_port(self.args.backend_port, 9080, reserved=(self.port,))
        self.nginx_text = ''
        if 'nginx' not in missing:
            self.nginx_text = run(['nginx', '-T']).stdout
            if 'sites-enabled/' not in self.nginx_text:
                raise InstallError('Nginx must include /etc/nginx/sites-enabled/; custom layouts require manual integration.')
            if (not free_port(80) or not free_port(443)) and run(['systemctl', 'is-active', 'nginx'], check=False).returncode:
                raise InstallError('Ports 80/443 are occupied but the host Nginx is not active. Refusing proxy replacement.')
        elif not free_port(80) or not free_port(443):
            raise InstallError('Another proxy occupies ports 80/443. Nginx will not be installed over it.')
        self.cert_pair = None
        if 'openssl' not in missing:
            self.cert_pair = find_certificate(domain, self.args.cert or self.state.get('cert'), self.args.key or self.state.get('key'),
                                             self.root / 'etc/letsencrypt/live')
        elif self.args.cert or self.args.key:
            raise InstallError('openssl is required to verify explicit certificates before provisioning.')
        if not self.cert_pair:
            # Do not add a competing domain vhost when another application owns it.
            names = re.findall(r'\bserver_name\s+([^;]+);', self.nginx_text)
            if any(domain in group.split() for group in names) and not self.acme_site.exists():
                raise InstallError('Domain already has a Nginx site but no matching valid certificate was found. Supply --cert and --key.')
            self.acme_email = self.prompt('email', 'Let\'s Encrypt email', self.state.get('acme_email'))
            self.validate_email(self.acme_email)
        else:
            self.acme_email = self.state.get('acme_email')
            self.missing = [p for p in self.missing if p != 'certbot']
        if self.args.admin_email: self.validate_email(self.args.admin_email)
        if self.args.admin_password_file:
            p = Path(self.args.admin_password_file)
            if p.is_symlink() or not p.is_file() or p.stat().st_uid != 0 or p.stat().st_mode & 0o077:
                raise InstallError('Admin password file must be root-owned with mode 0600 or stricter.')
        if not self.existing_data and self.args.non_interactive and not (self.args.admin_email and self.args.admin_password_file):
            raise InstallError('New non-interactive installs require --admin-email and --admin-password-file.')
        self.public_url = f'https://{domain}:{self.port}'
        print(f'Plan: {self.public_url} -> 127.0.0.1:{self.backend}; volume={self.volume}; source={self.commit}')
        print('Docker endpoint: ' + (self.docker.endpoint if self.docker else 'new local daemon on fresh host'))
        if self.missing: print('Missing packages: ' + ', '.join(self.missing))
        if self.args.check_only:
            print('Preflight passed; no packages, containers, config or firewall rules changed.')

    @staticmethod
    def validate_email(value):
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value) or len(value)>254:
            raise InstallError('Invalid email')

    def provision(self):
        if not self.missing: return
        packages = []
        if 'docker' in self.missing: packages += ['docker.io', 'docker-compose-v2']
        packages += [p for p in ('nginx', 'openssl', 'certbot') if p in self.missing]
        run(['apt-get', 'update'])
        run(['apt-get', 'install', '-y', *packages])
        if self.docker is None:
            run(['systemctl', 'enable', '--now', 'docker'])
            self.docker = Docker('unix:///var/run/docker.sock')
            self.docker_id = self.docker.json('info', '--format', '{{json .}}')['ID']
        self.docker('compose', 'version')

    def write_release(self):
        release = self.prefix / 'releases' / self.commit
        if release.exists():
            if not (release / '.ako-release').is_file() or (release / '.ako-release').read_text() != self.commit:
                raise InstallError('Unrecognized release directory')
            return release
        release.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='.release-', dir=release.parent))
        try:
            files = run(['git', '-C', self.source, 'ls-files', '-z']).stdout.split('\0')
            for relative in filter(None, files):
                origin = self.source / relative
                if origin.is_symlink() or '..' in Path(relative).parts or Path(relative).is_absolute():
                    raise InstallError('Unsupported source symlink or path')
                dest = staging / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origin, dest)
            (staging / '.ako-release').write_text(self.commit)
            staging.rename(release)
        finally:
            if staging.exists(): shutil.rmtree(staging)
        return release

    def compose(self, *args, **kwargs):
        return self.docker('compose', '-p', 'ako-fx', '-f', self.compose_file, *args, **kwargs)

    def configure_certificate(self):
        if self.cert_pair: return
        webroot = self.root / 'var/lib/ako-fx/acme'
        webroot.mkdir(parents=True, exist_ok=True)
        os.chmod(webroot.parent,0o755); os.chmod(webroot,0o755)
        config = MARKER + f'''server {{
    listen 80;
    listen [::]:80;
    server_name {self.domain};
    location ^~ /.well-known/acme-challenge/ {{ root {webroot}; }}
    location / {{ return 404; }}
}}
'''
        self.deploy_nginx(self.acme_site, self.acme_enabled, config)
        self.save(acme_sha256=sha256(self.acme_site))
        run(['certbot', 'certonly', '--webroot', '-w', webroot, '--non-interactive',
             '--agree-tos', '--email', self.acme_email, '--cert-name', 'ako-fx-' + self.domain,
             '-d', self.domain], umask=0o022)
        self.cert_pair = find_certificate(self.domain, base=self.root / 'etc/letsencrypt/live')
        if not self.cert_pair: raise InstallError('Issued certificate did not pass verification')
        hook = self.root / 'etc/letsencrypt/renewal-hooks/deploy/ako-fx-reload'
        if hook.exists() and not hook.read_text().startswith('#!/bin/sh\n' + MARKER):
            raise InstallError('Unrelated certificate renewal hook already exists')
        atomic_write(hook, '#!/bin/sh\n' + MARKER +
                     f'if [ "$RENEWED_LINEAGE" = "{Path(self.cert_pair[0]).parent}" ]; then\n'
                     '    nginx -t && systemctl reload nginx\nfi\n', 0o700)
        run(['systemctl', 'enable', '--now', 'certbot.timer'])

    def deploy_nginx(self, site, enabled, content):
        check_owned(site)
        previous = site.read_text() if site.exists() else None
        linked = enabled.is_symlink()
        atomic_write(site, content, 0o644)
        if not linked: enabled.symlink_to(site)
        try:
            run(['nginx', '-t'])
            active = run(['systemctl', 'is-active', 'nginx'], check=False).returncode == 0
            run(['systemctl', 'reload' if active else 'start', 'nginx'])
        except Exception:
            if previous is None: site.unlink(missing_ok=True)
            else: atomic_write(site, previous, 0o644)
            if not linked: enabled.unlink(missing_ok=True)
            # Restore the previous configuration without stopping other websites.
            run(['nginx', '-t'], check=False)
            run(['systemctl', 'reload', 'nginx'], check=False)
            raise

    def wait_backend(self):
        last = None
        for _ in range(45):
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{self.backend}/health', timeout=3) as response:
                    data = json.load(response)
                    if data.get('mode') == 'DEMO_ONLY' and data.get('role') == 'gateway': return
            except Exception as error: last = error
            time.sleep(2)
        raise InstallError(f'Gateway did not become reachable: {last}')

    def verify_https(self):
        # Verify SNI and CA trust on loopback, without depending on DNS hairpin routing.
        context = ssl.create_default_context()
        checks = (('/health',200),('/',200),('/api/me',401),('/api/wallet',401),
                  ('/api/accounts',401),('/api/prop/plans',401))
        for path, expected in checks:
            with socket.create_connection(('127.0.0.1', self.port), timeout=10) as raw:
                with context.wrap_socket(raw, server_hostname=self.domain) as connection:
                    connection.sendall(f'GET {path} HTTP/1.0\r\nHost: {self.domain}:{self.port}\r\n\r\n'.encode())
                    data = bytearray()
                    while True:
                        part = connection.recv(8192)
                        if not part: break
                        data.extend(part)
                    header, body = bytes(data).split(b'\r\n\r\n', 1)
                    status = int(header.split(b' ',2)[1])
                    if status != expected:
                        raise InstallError(f'HTTPS {path} returned {status}, expected {expected}')
                    if path == '/health' and json.loads(body).get('mode') != 'DEMO_ONLY':
                        raise InstallError('HTTPS returned an unexpected application')
                    if path == '/' and b'AKO' not in body:
                        raise InstallError('HTTPS did not return the AKO-FX login page')

    def backup(self):
        if not self.existing_data: return
        filename = 'pre-install-' + str(time.time_ns()) + '.db'
        code = ("import os,sqlite3; p='/data/ako.db'; "
                "s=sqlite3.connect('file:'+p+'?mode=ro',uri=True) if os.path.exists(p) else None; "
                f"t=sqlite3.connect('/data/{filename}') if s else None; "
                "s.backup(t) if s else None; t.close() if t else None; s.close() if s else None; "
                f"os.chmod('/data/{filename}',0o600) if s else None")
        # Use a helper on the same named volume; no schema initializer before snapshot.
        name = 'ako-fx-backup-' + str(os.getpid())
        try:
            self.docker('run', '--name', name, '--network', 'none', '--read-only',
                        '--user', '10001:10001', '--mount', f'type=volume,source={self.volume},target=/data',
                        'ako-fx:' + self.commit[:12], 'python', '-c', code)
            target = self.root / 'var/backups/ako-fx'
            target.mkdir(parents=True, exist_ok=True); os.chmod(target,0o700)
            copy = self.docker('cp', name + ':/data/' + filename, target / filename, check=False)
            if copy.returncode == 0:
                os.chmod(target / filename, 0o600)
                print('Consistent database backup: ' + str(target / filename))
            else:
                # An empty existing volume is valid only when the helper found no DB.
                result = self.docker('run', '--rm', '--network', 'none', '--read-only',
                    '--mount', f'type=volume,source={self.volume},target=/data,readonly',
                    'ako-fx:' + self.commit[:12], 'python', '-c',
                    "import os,sys; sys.exit(1 if os.path.exists('/data/ako.db') else 0)",check=False)
                if result.returncode: raise InstallError('Existing DB could not be backed up; refusing update.')
        finally: self.docker('rm', name, check=False)

    def admin(self):
        info = json.loads(self.compose('exec', '-T', 'identity', 'python', '-m',
                                      'ako_fx.manage', 'admin-status').stdout)
        if info['count']:
            print('Existing administrator preserved; no password changed.')
            return
        email = self.prompt('admin_email', 'Initial admin email')
        self.validate_email(email)
        command = ['docker', '--host', self.docker.endpoint, 'compose', '-p', 'ako-fx',
                   '-f', str(self.compose_file), 'exec']
        if self.args.admin_password_file:
            # Feed bytes through stdin, never environment, argv or output.
            command += ['-T', 'identity', 'python', '-m', 'ako_fx.manage', 'create-admin',
                        '--email', email, '--password-stdin']
            with open(self.args.admin_password_file, 'r') as password:
                result = subprocess.run(command, stdin=password, env=docker_environment())
        elif self.args.non_interactive:
            raise InstallError('No admin exists: --admin-email and --admin-password-file are required for non-interactive setup.')
        else:
            command += ['identity', 'python', '-m', 'ako_fx.manage', 'create-admin', '--email', email]
            with open('/dev/tty', 'r+') as tty:
                result = subprocess.run(command, stdin=tty, env=docker_environment())
        if result.returncode: raise InstallError('Admin setup failed; rerun the installer to continue.')

    def helper(self):
        path = self.root / 'usr/local/sbin/ako-fx'
        if path.exists() and not path.read_text().startswith('#!/usr/bin/env bash\n' + MARKER):
            raise InstallError('An unrelated ako-fx helper already exists')
        import shlex
        command = ' '.join(shlex.quote(str(x)) for x in
                           ('docker','--host',self.docker.endpoint,'compose','-p','ako-fx','-f',self.compose_file))
        content = '#!/usr/bin/env bash\n' + MARKER + 'set -euo pipefail\n'
        content += 'unset DOCKER_CONTEXT DOCKER_HOST DOCKER_TLS_VERIFY DOCKER_CERT_PATH\n'
        content += 'case "${1:-status}" in\n'
        content += f'  status) exec {command} ps ;;\n'
        content += f'  logs) exec {command} logs --tail=100 ;;\n'
        content += f'  admin) shift; exec {command} exec identity python -m ako_fx.manage create-admin "$@" ;;\n'
        content += f'  compose) shift; exec {command} "$@" ;;\n'
        content += '  *) echo "Usage: ako-fx {status|logs|admin --email EMAIL|compose ...}" >&2; exit 2 ;;\nesac\n'
        atomic_write(path, content, 0o700)

    def execute(self):
        self.preflight()
        if self.args.check_only: return
        self.provision()
        self.etc.mkdir(parents=True, exist_ok=True); os.chmod(self.etc,0o700)
        self.save(owner='AKO-FX installer v1', domain=self.domain, port=self.port,
                  backend_port=self.backend, volume=self.volume,
                  docker_endpoint=self.docker.endpoint, docker_id=self.docker_id,
                  acme_email=self.acme_email, stage='preparing', requested_commit=self.commit,
                  data_preexisting=self.existing_data or self.state.get('data_preexisting',False))
        release = self.write_release()
        config = compose_config(release,self.commit,self.volume,self.backend)
        if self.compose_file.exists():
            atomic_write(self.etc / 'compose.previous.json',self.compose_file.read_text())
        atomic_write(self.compose_file,json.dumps(config,indent=2)+'\n')
        self.compose('config','--quiet')
        print('Building pinned AKO-FX image ...')
        self.compose('build', 'identity')
        if not self.existing_data:
            self.save(created_volume=True)
            self.docker('volume','create','--label','com.docker.compose.project=ako-fx',
                        '--label','com.docker.compose.volume=ako-data',self.volume)
        if self.state.get('created_volume') and not self.state.get('volume_initialized'):
            # Only initialize an empty volume created by this installer; never chown existing data.
            self.docker('run','--rm','--network','none','--user','0:0',
                '--mount',f'type=volume,source={self.volume},target=/data',
                'ako-fx:' + self.commit[:12], 'python', '-c',
                "import os; assert not os.listdir('/data'), 'Refusing nonempty uninitialized data'; os.chown('/data',10001,10001); os.chmod('/data',0o700)")
            self.save(volume_initialized=True)
        self.backup()
        self.configure_certificate()
        self.save(stage='starting',cert=self.cert_pair[0],key=self.cert_pair[1])
        self.compose('up','-d',*SERVICES)
        self.wait_backend()
        self.admin()
        self.deploy_nginx(self.site,self.enabled,
                          nginx_config(self.domain,self.port,self.backend,*map(safe_path,self.cert_pair)))
        self.save(nginx_sha256=sha256(self.site),stage='verifying')
        self.verify_https()
        if shutil.which('ufw'):
            status=run(['ufw','status']).stdout
            if re.search(r'^Status: active$',status,re.MULTILINE):
                run(['ufw','allow',str(self.port)+'/tcp'])
        self.helper()
        self.save(stage='complete',commit=self.commit)
        print('\nInstallation verified locally. Open: ' + self.public_url)
        print('Login using your existing or newly created admin. No real trading is enabled.')
        print(f'If your VPS provider has a firewall, allow inbound TCP {self.port}.')
        print('Management: sudo ako-fx status | sudo ako-fx logs')


def arguments(argv=None):
    parser=argparse.ArgumentParser(description='AKO-FX coexistence installer')
    for name in ('domain','admin-email','admin-password-file','email','cert','key'):
        parser.add_argument('--'+name)
    parser.add_argument('--port',type=int)
    parser.add_argument('--backend-port',type=int)
    parser.add_argument('--ref',default='main',help='Bootstrap source reference; local checkout uses its exact HEAD')
    parser.add_argument('--check-only',action='store_true')
    parser.add_argument('--non-interactive',action='store_true')
    return parser.parse_args(argv)

def main(argv=None):
    args=arguments(argv)
    if os.geteuid()!=0: raise InstallError('Run as root')
    if sys.version_info<(3,11): raise InstallError('Python 3.11+ is required')
    os.umask(0o077)
    os_info=Path('/etc/os-release').read_text()
    if not re.search(r'^ID="?ubuntu"?$',os_info,re.MULTILINE) or not re.search(r'^VERSION_ID="?24\.04"?$',os_info,re.MULTILINE):
        raise InstallError('Automatic installer supports Ubuntu 24.04 only')
    if args.check_only:
        Installer(args).execute()
        return
    with open('/run/lock/ako-fx-install.lock','w') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise InstallError('Another AKO-FX installer is running')
        Installer(args).execute()

if __name__=='__main__':
    try: main()
    except (InstallError,subprocess.SubprocessError,OSError,ValueError) as error:
        print('AKO-FX installation stopped: '+str(error),file=sys.stderr)
        print('Existing data is retained. Resolve the error and rerun the same command; do not use docker down -v.',file=sys.stderr)
        sys.exit(1)
