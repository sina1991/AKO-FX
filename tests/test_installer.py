import contextlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from scripts import installer as ins
from ako_fx import manage

SHA = 'a' * 40
CERT = '/etc/letsencrypt/live/30na-dashboard/fullchain.pem'
KEY = '/etc/letsencrypt/live/30na-dashboard/privkey.pem'


def result(stdout='', code=0):
    return subprocess.CompletedProcess([], code, stdout, 'mock command failed' if code else '')


def container(service='identity', volume='ako-fx_ako-data', running=True):
    return {'Config': {'Labels': {'com.docker.compose.project':'ako-fx',
            'com.docker.compose.service':service}, 'Cmd':['python','-m','ako_fx.server']},
            'State':{'Running':running},
            'Mounts':[{'Destination':'/data','Type':'volume','Name':volume}],
            'HostConfig':{'PortBindings':{}}, 'NetworkSettings':{'Ports':{}}}


class DockerFake:
    endpoint='unix:///var/run/docker.sock'
    def __init__(self): self.calls=[]; self.id='local-daemon-1'
    def __call__(self,*args,**kwargs):
        self.calls.append(args)
        if 'admin-status' in args: return result('{"count":1}')
        return result()
    def json(self,*args):
        self.calls.append(args)
        if args[0]=='info': return {'ID':self.id,'DockerRootDir':'/var/lib/docker'}
        return []


