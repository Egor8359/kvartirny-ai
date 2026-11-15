"""Run only against the disposable PostgreSQL service in GitHub Actions."""
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from psycopg import sql

url = os.environ['TEST_POSTGRES_URL']
parsed = urlsplit(url)
if parsed.hostname != '127.0.0.1' or parsed.path != '/apartment_test' or os.environ.get('GITHUB_ACTIONS') != 'true':
    raise RuntimeError('This test only runs against the isolated GitHub Actions PostgreSQL service')
name = 'production_sql_' + uuid.uuid4().hex
directory = Path(__file__).resolve().parents[1] / 'docs' / 'supabase-production-sql'
schema, catalog, verify = [(directory / n).read_text(encoding='utf-8') for n in
    ('01_schema_production.sql', '02_catalog_production.sql', '03_verify_production.sql')]

with psycopg.connect(url, dbname='postgres', autocommit=True) as admin:
    for role in ('anon', 'authenticated'):
        if not admin.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
            admin.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(role)))
    admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        with psycopg.connect(url, dbname=name, autocommit=True) as db:
            notices = []
            db.add_notice_handler(lambda diag: notices.append(diag.message_primary))
            def check(expected, scenario):
                notices.clear()
                db.execute(verify)
                results = [v for v in notices if v.startswith(('PASS:', 'FAIL:'))]
                if len(results) != 1 or not results[0].startswith(expected + ':'):
                    raise AssertionError(f'{scenario}: expected {expected}, got {results}')
                print(f'{scenario}: {expected}')
            db.execute(schema)
            db.execute(catalog)
            check('PASS', 'initial schema and catalog')
            before = db.execute('SELECT * FROM public.apartments ORDER BY id').fetchall()
            db.execute(schema)
            db.execute(catalog)
            after = db.execute('SELECT * FROM public.apartments ORDER BY id').fetchall()
            assert len(before) == 12 and before == after
            check('PASS', 'repeated initialization preserves catalog')
            for label, mutation in [
                ('missing table', 'DROP TABLE public.rate_windows'),
                ('wrong marker', "UPDATE public.environment_identity SET name='preview' WHERE id=1"),
                ('extra apartment', "INSERT INTO public.apartments SELECT 'extra',building,rooms,area,floor,total_floors,price,finishing,delivery_year,status FROM public.apartments LIMIT 1"),
                ('anon access', 'GRANT SELECT ON public.users TO anon'),
            ]:
                db.execute('BEGIN')
                try:
                    db.execute(mutation)
                    check('FAIL', label)
                finally:
                    db.execute('ROLLBACK')
                check('PASS', label + ' rollback')
    finally:
        admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
