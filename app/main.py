import hmac
import logging
import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, delete
from sqlalchemy.orm import sessionmaker
from .database import make_engine, check_environment, environment, User, AuthSession, Conversation, Message, Fact, Apartment, now
from .coordination import consume, acquire, release
from .security import verify_password, token_hash, csrf_for, hash_password
from .services import RouterAI, LABELS, facts_for, fact_rows, upsert_fact, validate_fact, validate_changes, apply_changes, build_context, render_answer, apartment_dict

ROOT = Path(__file__).resolve().parent
COOKIE = 'apartment_session'
SESSION_HOURS = 12

class LoginInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)

class ChatInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content: str = Field(min_length=1, max_length=4000)

class FactInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    value: object


def create_app(database_url=None, ai=None):
    engine = make_engine(database_url)
    factory = sessionmaker(engine, expire_on_commit=False)
    @asynccontextmanager
    async def lifespan(application):
        check_environment(engine)
        yield
        engine.dispose()
    app = FastAPI(title='Квартирный AI', lifespan=lifespan)
    app.state.engine = engine
    app.state.ai = ai or RouterAI()
    app.state.session_factory = factory
    dummy_hash = hash_password(secrets.token_urlsafe(24))
    secure = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
    public_origin = os.getenv('PUBLIC_ORIGIN', '').rstrip('/')
    if not public_origin and environment() == 'preview' and os.getenv('VERCEL_URL'):
        public_origin = 'https://' + os.environ['VERCEL_URL'].rstrip('/')
    if environment() in ('preview', 'production') and (not secure or not public_origin.startswith('https://')):
        raise RuntimeError('В облаке нужны COOKIE_SECURE=true и HTTPS PUBLIC_ORIGIN')
    templates = Jinja2Templates(directory=str(ROOT / 'templates'))
    app.mount('/static', StaticFiles(directory=str(ROOT / 'static')), name='static')

    def db_session():
        with factory() as db:
            yield db

    def current_user(request: Request, db=Depends(db_session)):
        token = request.cookies.get(COOKIE, '')
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token), AuthSession.expires_at > now()))
        if not session:
            raise HTTPException(401, 'Войдите в приложение')
        user = db.get(User, session.user_id)
        if not user:
            raise HTTPException(401, 'Сессия недействительна')
        return user

    def admin(user=Depends(current_user)):
        if user.role != 'admin':
            raise HTTPException(403, 'Требуется роль администратора')
        return user

    def owned_conversation(db, uid, cid):
        conv = db.scalar(select(Conversation).where(Conversation.id == cid, Conversation.user_id == uid))
        if not conv:
            raise HTTPException(404, 'Диалог не найден')
        return conv

    def user_dict(user):
        return dict(id=user.id, username=user.username, display_name=user.display_name, role=user.role)

    def messages_for(db, cid):
        return [dict(id=m.id, role=m.role, content=m.content, created_at=m.created_at.isoformat()) for m in db.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.id))]

    @app.middleware('http')
    async def csrf_and_headers(request, call_next):
        if request.method in ('POST','PUT','PATCH','DELETE'):
            header = request.headers.get('x-csrf-token','')
            cookie = request.cookies.get('csrf_token','')
            session_token = request.cookies.get(COOKIE)
            expected = csrf_for(session_token) if session_token else cookie
            origin = request.headers.get('origin')
            if not header or not cookie or not hmac.compare_digest(header,cookie) or not hmac.compare_digest(header,expected):
                return JSONResponse({'detail':'Проверка CSRF не пройдена. Обновите страницу.'}, status_code=403)
            if origin and origin.rstrip('/') != (public_origin or str(request.base_url).rstrip('/')):
                return JSONResponse({'detail':'Недопустимый источник запроса'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.get('/', response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse(request=request, name='index.html', context={})

    @app.get('/admin', response_class=HTMLResponse)
    def admin_page(request: Request, user=Depends(admin)):
        return templates.TemplateResponse(request=request, name='index.html', context={})

    @app.get('/api/bootstrap')
    def bootstrap(request: Request, db=Depends(db_session)):
        session_token = request.cookies.get(COOKIE)
        csrf = csrf_for(session_token) if session_token else secrets.token_urlsafe(32)
        user = None
        try:
            user = current_user(request, db)
        except HTTPException:
            pass
        response = JSONResponse({'user':user_dict(user) if user else None, 'csrf_token':csrf, 'labels':LABELS, 'ai_configured':bool(os.getenv('ROUTERAI_API_KEY'))})
        response.set_cookie('csrf_token', csrf, httponly=False, samesite='strict', secure=secure, max_age=SESSION_HOURS * 3600)
        return response

    @app.post('/api/login')
    def login(data: LoginInput, request: Request, db=Depends(db_session)):
        if not consume(engine, 'login-global', 'global', 200, 300) or not consume(engine, 'login-user', data.username.strip().lower(), 15, 300):
            raise HTTPException(429, 'Слишком много попыток. Повторите позже.')
        user = db.scalar(select(User).where(User.username == data.username))
        valid = verify_password(data.password, user.password_hash if user else dummy_hash)
        if not user or not valid:
            raise HTTPException(401, 'Неверный логин или пароль')
        previous = request.cookies.get(COOKIE)
        if previous:
            db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(previous)))
        db.execute(delete(AuthSession).where(AuthSession.expires_at <= now()))
        token = secrets.token_urlsafe(32)
        db.add(AuthSession(user_id=user.id, token_hash=token_hash(token), expires_at=now()+timedelta(hours=SESSION_HOURS)))
        db.commit()
        response = JSONResponse({'user':user_dict(user), 'csrf_token':csrf_for(token)})
        response.set_cookie(COOKIE, token, httponly=True, secure=secure, samesite='strict', max_age=SESSION_HOURS*3600)
        response.set_cookie('csrf_token', csrf_for(token), secure=secure, samesite='strict', max_age=SESSION_HOURS*3600)
        return response

    @app.post('/api/logout')
    def logout(request: Request, user=Depends(current_user), db=Depends(db_session)):
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(request.cookies.get(COOKIE,''))))
        db.commit()
        response = JSONResponse({'ok':True})
        response.delete_cookie(COOKIE)
        response.delete_cookie('csrf_token')
        return response

    @app.get('/api/apartments')
    def apartments(user=Depends(current_user), db=Depends(db_session)):
        return [apartment_dict(a) for a in db.scalars(select(Apartment).order_by(Apartment.price))]

    @app.get('/api/facts')
    def own_facts(user=Depends(current_user), db=Depends(db_session)):
        return fact_rows(db, user.id)

    def save_fact(db, uid, key, value, source):
        lease = acquire(engine, uid)
        if not lease: raise HTTPException(409, 'Данные пользователя сейчас изменяются. Повторите позже.')
        try:
            try:
                changed = upsert_fact(db, uid, key, value, source)
            except ValueError as exc:
                raise HTTPException(422, str(exc))
            db.commit()
            return {'changed':changed, 'facts':fact_rows(db, uid)}
        finally:
            release(engine, uid, lease)

    def remove_fact(db, uid, key):
        lease = acquire(engine, uid)
        if not lease: raise HTTPException(409, 'Данные пользователя сейчас изменяются. Повторите позже.')
        try:
            row = db.scalar(select(Fact).where(Fact.user_id == uid, Fact.fact_key == key))
            if not row: raise HTTPException(404, 'Факт не найден')
            db.delete(row)
            db.commit()
            return {'facts':fact_rows(db, uid)}
        finally:
            release(engine, uid, lease)

    @app.put('/api/facts/{key}')
    def edit_fact(key: str, data: FactInput, user=Depends(current_user), db=Depends(db_session)):
        return save_fact(db, user.id, key, data.value, 'manual')

    @app.delete('/api/facts/{key}')
    def delete_fact(key: str, user=Depends(current_user), db=Depends(db_session)):
        return remove_fact(db, user.id, key)

    @app.get('/api/conversations')
    def conversations(user=Depends(current_user), db=Depends(db_session)):
        return [dict(id=c.id,title=c.title,updated_at=c.updated_at.isoformat()) for c in db.scalars(select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.updated_at.desc()))]

    @app.post('/api/conversations')
    def new_conversation(user=Depends(current_user), db=Depends(db_session)):
        conv = Conversation(user_id=user.id)
        db.add(conv)
        db.commit()
        return {'id':conv.id, 'title':conv.title}

    @app.get('/api/conversations/{cid}')
    def conversation(cid: int, user=Depends(current_user), db=Depends(db_session)):
        conv = owned_conversation(db, user.id, cid)
        return {'id':conv.id, 'title':conv.title, 'messages':messages_for(db,cid)}

    @app.delete('/api/conversations/{cid}')
    def delete_conversation(cid: int, user=Depends(current_user), db=Depends(db_session)):
        conv = owned_conversation(db, user.id, cid)
        lease = acquire(engine, user.id)
        if not lease: raise HTTPException(409, 'Данные пользователя сейчас изменяются. Повторите позже.')
        try:
            db.delete(conv)
            db.commit()
            return {'ok':True}
        finally:
            release(engine, user.id, lease)

    @app.post('/api/conversations/{cid}/messages')
    def send_message(cid: int, data: ChatInput, user=Depends(current_user), db=Depends(db_session)):
        if not data.content.strip():
            raise HTTPException(422, 'Сообщение пустое')
        owned_conversation(db, user.id, cid)
        if not consume(engine, 'chat-global', 'global', 300, 3600) or not consume(engine, 'chat-user', str(user.id), 20, 3600):
            raise HTTPException(429, 'Лимит запросов к AI исчерпан. Попробуйте позже.')
        lease = acquire(engine, user.id)
        if not lease: raise HTTPException(409, 'Данные пользователя сейчас изменяются. Повторите позже.')
        try:
            conv = owned_conversation(db, user.id, cid)
            msg = Message(conversation_id=cid, role='user', content=data.content.strip())
            db.add(msg)
            if conv.title == 'Новый подбор': conv.title = msg.content[:55]
            conv.updated_at = now()
            db.commit()  # Preserve the user message even if the provider fails.
            updated, warning = False, None
            app.state.memory_error = None
            app.state.sales_error = None
            try:
                raw = app.state.ai.extract(msg.content, facts_for(db,user.id))
                changes = validate_changes(raw, msg.content)
                updated = apply_changes(db,user.id,changes,msg.id)
                db.commit()
            except Exception as exc:
                app.state.memory_error = type(exc).__name__ + (': ' + str(exc) if isinstance(exc, ValueError) else '')
                logging.getLogger(__name__).warning('Memory update rejected: %s', app.state.memory_error)
                db.rollback()
                warning = 'Не удалось безопасно обновить память. Сообщение сохранено; предпочтения можно указать в «Мои данные».'
            context = build_context(db,user.id,cid)
            context['memory_extraction_failed'] = warning is not None
            try:
                raw = app.state.ai.respond(context)
                answer = render_answer(raw,context)
            except Exception as exc:
                app.state.sales_error = type(exc).__name__ + (': ' + str(exc) if isinstance(exc, ValueError) else '')
                logging.getLogger(__name__).warning('Sales response rejected: %s', app.state.sales_error)
                return JSONResponse({'detail':'RouterAI недоступен или вернул некорректный ответ. Проверьте ключ и соединение. Ваше сообщение сохранено.',
                    'user_message_saved':True, 'memory_updated':updated, 'warning':warning},status_code=502)
            db.add(Message(conversation_id=cid, role='assistant', content=answer))
            conv.updated_at = now()
            db.commit()
            return {'answer':answer,'memory_updated':updated,'facts':fact_rows(db,user.id), 'used_facts':context['facts'], 'warning':warning}
        finally:
            release(engine, user.id, lease)

    @app.get('/api/admin/users')
    def users(user=Depends(admin), db=Depends(db_session)):
        return [user_dict(u) for u in db.scalars(select(User).order_by(User.id))]

    def existing_user(db, uid):
        target = db.get(User,uid)
        if not target: raise HTTPException(404,'Пользователь не найден')
        return target

    @app.get('/api/admin/users/{uid}')
    def admin_user(uid: int, user=Depends(admin), db=Depends(db_session)):
        target = existing_user(db,uid)
        convs = list(db.scalars(select(Conversation).where(Conversation.user_id == uid).order_by(Conversation.updated_at.desc())))
        return {'user':user_dict(target),'facts':fact_rows(db,uid),'conversations':[
            {'id':c.id,'title':c.title,'messages':messages_for(db,c.id)} for c in convs]}

    @app.put('/api/admin/users/{uid}/facts/{key}')
    def admin_edit_fact(uid: int,key: str,data: FactInput,user=Depends(admin),db=Depends(db_session)):
        existing_user(db,uid)
        return save_fact(db,uid,key,data.value,'admin')

    @app.delete('/api/admin/users/{uid}/facts/{key}')
    def admin_delete_fact(uid: int,key: str,user=Depends(admin),db=Depends(db_session)):
        existing_user(db,uid)
        return remove_fact(db,uid,key)

    return app

app = create_app()
