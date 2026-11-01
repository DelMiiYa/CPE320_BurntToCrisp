from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationInfo, field_validator

UTC = timezone.utc
BANGKOK = timezone(timedelta(hours=7))
COOKIE = 'burningupp_session'
SESSION_SECONDS = 7 * 24 * 60 * 60
PASSWORD_ITERATIONS = 600000
ASSESSMENT_MESSAGE = 'รอกำหนดกติกาการประเมิน ยังไม่มีการคำนวณคะแนน burnout'
DISCLAIMER = (
    'ค่าเฉลี่ยเป็นความรู้สึกที่รายงานเอง 0–4 จากเช็กอิน ไม่ใช่คะแนน burnout หรือการวินิจฉัย '
    'นับเฉพาะสมาชิกปัจจุบันและเช็กอินตั้งแต่วันที่เข้าทีม '
    'สัญญาณความรู้สึกต่ำใช้เช็กอินล่าสุดวันนี้หรือเมื่อวานที่มีค่าไม่เกิน 1 '
    'สัญญาณขาดเช็กอิน 3 วันใช้สมาชิกที่เข้าทีมตั้งแต่วันนี้ลบ 2 วันและไม่มีเช็กอินใน 3 วันล่าสุด '
    'สัญญาณใช้เพื่อเริ่มพูดคุยและติดตามโดยมนุษย์'
)

SCHEMA = '''
CREATE TABLE IF NOT EXISTS organizations (
 id INTEGER PRIMARY KEY,
 name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 120),
 plan TEXT NOT NULL DEFAULT 'trial' CHECK(plan='trial'),
 plan_status TEXT NOT NULL DEFAULT 'active' CHECK(plan_status='active'),
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY,
 organization_id INTEGER NOT NULL REFERENCES organizations(id),
 email TEXT NOT NULL UNIQUE CHECK(length(email)<=254 AND email=lower(trim(email))),
 password_hash TEXT NOT NULL,
 display_name TEXT NOT NULL CHECK(length(trim(display_name)) BETWEEN 1 AND 80),
 org_role TEXT NOT NULL CHECK(org_role IN ('owner','member')),
 personal_goal TEXT NOT NULL DEFAULT '' CHECK(length(personal_goal)<=500),
 created_at TEXT NOT NULL,
 UNIQUE(id,organization_id)
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS teams (
 id INTEGER PRIMARY KEY,
 organization_id INTEGER NOT NULL REFERENCES organizations(id),
 name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 120),
 join_code TEXT NOT NULL UNIQUE CHECK(length(join_code)>=12),
 created_at TEXT NOT NULL,
 UNIQUE(id,organization_id)
);
CREATE TABLE IF NOT EXISTS memberships (
 organization_id INTEGER NOT NULL,
 team_id INTEGER NOT NULL,
 user_id INTEGER NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('manager','member')),
 joined_on TEXT NOT NULL,
 UNIQUE(team_id,user_id),
 FOREIGN KEY(team_id,organization_id) REFERENCES teams(id,organization_id),
 FOREIGN KEY(user_id,organization_id) REFERENCES users(id,organization_id)
);
CREATE TABLE IF NOT EXISTS checkins (
 id INTEGER PRIMARY KEY,
 organization_id INTEGER NOT NULL,
 user_id INTEGER NOT NULL,
 date TEXT NOT NULL,
 mood INTEGER NOT NULL CHECK(typeof(mood)='integer' AND mood BETWEEN 0 AND 4),
 activity TEXT NOT NULL DEFAULT '' CHECK(length(activity)<=200),
 private_note TEXT NOT NULL DEFAULT '' CHECK(length(private_note)<=2000),
 updated_at TEXT NOT NULL,
 UNIQUE(user_id,date),
 FOREIGN KEY(user_id,organization_id) REFERENCES users(id,organization_id)
);
CREATE TABLE IF NOT EXISTS followups (
 id INTEGER PRIMARY KEY,
 organization_id INTEGER NOT NULL,
 team_id INTEGER NOT NULL,
 subject_user_id INTEGER NOT NULL,
 created_by INTEGER NOT NULL,
 action TEXT NOT NULL CHECK(length(trim(action)) BETWEEN 1 AND 1000),
 status TEXT NOT NULL CHECK(status IN ('open','done')),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 FOREIGN KEY(team_id,organization_id) REFERENCES teams(id,organization_id),
 FOREIGN KEY(team_id,subject_user_id) REFERENCES memberships(team_id,user_id),
 FOREIGN KEY(created_by,organization_id) REFERENCES users(id,organization_id)
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS memberships_user ON memberships(user_id,organization_id);
CREATE INDEX IF NOT EXISTS checkins_org_date ON checkins(organization_id,date);
CREATE INDEX IF NOT EXISTS followups_team ON followups(organization_id,team_id);
'''


