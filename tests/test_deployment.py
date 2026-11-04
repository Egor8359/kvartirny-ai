import os
import uuid
import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.database import make_engine, initialize, check_environment, User, Apartment, Fact, EnvironmentIdentity
from app.coordination import consume, acquire, release
from app.main import create_app
from app.security import hash_password


def test_init_is_explicit_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_ENV','test')
    url = 'sqlite:///' + (tmp_path/'init.db').as_posix()
    app = create_app(url)
    from sqlalchemy import inspect
    assert not inspect(app.state.engine).has_table('users')
    initialize(app.state.engine)
    with Session(app.state.engine) as db:
        db.add(User(username='kept', display_name='Kept', role='admin', password_hash='unchanged'))
        db.commit()
    initialize(app.state.engine)
    with Session(app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Apartment)) == 12
        user = db.scalar(select(User).where(User.username == 'kept'))
        assert (user.role,user.password_hash) == ('admin','unchanged')
    with TestClient(app) as client:
        assert client.get('/').status_code == 200
        assert client.get('/static/style.css').status_code == 200
        assert client.get('/static/app.js').status_code == 200
    app.state.engine.dispose()


def test_explicit_account_creation_never_overwrites(tmp_path, monkeypatch):
    import sys
    from app import setup
    from app.security import verify_password
    monkeypatch.setenv('APP_ENV','test')
    url='sqlite:///' + (tmp_path/'accounts.db').as_posix()
    monkeypatch.setenv('DATABASE_URL',url)
    engine=make_engine(url); initialize(engine)
    monkeypatch.setattr(sys, 'argv', ['setup','create-user','--username','demo','--name','Demo','--role','client'])
    monkeypatch.setattr(setup.getpass, 'getpass', lambda prompt: 'safe-test-password!')
    setup.main()
    with Session(engine) as db:
        user=db.scalar(select(User).where(User.username=='demo'))
        assert user.role == 'client' and verify_password('safe-test-password!',user.password_hash)
        original=user.password_hash
    monkeypatch.setattr(sys, 'argv', ['setup','create-user','--username','demo','--name','Admin','--role','admin'])
    with pytest.raises(SystemExit): setup.main()
    with Session(engine) as db:
        user=db.scalar(select(User).where(User.username=='demo'))
        assert user.role == 'client' and user.password_hash == original
    engine.dispose()