class InstallerLogic(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        for p in ('etc/nginx/sites-enabled','etc/nginx/sites-available'):
            (self.root/p).mkdir(parents=True)
        self.original=self.root/'etc/nginx/sites-available/30na'
        self.original.write_text('Existing 30nA content must stay byte-identical\n')
        self.docker=DockerFake()
        self.args=ins.arguments(['--domain','x.30na.top','--non-interactive'])
        self.calls=[]
    def tearDown(self): self.tmp.cleanup()
    def fake_run(self,args,**kwargs):
        self.calls.append(tuple(str(a) for a in args))
        if 'rev-parse' in args: return result(SHA+'\n')
        if 'status' in args and args[0]=='git': return result()
        if args[:2]==['nginx','-T']:
            return result('# configuration file /etc/nginx/sites-enabled/30na:\nserver { server_name x.30na.top; }')
        return result()
    @contextlib.contextmanager
    def environment(self,**extra):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(ins,'run',side_effect=self.fake_run))
            stack.enter_context(patch.object(ins,'root_owned',return_value=True))
            stack.enter_context(patch.object(ins,'Docker',return_value=self.docker))
            stack.enter_context(patch.object(ins,'docker_endpoint',return_value=self.docker.endpoint))
            stack.enter_context(patch.object(ins,'inspect_install',return_value=([container()], 'ako-fx_ako-data', True)))
            stack.enter_context(patch.object(ins,'free_port',return_value=True))
            stack.enter_context(patch.object(ins,'find_certificate',return_value=(CERT,KEY)))
            stack.enter_context(patch.object(ins.shutil,'which',side_effect=lambda x:'/usr/bin/'+x if x!='ufw' else None))
            for name,value in extra.items(): stack.enter_context(patch.object(ins,name,value))
            yield
    def test_domain_rejects_nginx_and_shell_injection(self):
        self.assertEqual(ins.domain_name('X.30na.top'),'x.30na.top')
        for value in ('127.0.0.1','x;return 200;','https://x.30na.top','x.30na.top:8443','x\n.example','-x.example','x..top'):
            with self.subTest(value=value),self.assertRaises(ins.InstallError): ins.domain_name(value)
    def test_choose_free_fallback_port(self):
        with patch.object(ins,'free_port',side_effect=lambda p:p not in (8443,8444)):
            self.assertEqual(ins.choose_port(None,8443),8445)
            with self.assertRaises(ins.InstallError): ins.choose_port(8443,8443)
            self.assertEqual(ins.choose_port(None,8443,reserved=(8445,)),8446)
    def test_real_bound_port_is_not_free(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));sock.listen()
            self.assertFalse(ins.free_port(sock.getsockname()[1]))
    def test_compose_preserves_volume_and_limits_public_exposure(self):
        c=ins.compose_config(Path('/opt/ako-fx/releases/'+SHA),SHA,'existing-volume',9087)
        self.assertEqual(c['volumes']['ako-data'],{'name':'existing-volume','external':True})
        self.assertEqual(c['services']['gateway']['ports'],['127.0.0.1:9087:8080'])
        self.assertIn('host-access',c['services']['gateway']['networks'])
        self.assertEqual(set(c['services']),set(ins.SERVICES))
        self.assertNotIn('proxy',c['services'])
        for role in ins.SERVICES[:-1]: self.assertNotIn('ports',c['services'][role])
    def test_nginx_retains_nonstandard_host_port(self):
        text=ins.nginx_config('x.30na.top',8443,9080,CERT,KEY)
        self.assertIn('proxy_set_header Host $http_host;',text)
        self.assertIn('listen 8443 ssl;',text)
        self.assertIn('127.0.0.1:9080',text)
        self.assertNotIn('listen 443 ',text)
        with self.assertRaises(ins.InstallError): ins.safe_path('/tmp/bad";x')
    def test_check_only_has_no_persistent_writes(self):
        self.args.check_only=True
        before={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with self.environment(): ins.Installer(self.args,root=self.root).execute()
        after={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)
        self.assertFalse(any('build' in c or 'up' in c for c in self.docker.calls))
    def test_full_existing_install_reuses_admin_and_other_site(self):
        before=self.original.read_bytes()
        with self.environment():
            obj=ins.Installer(self.args,root=self.root)
            with patch.object(obj,'write_release',return_value=self.root/'release'), \
                 patch.object(obj,'backup') as backup, \
                 patch.object(obj,'wait_backend'),patch.object(obj,'verify_https'):
                obj.execute();backup.assert_called_once()
        self.assertEqual(self.original.read_bytes(),before)
        state=json.loads(obj.state_file.read_text())
        self.assertEqual((state['stage'],state['volume']),('complete','ako-fx_ako-data'))
        self.assertEqual(state['docker_endpoint'],self.docker.endpoint)
        self.assertTrue(obj.enabled.is_symlink())
        self.assertFalse(any('create-admin' in c for c in self.docker.calls))
        self.assertFalse(any('stop' in c or 'prune' in c or 'down' in c for c in self.docker.calls))
        self.assertFalse(any(c[0]=='certbot' for c in self.calls))
        self.assertTrue((self.root/'usr/local/sbin/ako-fx').exists())
    def test_nginx_failure_rolls_back_only_owned_file(self):
        obj=ins.Installer(self.args,root=self.root)
        count=0
        def command(args,**kwargs):
            nonlocal count
            if args[:2]==['nginx','-t']:
                count+=1
                if count==1: raise ins.InstallError('Invalid config')
            return result()
        with patch.object(ins,'run',side_effect=command):
            with self.assertRaises(ins.InstallError): obj.deploy_nginx(obj.site,obj.enabled,ins.MARKER+'bad')
        self.assertFalse(obj.site.exists());self.assertFalse(obj.enabled.exists())
        self.assertIn('byte-identical',self.original.read_text())
    def test_nginx_existing_owned_config_restored_on_failure(self):
        obj=ins.Installer(self.args,root=self.root)
        old=ins.MARKER+'old config\n'; obj.site.write_text(old);obj.enabled.symlink_to(obj.site)
        with patch.object(ins,'run',side_effect=[ins.InstallError('bad'),result(),result()]):
            with self.assertRaises(ins.InstallError): obj.deploy_nginx(obj.site,obj.enabled,ins.MARKER+'new')
        self.assertEqual(obj.site.read_text(),old);self.assertTrue(obj.enabled.is_symlink())
    def test_foreign_config_or_modified_owned_config_is_refused(self):
        obj=ins.Installer(self.args,root=self.root)
        obj.site.write_text('Unrelated file')
        with self.environment(),self.assertRaises(ins.InstallError): obj.preflight()
        obj.site.write_text(ins.MARKER+'ours')
        with self.assertRaises(ins.InstallError): ins.check_owned(obj.site,'wrong-hash')
    def test_foreign_enabled_symlink_refused(self):
        obj=ins.Installer(self.args,root=self.root);obj.enabled.symlink_to(self.original)
        with self.environment(),self.assertRaises(ins.InstallError): obj.preflight()
    def test_changed_daemon_refused(self):
        obj=ins.Installer(self.args,root=self.root)
        obj.save(owner='AKO-FX installer v1',domain='x.30na.top',docker_id='different')
        with self.environment(),self.assertRaisesRegex(ins.InstallError,'identity changed'): obj.preflight()
    def test_missing_stored_volume_never_becomes_empty_database(self):
        obj=ins.Installer(self.args,root=self.root)
        obj.save(owner='AKO-FX installer v1',domain='x.30na.top',volume='ako-fx_ako-data',
                 docker_id=self.docker.id,volume_initialized=True)
        with self.environment(),patch.object(ins,'inspect_install',return_value=([],'ako-fx_ako-data',False)):
            with self.assertRaisesRegex(ins.InstallError,'volume is missing'): obj.preflight()
    def test_missing_certificate_on_existing_domain_stops_before_changes(self):
        with self.environment(),patch.object(ins,'find_certificate',return_value=None):
            obj=ins.Installer(self.args,root=self.root)
            with self.assertRaisesRegex(ins.InstallError,'already has a Nginx site'): obj.preflight()
        self.assertFalse(obj.state_file.exists())
    def test_resume_domain_mismatch_refused(self):
        obj=ins.Installer(self.args,root=self.root)
        obj.save(owner='AKO-FX installer v1',domain='other.example.com')
        with self.environment(),self.assertRaisesRegex(ins.InstallError,'domain'): obj.preflight()
    def test_https_reload_readiness_is_retried(self):
        obj=ins.Installer(self.args,root=self.root)
        with patch.object(obj,'verify_https',side_effect=[ConnectionRefusedError(),None]) as verify,patch.object(ins.time,'sleep'):
            obj.wait_https()
            self.assertEqual(verify.call_count,2)
    def test_https_certificate_failure_is_not_hidden_by_retry(self):
        import ssl
        obj=ins.Installer(self.args,root=self.root)
        with patch.object(obj,'verify_https',side_effect=ssl.SSLCertVerificationError('wrong certificate')) as verify:
            with self.assertRaises(ssl.SSLCertVerificationError):obj.wait_https()
            self.assertEqual(verify.call_count,1)
    def test_remote_docker_endpoint_refused(self):
        with self.assertRaises(ins.InstallError): ins.Docker('ssh://host')
    def test_docker_environment_cannot_redirect_selected_daemon(self):
        with patch.dict(os.environ,{'DOCKER_CONTEXT':'sandbox','DOCKER_HOST':'unix:///wrong'}),patch.object(ins,'run',return_value=result()) as call:
            ins.Docker('unix:///safe')('info')
            self.assertEqual(call.call_args.args[0],['docker','--host','unix:///safe','info'])
            self.assertNotIn('DOCKER_CONTEXT',call.call_args.kwargs['env'])
            self.assertNotIn('DOCKER_HOST',call.call_args.kwargs['env'])
    def test_dedicated_sandbox_daemon_is_refused(self):
        self.docker.json=lambda *a:{'ID':'one','DockerRootDir':'/var/lib/30na-sandbox/.local/share/docker'}
        with self.environment(),self.assertRaisesRegex(ins.InstallError,'sandbox'): ins.Installer(self.args,root=self.root).preflight()
    def test_unsafe_password_file_permissions_refused(self):
        secret=self.root/'secret';secret.write_text('not-printed-password');secret.chmod(0o644)
        self.args.admin_password_file=str(secret)
        with self.environment(),self.assertRaisesRegex(ins.InstallError,'password file'): ins.Installer(self.args,root=self.root).preflight()
    def test_new_noninteractive_setup_requires_credentials_before_writes(self):
        with self.environment(),patch.object(ins,'inspect_install',return_value=([],'ako-fx_ako-data',False)):
            obj=ins.Installer(self.args,root=self.root)
            with self.assertRaisesRegex(ins.InstallError,'non-interactive'): obj.preflight()
            self.assertFalse(obj.state_file.exists())


class Adoption(unittest.TestCase):
    def fake(self,containers,volume_result=None):
        docker=Mock()
        docker.side_effect=lambda *a,**kw:result('one\ntwo' if a[0]=='ps' else json.dumps(volume_result or [{}]))
        docker.json.return_value=containers
        return docker
    def test_existing_volume_adopted_exactly(self):
        cs=[container(),container('gateway')]
        cs[0]['Mounts'][0]['Name']='custom-real-data';cs[1]['Mounts'][0]['Name']='custom-real-data'
        _,volume,exists=ins.inspect_install(self.fake(cs))
        self.assertEqual(volume,'custom-real-data');self.assertTrue(exists)
    def test_multiple_volumes_refused(self):
        with self.assertRaises(ins.InstallError): ins.inspect_install(self.fake([container(),container('gateway','different')]))
    def test_unknown_container_refused(self):
        with self.assertRaises(ins.InstallError): ins.inspect_install(self.fake([container('unrelated')]))
    def test_bind_mount_refused(self):
        c=container();c['Mounts'][0]['Type']='bind'
        with self.assertRaises(ins.InstallError): ins.inspect_install(self.fake([c]))
    def test_recorded_volume_without_containers_is_preserved(self):
        docker=Mock()
        docker.side_effect=lambda *a,**kw:result('' if a[0]=='ps' else '[{}]')
        _,volume,exists=ins.inspect_install(docker,'recorded-custom-volume')
        self.assertEqual(volume,'recorded-custom-volume');self.assertTrue(exists)
    def test_running_caddy_not_stopped_or_adopted(self):
        with self.assertRaises(ins.InstallError): ins.inspect_install(self.fake([container('proxy')]))


class RealCertificate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.base=Path(cls.tmp.name)
        cls.cert=cls.base/'fullchain.pem';cls.key=cls.base/'privkey.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes',
            '-keyout',str(cls.key),'-out',str(cls.cert),'-days','2','-subj','/CN=x.30na.top',
            '-addext','subjectAltName=DNS:x.30na.top'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()
    def test_matching_domain_and_key(self): self.assertTrue(ins.certificate_valid(self.cert,self.key,'x.30na.top'))
    def test_wrong_domain(self): self.assertFalse(ins.certificate_valid(self.cert,self.key,'other.example.com'))
    def test_invalid_key(self):
        with self.assertRaises(ins.InstallError): ins.find_certificate('x.30na.top',self.cert,self.cert)
    def test_openssl_zero_exit_mismatch_is_not_accepted(self):
        with patch.object(ins,'run',return_value=result('Hostname other.example.com does NOT match certificate\n',0)):
            self.assertFalse(ins.certificate_valid(self.cert,self.key,'other.example.com'))
    def test_no_certificate_in_empty_directory(self):
        self.assertIsNone(ins.find_certificate('x.30na.top',base=self.base/'absent'))


class AdminManagement(unittest.TestCase):
    def test_private_stdin_and_status_keep_existing_admin(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'AKO_DB':tmp+'/db'}):
            output=io.StringIO()
            with contextlib.redirect_stdout(output),patch('sys.stdin',io.StringIO('Secret-example-123\n')):
                manage.main(['create-admin','--email','admin@example.com','--password-stdin'])
            self.assertNotIn('Secret-example-123',output.getvalue())
            output=io.StringIO()
            with contextlib.redirect_stdout(output): manage.main(['admin-status'])
            self.assertEqual(json.loads(output.getvalue()),{'count':1})

if __name__=='__main__':unittest.main()