class Payload(BaseModel):
    model_config = ConfigDict(extra='forbid')

    @field_validator('*', mode='before')
    @classmethod
    def trim_strings(cls, value, info: ValidationInfo):
        if isinstance(value, str) and info.field_name != 'password':
            return value.strip()
        return value


class Credentials(Payload):
    email: StrictStr = Field(..., min_length=3, max_length=254)
    password: StrictStr = Field(..., min_length=1, max_length=128)

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        if not re.fullmatch(r'[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+', value):
            raise ValueError('Invalid email')
        return value.lower()


class RegisterOrganization(Credentials):
    organization_name: StrictStr = Field(..., min_length=1, max_length=120)
    display_name: StrictStr = Field(..., min_length=1, max_length=80)
    password: StrictStr = Field(..., min_length=10, max_length=128)

    @field_validator('password')
    @classmethod
    def nonblank_password(cls, value):
        if not value.strip():
            raise ValueError('Password must not be blank')
        return value


class RegisterMember(Credentials):
    join_code: StrictStr = Field(..., min_length=1, max_length=256)
    display_name: StrictStr = Field(..., min_length=1, max_length=80)
    password: StrictStr = Field(..., min_length=10, max_length=128)

    @field_validator('password')
    @classmethod
    def nonblank_password(cls, value):
        if not value.strip():
            raise ValueError('Password must not be blank')
        return value


class Profile(Payload):
    display_name: StrictStr = Field(..., min_length=1, max_length=80)
    personal_goal: StrictStr = Field(..., max_length=500)


class TeamName(Payload):
    name: StrictStr = Field(..., min_length=1, max_length=120)


class JoinTeam(Payload):
    join_code: StrictStr = Field(..., min_length=1, max_length=256)


class MemberRole(Payload):
    role: Literal['manager', 'member']


class Checkin(Payload):
    mood: StrictInt
    activity: StrictStr = Field('', max_length=200)
    private_note: StrictStr = Field('', max_length=2000)

    @field_validator('mood')
    @classmethod
    def mood_range(cls, value):
        if not 0 <= value <= 4:
            raise ValueError('Mood must be between 0 and 4')
        return value


class NewFollowup(Payload):
    subject_user_id: StrictInt
    action: StrictStr = Field(..., min_length=1, max_length=1000)

    @field_validator('subject_user_id')
    @classmethod
    def positive_id(cls, value):
        if value <= 0:
            raise ValueError('ID must be positive')
        return value


class EditFollowup(Payload):
    action: StrictStr = Field(..., min_length=1, max_length=1000)
    status: Literal['open', 'done']


def utc_now():
    return datetime.now(UTC)


def now_for(app):
    value = app.state.clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeError('app.state.clock must return a timezone-aware datetime')
    return value.astimezone(UTC)


def bangkok_date(value):
    return value.astimezone(BANGKOK).date()


def iso(value):
    return value.astimezone(UTC).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PASSWORD_ITERATIONS)
    return f'pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}'


def verify_password(password, encoded):
    try:
        algorithm, iterations, salt, expected = encoded.split('$')
        rounds = int(iterations)
        if algorithm != 'pbkdf2_sha256' or not 100000 <= rounds <= 2000000:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), rounds)
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