def test_shared_quota_and_lease(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_ENV','test')
    url='sqlite:///' + (tmp_path/'shared.db').as_posix()
    a=make_engine(url); b=make_engine(url); initialize(a)
    with Session(a) as db:
        user=User(username='shared',display_name='Shared',role='client',password_hash='hash')
        db.add(user); db.commit(); uid=user.id
    assert consume(a,'unit','person',2,300)
    assert consume(b,'unit','person',2,300)
    assert not consume(a,'unit','person',2,300)
    lease=acquire(a,uid); assert lease
    assert acquire(b,uid) is None
    release(b,uid,'wrong-token'); assert acquire(b,uid) is None
    release(a,uid,lease); lease2=acquire(b,uid); assert lease2
    release(b,uid,lease2); a.dispose(); b.dispose()


def test_cross_instance_chat_blocks_memory_edits(tmp_path, monkeypatch):
    import json, threading
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setenv('APP_ENV','test')
    url='sqlite:///' + (tmp_path/'concurrent.db').as_posix()
    started=threading.Event(); finish=threading.Event()
    class SlowAI:
        def extract(self, message, facts):
            started.set()
            assert finish.wait(10)
            return json.dumps({'changes':[]})
        def respond(self, context):
            return json.dumps({'apartment_ids':[],'reasons':[],'next_question':'continue','intent':'selection'})
    one=create_app(url,SlowAI()); two=create_app(url,SlowAI()); initialize(one.state.engine)
    with Session(one.state.engine) as db:
        db.add(User(username='concurrent',display_name='Client',role='client',password_hash=hash_password('concurrent-test-password!')))
        db.commit()
    with TestClient(one) as a, TestClient(two) as b:
        for client in (a,b):
            csrf=client.get('/api/bootstrap').json()['csrf_token']
            result=client.post('/api/login',headers={'X-CSRF-Token':csrf},json={'username':'concurrent','password':'concurrent-test-password!'})
            assert result.status_code == 200
            client.headers['X-CSRF-Token']=result.json()['csrf_token']
        cid=a.post('/api/conversations').json()['id']
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(a.post, f'/api/conversations/{cid}/messages', json={'content':'Здравствуйте'})
            try:
                assert started.wait(10)
                assert b.put('/api/facts/rooms',json={'value':2}).status_code == 409
                assert b.delete(f'/api/conversations/{cid}').status_code == 409
            finally:
                finish.set()
            assert pending.result(timeout=20).status_code == 200
        assert b.put('/api/facts/rooms',json={'value':2}).status_code == 200


def test_limits_enforced_across_app_instances(tmp_path, monkeypatch):
    import app.main as main_module
    monkeypatch.setenv('APP_ENV','test')
    url='sqlite:///' + (tmp_path/'limits.db').as_posix()
    one=create_app(url); two=create_app(url); initialize(one.state.engine)
    with Session(one.state.engine) as db:
        user=User(username='quota-user',display_name='Client',role='client',password_hash=hash_password('quota-test-password!'))
        db.add(user); db.commit(); uid=user.id
    with TestClient(one) as a, TestClient(two) as b:
        for client in (a,b):
            client.headers['X-CSRF-Token']=client.get('/api/bootstrap').json()['csrf_token']
        original=main_module.verify_password
        monkeypatch.setattr(main_module,'verify_password',lambda *_: False)
        for i in range(15):
            assert (a if i % 2 else b).post('/api/login',json={'username':'missing-user','password':'wrong'}).status_code == 401
        assert a.post('/api/login',json={'username':'missing-user','password':'wrong'}).status_code == 429
        monkeypatch.setattr(main_module,'verify_password',original)
        response=b.post('/api/login',json={'username':'quota-user','password':'quota-test-password!'})
        assert response.status_code == 200
        b.headers['X-CSRF-Token']=response.json()['csrf_token']
        cid=b.post('/api/conversations').json()['id']
        for _ in range(20): assert consume(one.state.engine,'chat-user',str(uid),20,3600)
        assert b.post(f'/api/conversations/{cid}/messages',json={'content':'test'}).status_code == 429
        assert b.get(f'/api/conversations/{cid}').json()['messages'] == []


def test_secure_cookie_and_origin(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_ENV','test')
    monkeypatch.setenv('COOKIE_SECURE','true')
    monkeypatch.setenv('PUBLIC_ORIGIN','https://test.example')
    app=create_app('sqlite:///' + (tmp_path/'https.db').as_posix())
    initialize(app.state.engine)
    with TestClient(app,base_url='https://test.example') as client:
        boot=client.get('/api/bootstrap')
        assert 'Secure' in boot.headers['set-cookie']
        token=boot.json()['csrf_token']
        assert client.post('/api/login',headers={'X-CSRF-Token':token,'Origin':'https://evil.example'},json={'username':'x','password':'x'}).status_code == 403
        assert client.post('/api/login',headers={'X-CSRF-Token':token,'Origin':'https://test.example'},json={'username':'x','password':'x'}).status_code == 401


def test_environment_identity_refuses_cross_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_ENV','test')
    engine=make_engine('sqlite:///' + (tmp_path/'env.db').as_posix())
    initialize(engine)
    monkeypatch.setenv('APP_ENV','preview')
    with pytest.raises(RuntimeError): initialize(engine)
    with pytest.raises(RuntimeError): check_environment(engine)
    with Session(engine) as db: assert db.get(EnvironmentIdentity,1).name == 'test'
    monkeypatch.setenv('APP_ENV','development')
    with pytest.raises(RuntimeError): check_environment(engine)
    engine.dispose()


@pytest.mark.skipif(not os.getenv('TEST_POSTGRES_URL'), reason='TEST_POSTGRES_URL не задан')
def test_postgres_isolated_integration(monkeypatch):
    from sqlalchemy.engine import make_url
    url=os.environ['TEST_POSTGRES_URL']
    parsed=make_url(url)
    assert parsed.database == 'apartment_test' and os.getenv('ALLOW_TEST_DATABASE') == '1', 'Только отдельная тестовая база apartment_test'
    monkeypatch.setenv('APP_ENV','test')
    engine=make_engine(url)
    initialize(engine); initialize(engine)
    name='test_'+uuid.uuid4().hex
    with Session(engine) as db:
        db.add(User(username=name,display_name='Проверка',role='client',password_hash=hash_password('test-only-password!')))
        db.commit()
        user=db.scalar(select(User).where(User.username == name)); uid=user.id
        db.add(Fact(user_id=uid,fact_key='rooms',fact_value='2',source='manual'))
        db.commit()
    initialize(engine)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Apartment)) == 12
        assert db.scalar(select(Fact).where(Fact.user_id == uid)).fact_value == '2'
    assert consume(engine,'pg-test',name,1,300)
    assert not consume(engine,'pg-test',name,1,300)
    lease=acquire(engine,uid); assert lease and acquire(engine,uid) is None
    release(engine,uid,lease)
    class FakeAI:
        def extract(self, message, facts): return '{"changes":[]}'
        def respond(self, context):
            import json
            return json.dumps({'apartment_ids': [], 'reasons': [], 'next_question':'continue', 'intent':'selection'})
    app=create_app(url, FakeAI())
    with TestClient(app) as client:
        token=client.get('/api/bootstrap').json()['csrf_token']
        response=client.post('/api/login',headers={'X-CSRF-Token':token},json={'username':name,'password':'test-only-password!'})
        assert response.status_code == 200
        csrf=response.json()['csrf_token']; client.headers['X-CSRF-Token']=csrf
        assert client.get('/api/facts').json()[0]['value'] == 2
        assert client.get('/api/admin/users').status_code == 403
        cid=client.post('/api/conversations').json()['id']
        response=client.post(f'/api/conversations/{cid}/messages',json={'content':'Что подходит?'})
        assert response.status_code == 200 and 'B-' in response.json()['answer']
        assert len(client.get(f'/api/conversations/{cid}').json()['messages']) == 2
        assert client.post('/api/logout').status_code == 200
        token=client.get('/api/bootstrap').json()['csrf_token']
        assert client.post('/api/login',headers={'X-CSRF-Token':token},json={'username':name,'password':'test-only-password!'}).status_code == 200
        assert client.get('/api/facts').json()[0]['value'] == 2
        assert len(client.get(f'/api/conversations/{cid}').json()['messages']) == 2
        with Session(engine) as db:
            other = User(username='other_'+uuid.uuid4().hex, display_name='Other', role='client', password_hash=hash_password('other-test-password!'))
            db.add(other); db.commit(); other_name = other.username
        token=client.get('/api/bootstrap').json()['csrf_token']
        response=client.post('/api/login',headers={'X-CSRF-Token':token},json={'username':other_name,'password':'other-test-password!'})
        assert response.status_code == 200
        assert client.get(f'/api/conversations/{cid}').status_code == 404
        assert client.get('/api/facts').json() == []
    engine.dispose()