@contextmanager
def connect(path):
    db = sqlite3.connect(str(path), timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
    finally:
        db.close()


def require_user(request: Request):
    token = request.cookies.get(COOKIE)
    if not token or len(token) > 512:
        raise HTTPException(401, 'Unauthenticated')
    with connect(request.app.state.db_path) as db:
        row = db.execute(
            'SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id '
            'WHERE s.token_hash=? AND s.expires_at>?',
            (token_hash(token), iso(now_for(request.app))),
        ).fetchone()
    if row is None:
        raise HTTPException(401, 'Unauthenticated')
    return dict(row)


def require_sqlite_resource_id(value, detail):
    # SQLite binds integers only within its signed 64-bit range.
    if not -(1 << 63) <= value <= (1 << 63) - 1:
        raise HTTPException(404, detail)


def team_access(db, user, team_id, manage=False):
    require_sqlite_resource_id(team_id, 'Team not found')
    row = db.execute('SELECT id,name,join_code FROM teams WHERE id=? AND organization_id=?',
                     (team_id, user['organization_id'])).fetchone()
    if row is None:
        raise HTTPException(404, 'Team not found')
    membership = db.execute(
        'SELECT role FROM memberships WHERE team_id=? AND user_id=? AND organization_id=?',
        (team_id, user['id'], user['organization_id']),
    ).fetchone()
    role = 'owner' if user['org_role'] == 'owner' else membership['role'] if membership else None
    if role is None:
        raise HTTPException(404, 'Team not found')
    if manage and role not in ('owner', 'manager'):
        raise HTTPException(403, 'Team manager required')
    return row, role


def owner_required(user):
    if user['org_role'] != 'owner':
        raise HTTPException(403, 'Owner required')


def team_json(row, role):
    return {'id': row['id'], 'name': row['name'], 'my_role': role,
            'join_code': row['join_code'] if role in ('owner', 'manager') else None}


def account_json(db, user, today, private=False):
    org = db.execute('SELECT id,name,plan,plan_status FROM organizations WHERE id=?',
                     (user['organization_id'],)).fetchone()
    public_user = {k: user[k] for k in ('id', 'display_name', 'email', 'org_role')}
    if private:
        public_user['personal_goal'] = user['personal_goal']
    return {'user': public_user, 'organization': dict(org), 'today': today.isoformat()}


def create_session(db, user_id, now):
    token = secrets.token_urlsafe(32)
    db.execute('INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)',
               (token_hash(token), user_id, iso(now + timedelta(days=7))))
    return token


def set_session(response, request, token):
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS,
                        expires=now_for(request.app) + timedelta(days=7),
                        httponly=True, samesite='lax', secure=request.url.scheme == 'https', path='/')


def checkin_json(row):
    return {k: row[k] for k in ('id', 'date', 'mood', 'activity', 'private_note', 'updated_at')}


def followup_json(row):
    return {k: row[k] for k in ('id', 'subject_user_id', 'created_by', 'action', 'status', 'created_at', 'updated_at')}


def trend(rows, today):
    current_start = (today - timedelta(days=6)).isoformat()
    previous_start = (today - timedelta(days=13)).isoformat()
    end = today.isoformat()
    current = [r['mood'] for r in rows if current_start <= r['date'] <= end]
    previous = [r['mood'] for r in rows if previous_start <= r['date'] < current_start]
    # Keep raw means for delta; rounding each mean first can change the result.
    cm = sum(current) / len(current) if current else None
    pm = sum(previous) / len(previous) if previous else None
    return {'current_mean': round(cm, 2) if cm is not None else None,
            'previous_mean': round(pm, 2) if pm is not None else None,
            'delta': round(cm - pm, 2) if cm is not None and pm is not None else None,
            'current_count': len(current), 'previous_count': len(previous)}


def parse_range(start, end, today):
    try:
        for value in (start, end):
            if value is not None and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                raise ValueError
        first = date.fromisoformat(start) if start is not None else today - timedelta(days=29)
        last = date.fromisoformat(end) if end is not None else today
        if not first <= last <= today or (last - first).days >= 366:
            raise ValueError
        return first.isoformat(), last.isoformat()
    except ValueError:
        raise HTTPException(422, 'Invalid date range: use YYYY-MM-DD, from <= to <= today, at most 366 days')


def create_app(data_dir=None):
    app = FastAPI(title='BurningUpp API')
    # Resolve independently for every factory call; never cache APP_DATA_DIR globally.
    directory = Path(data_dir) if data_dir is not None else Path(
        os.environ.get('APP_DATA_DIR') or Path(__file__).resolve().parent / 'data')
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    app.state.db_path = directory / 'burningupp.sqlite3'
    app.state.clock = utc_now
    # Eager, additive initialization also supports httpx ASGITransport without lifespan.
    with connect(app.state.db_path) as db:
        with db:
            db.executescript(SCHEMA)
    # A valid dummy hash avoids skipping password derivation for unknown accounts.
    app.state.dummy_password_hash = hash_password(secrets.token_urlsafe(32))

    @app.exception_handler(RequestValidationError)
    async def invalid_payload(request, exc):
        return JSONResponse(status_code=422, content={'detail': 'Invalid request payload or parameters'})

    @app.middleware('http')
    async def mutation_guard(request, call_next):
        if request.url.path.startswith('/api/') and request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            origin = request.headers.get('origin')
            expected = f'{request.url.scheme}://{request.url.netloc}'
            if origin is not None and origin != expected:
                return JSONResponse(status_code=403, content={'detail': 'Origin not allowed'})
            raw_length = request.headers.get('content-length')
            try:
                has_body = bool(await request.body()) if raw_length is None else int(raw_length) != 0
            except ValueError:
                return JSONResponse(status_code=422, content={'detail': 'Invalid Content-Length'})
            if has_body:
                media_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
                if media_type != 'application/json':
                    return JSONResponse(status_code=415, content={'detail': 'Content-Type must be application/json'})
        response = await call_next(request)
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.post('/api/auth/register-organization', status_code=201)
    def register_organization(payload: RegisterOrganization, request: Request, response: Response):
        now = now_for(app)
        password = hash_password(payload.password)
        try:
            with connect(app.state.db_path) as db:
                with db:
                    org_id = db.execute('INSERT INTO organizations(name,created_at) VALUES(?,?)',
                                        (payload.organization_name, iso(now))).lastrowid
                    user_id = db.execute(
                        'INSERT INTO users(organization_id,email,password_hash,display_name,org_role,created_at) '
                        "VALUES(?,?,?,?,'owner',?)",
                        (org_id, payload.email, password, payload.display_name, iso(now)),
                    ).lastrowid
                    token = create_session(db, user_id, now)
                    user = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
                    result = account_json(db, user, bangkok_date(now))
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Email already exists')
        set_session(response, request, token)
        return result

    @app.post('/api/auth/register-member', status_code=201)
    def register_member(payload: RegisterMember, request: Request, response: Response):
        now = now_for(app)
        password = hash_password(payload.password)
        try:
            with connect(app.state.db_path) as db:
                with db:
                    team = db.execute('SELECT id,organization_id FROM teams WHERE join_code=?',
                                      (payload.join_code,)).fetchone()
                    if team is None:
                        raise HTTPException(404, 'Invalid join code')
                    user_id = db.execute(
                        'INSERT INTO users(organization_id,email,password_hash,display_name,org_role,created_at) '
                        "VALUES(?,?,?,?,'member',?)",
                        (team['organization_id'], payload.email, password, payload.display_name, iso(now)),
                    ).lastrowid
                    db.execute('INSERT INTO memberships(organization_id,team_id,user_id,role,joined_on) '
                               "VALUES(?,?,?,'member',?)",
                               (team['organization_id'], team['id'], user_id, bangkok_date(now).isoformat()))
                    token = create_session(db, user_id, now)
                    user = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
                    result = account_json(db, user, bangkok_date(now))
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Email already exists')
        set_session(response, request, token)
        return result

    @app.post('/api/auth/login')
    def login(payload: Credentials, request: Request, response: Response):
        now = now_for(app)
        with connect(app.state.db_path) as db:
            user = db.execute('SELECT * FROM users WHERE email=?', (payload.email,)).fetchone()
            valid = verify_password(payload.password,
                                    user['password_hash'] if user else app.state.dummy_password_hash)
            if not valid or user is None:
                raise HTTPException(401, 'Invalid credentials')
            with db:
                token = create_session(db, user['id'], now)
            result = account_json(db, user, bangkok_date(now))
        set_session(response, request, token)
        return result

    @app.post('/api/auth/logout')
    def logout(request: Request, response: Response, user=Depends(require_user)):
        with connect(app.state.db_path) as db:
            with db:
                db.execute('DELETE FROM sessions WHERE token_hash=? AND user_id=?',
                           (token_hash(request.cookies[COOKIE]), user['id']))
        response.delete_cookie(COOKIE, path='/', secure=request.url.scheme == 'https',
                               httponly=True, samesite='lax')
        return {'ok': True}

    @app.get('/api/me')
    def me(user=Depends(require_user)):
        with connect(app.state.db_path) as db:
            return account_json(db, user, bangkok_date(now_for(app)), private=True)

    @app.patch('/api/me')
    def update_me(payload: Profile, user=Depends(require_user)):
        with connect(app.state.db_path) as db:
            with db:
                db.execute('UPDATE users SET display_name=?,personal_goal=? WHERE id=? AND organization_id=?',
                           (payload.display_name, payload.personal_goal, user['id'], user['organization_id']))
        return {'id': user['id'], 'display_name': payload.display_name, 'personal_goal': payload.personal_goal}

    @app.get('/api/teams')
    def list_teams(user=Depends(require_user)):
        with connect(app.state.db_path) as db:
            rows = db.execute(
                'SELECT t.id,t.name,t.join_code,m.role FROM teams t '
                'LEFT JOIN memberships m ON m.team_id=t.id AND m.organization_id=t.organization_id AND m.user_id=? '
                "WHERE t.organization_id=? AND (?='owner' OR m.user_id IS NOT NULL) ORDER BY t.id",
                (user['id'], user['organization_id'], user['org_role']),
            ).fetchall()
            return {'teams': [team_json(r, 'owner' if user['org_role'] == 'owner' else r['role']) for r in rows]}

    @app.post('/api/teams', status_code=201)
    def create_team(payload: TeamName, user=Depends(require_user)):
        owner_required(user)
        now = now_for(app)
        with connect(app.state.db_path) as db:
            with db:
                team_id = db.execute('INSERT INTO teams(organization_id,name,join_code,created_at) VALUES(?,?,?,?)',
                                     (user['organization_id'], payload.name, secrets.token_urlsafe(18), iso(now))).lastrowid
                db.execute('INSERT INTO memberships(organization_id,team_id,user_id,role,joined_on) '
                           "VALUES(?,?,?,'manager',?)",
                           (user['organization_id'], team_id, user['id'], bangkok_date(now).isoformat()))
                row = db.execute('SELECT id,name,join_code FROM teams WHERE id=? AND organization_id=?',
                                 (team_id, user['organization_id'])).fetchone()
        return team_json(row, 'owner')

    @app.post('/api/teams/join')
    def join_team(payload: JoinTeam, user=Depends(require_user)):
        with connect(app.state.db_path) as db:
            with db:
                row = db.execute('SELECT id,name,join_code FROM teams WHERE join_code=? AND organization_id=?',
                                 (payload.join_code, user['organization_id'])).fetchone()
                if row is None:
                    raise HTTPException(404, 'Invalid join code')
                db.execute('INSERT INTO memberships(organization_id,team_id,user_id,role,joined_on) '
                           "VALUES(?,?,?,'member',?) ON CONFLICT(team_id,user_id) DO NOTHING",
                           (user['organization_id'], row['id'], user['id'], bangkok_date(now_for(app)).isoformat()))
                row, role = team_access(db, user, row['id'])
        return team_json(row, role)

    @app.get('/api/teams/{team_id}/members')
    def members(team_id: int, user=Depends(require_user)):
        with connect(app.state.db_path) as db:
            team_access(db, user, team_id, manage=True)
            rows = db.execute('SELECT m.user_id,u.display_name,m.role,m.joined_on FROM memberships m '
                              'JOIN users u ON u.id=m.user_id AND u.organization_id=m.organization_id '
                              'WHERE m.team_id=? AND m.organization_id=? ORDER BY m.user_id',
                              (team_id, user['organization_id'])).fetchall()
        return {'members': [dict(r) for r in rows]}

    @app.patch('/api/teams/{team_id}/members/{user_id}')
    def update_member(team_id: int, user_id: int, payload: MemberRole, user=Depends(require_user)):
        with connect(app.state.db_path) as db:
            team_access(db, user, team_id)
            require_sqlite_resource_id(user_id, 'Membership not found')
            target = db.execute('SELECT user_id FROM memberships WHERE team_id=? AND user_id=? AND organization_id=?',
                                (team_id, user_id, user['organization_id'])).fetchone()
            if target is None:
                raise HTTPException(404, 'Membership not found')
            owner_required(user)
            with db:
                db.execute('UPDATE memberships SET role=? WHERE team_id=? AND user_id=? AND organization_id=?',
                           (payload.role, team_id, user_id, user['organization_id']))
        return {'user_id': user_id, 'role': payload.role}

    @app.put('/api/checkins/today')
    def save_checkin(payload: Checkin, user=Depends(require_user)):
        now = now_for(app)
        today = bangkok_date(now).isoformat()
        with connect(app.state.db_path) as db:
            with db:
                db.execute('INSERT INTO checkins(organization_id,user_id,date,mood,activity,private_note,updated_at) '
                           'VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,date) DO UPDATE SET '
                           'mood=excluded.mood,activity=excluded.activity,private_note=excluded.private_note,updated_at=excluded.updated_at',
                           (user['organization_id'], user['id'], today, payload.mood,
                            payload.activity, payload.private_note, iso(now)))
                row = db.execute('SELECT id,date,mood,activity,private_note,updated_at FROM checkins '
                                 'WHERE user_id=? AND organization_id=? AND date=?',
                                 (user['id'], user['organization_id'], today)).fetchone()
        return checkin_json(row)

    @app.get('/api/checkins')
    def history(from_: str | None = Query(None, alias='from'), to: str | None = Query(None),
                user=Depends(require_user)):
        today = bangkok_date(now_for(app))
        first, last = parse_range(from_, to, today)
        with connect(app.state.db_path) as db:
            rows = db.execute('SELECT id,date,mood,activity,private_note,updated_at FROM checkins '
                              'WHERE user_id=? AND organization_id=? AND date BETWEEN ? AND ? ORDER BY date',
                              (user['id'], user['organization_id'], first, last)).fetchall()
            recent = db.execute('SELECT date,mood FROM checkins WHERE user_id=? AND organization_id=? '
                                'AND date BETWEEN ? AND ?',
                                (user['id'], user['organization_id'], (today - timedelta(days=13)).isoformat(),
                                 today.isoformat())).fetchall()
        return {'from': first, 'to': last, 'entries': [checkin_json(r) for r in rows],
                'insight': trend(recent, today)}

    @app.get('/api/teams/{team_id}/dashboard')
    def dashboard(team_id: int, user=Depends(require_user)):
        today = bangkok_date(now_for(app))
        today_text = today.isoformat()
        yesterday = (today - timedelta(days=1)).isoformat()
        missing_start = (today - timedelta(days=2)).isoformat()
        with connect(app.state.db_path) as db:
            team, role = team_access(db, user, team_id, manage=True)
            roster = db.execute(
                'SELECT m.user_id,u.display_name,m.joined_on FROM memberships m '
                'JOIN users u ON u.id=m.user_id AND u.organization_id=m.organization_id '
                'WHERE m.team_id=? AND m.organization_id=? ORDER BY m.user_id',
                (team_id, user['organization_id']),
            ).fetchall()
            # Only identity, date and mood are needed; private journal/profile fields are never read.
            recent = db.execute(
                'SELECT c.user_id,c.date,c.mood FROM checkins c JOIN memberships m '
                'ON m.user_id=c.user_id AND m.organization_id=c.organization_id '
                'WHERE m.team_id=? AND m.organization_id=? AND c.date>=m.joined_on '
                'AND c.date BETWEEN ? AND ?',
                (team_id, user['organization_id'], (today - timedelta(days=13)).isoformat(),
                 today_text),
            ).fetchall()
            # Latest eligible entry is scoped from joined_on through today, not to the trend window.
            latest = db.execute(
                'SELECT c.user_id,c.date,c.mood FROM checkins c JOIN memberships m '
                'ON m.user_id=c.user_id AND m.organization_id=c.organization_id '
                'WHERE m.team_id=? AND m.organization_id=? AND c.date>=m.joined_on '
                'AND c.date<=? AND NOT EXISTS ('
                'SELECT 1 FROM checkins newer WHERE newer.user_id=c.user_id '
                'AND newer.organization_id=c.organization_id '
                'AND newer.date>c.date AND newer.date<=?) ORDER BY c.user_id',
                (team_id, user['organization_id'], today_text, today_text),
            ).fetchall()
        days = []
        for offset in range(6, -1, -1):
            day = (today - timedelta(days=offset)).isoformat()
            eligible = sum(1 for member in roster if member['joined_on'] <= day)
            moods = [r['mood'] for r in recent if r['date'] == day]
            days.append({'date': day, 'eligible_members': eligible, 'checkin_count': len(moods),
                         'participation_rate': round(100.0 * len(moods) / eligible, 1) if eligible else None,
                         'mean_mood': round(sum(moods) / len(moods), 2) if moods else None})
        latest_by_user = {entry['user_id']: entry for entry in latest}
        candidates = []
        for member in roster:
            entry = latest_by_user.get(member['user_id'])
            reasons = []
            if entry is not None and yesterday <= entry['date'] <= today_text and entry['mood'] <= 1:
                reasons.append('low_mood')
            if member['joined_on'] <= missing_start and (entry is None or entry['date'] < missing_start):
                reasons.append('missing_3_days')
            if reasons:
                candidates.append({'user_id': member['user_id'], 'display_name': member['display_name'],
                                   'reasons': reasons})
        return {'team': {'id': team['id'], 'name': team['name']}, 'today': today_text,
                'member_count': len(roster), 'days': days, 'trend': trend(recent, today),
                'followup_candidates': candidates, 'disclaimer': DISCLAIMER}

    @app.get('/api/teams/{team_id}/followups')
    def list_followups(team_id: int, user=Depends(require_user)):
        with connect(app.state.db_path) as db:
            team_access(db, user, team_id, manage=True)
            rows = db.execute('SELECT id,subject_user_id,created_by,action,status,created_at,updated_at FROM followups '
                              'WHERE team_id=? AND organization_id=? ORDER BY created_at DESC,id DESC',
                              (team_id, user['organization_id'])).fetchall()
        return {'followups': [followup_json(r) for r in rows]}

    @app.post('/api/teams/{team_id}/followups', status_code=201)
    def create_followup(team_id: int, payload: NewFollowup, user=Depends(require_user)):
        now = iso(now_for(app))
        with connect(app.state.db_path) as db:
            with db:
                team_access(db, user, team_id, manage=True)
                require_sqlite_resource_id(payload.subject_user_id, 'Subject not found')
                subject = db.execute('SELECT user_id FROM memberships WHERE team_id=? AND user_id=? AND organization_id=?',
                                     (team_id, payload.subject_user_id, user['organization_id'])).fetchone()
                if subject is None:
                    raise HTTPException(404, 'Subject not found')
                task_id = db.execute('INSERT INTO followups(organization_id,team_id,subject_user_id,created_by,action,status,created_at,updated_at) '
                                     "VALUES(?,?,?,?,?,'open',?,?)",
                                     (user['organization_id'], team_id, payload.subject_user_id, user['id'],
                                      payload.action, now, now)).lastrowid
                row = db.execute('SELECT * FROM followups WHERE id=? AND team_id=? AND organization_id=?',
                                 (task_id, team_id, user['organization_id'])).fetchone()
        return followup_json(row)

    @app.patch('/api/teams/{team_id}/followups/{followup_id}')
    def update_followup(team_id: int, followup_id: int, payload: EditFollowup, user=Depends(require_user)):
        with connect(app.state.db_path) as db:
            with db:
                team_access(db, user, team_id, manage=True)
                require_sqlite_resource_id(followup_id, 'Followup not found')
                row = db.execute('SELECT id FROM followups WHERE id=? AND team_id=? AND organization_id=?',
                                 (followup_id, team_id, user['organization_id'])).fetchone()
                if row is None:
                    raise HTTPException(404, 'Followup not found')
                db.execute('UPDATE followups SET action=?,status=?,updated_at=? WHERE id=? AND team_id=? AND organization_id=?',
                           (payload.action, payload.status, iso(now_for(app)), followup_id, team_id, user['organization_id']))
                row = db.execute('SELECT * FROM followups WHERE id=? AND team_id=? AND organization_id=?',
                                 (followup_id, team_id, user['organization_id'])).fetchone()
        return followup_json(row)

    @app.get('/api/assessment')
    def assessment(user=Depends(require_user)):
        return {'status': 'pending_rules', 'message': ASSESSMENT_MESSAGE}

    # Exact static routes only; unknown /api paths remain API 404 responses.
    frontend = Path(__file__).resolve().parent.parent / 'frontend'

    @app.get('/', include_in_schema=False)
    def index():
        path = frontend / 'index.html'
        if not path.is_file():
            raise HTTPException(404, 'Frontend file not found')
        return FileResponse(path, media_type='text/html')

    @app.get('/styles.css', include_in_schema=False)
    def stylesheet():
        path = frontend / 'styles.css'
        if not path.is_file():
            raise HTTPException(404, 'Frontend file not found')
        return FileResponse(path, media_type='text/css')

    @app.get('/app.js', include_in_schema=False)
    def javascript():
        path = frontend / 'app.js'
        if not path.is_file():
            raise HTTPException(404, 'Frontend file not found')
        return FileResponse(path, media_type='text/javascript')

    return app


app = create_app()
