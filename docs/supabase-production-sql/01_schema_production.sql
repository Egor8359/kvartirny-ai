-- SQLAlchemy metadata; для проекта Production. Выполнять целиком.
BEGIN;
SET LOCAL search_path TO public, pg_catalog;
DO $$
DECLARE unknown_objects text; present_count integer; marker text;
BEGIN
 SELECT string_agg(c.relname, ', ') INTO unknown_objects
 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')
   AND c.relname NOT IN ('apartments', 'environment_identity', 'rate_windows', 'users', 'auth_sessions', 'conversations', 'user_leases', 'messages', 'user_facts');
 IF unknown_objects IS NOT NULL THEN RAISE EXCEPTION 'Неожиданные объекты в public: %', unknown_objects; END IF;
 SELECT count(*) INTO present_count FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f') AND c.relname IN ('apartments', 'environment_identity', 'rate_windows', 'users', 'auth_sessions', 'conversations', 'user_leases', 'messages', 'user_facts');
 IF present_count > 0 THEN
   IF to_regclass('public.environment_identity') IS NULL THEN RAISE EXCEPTION 'Есть таблицы без маркера окружения'; END IF;
   SELECT name INTO marker FROM public.environment_identity WHERE id=1;
   IF marker IS DISTINCT FROM 'production' THEN RAISE EXCEPTION 'Маркер отсутствует или не равен production'; END IF;
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS apartments (
	id VARCHAR NOT NULL,
	building VARCHAR NOT NULL,
	rooms INTEGER NOT NULL,
	area DOUBLE PRECISION NOT NULL,
	floor INTEGER NOT NULL,
	total_floors INTEGER NOT NULL,
	price INTEGER NOT NULL,
	finishing BOOLEAN NOT NULL,
	delivery_year INTEGER NOT NULL,
	status VARCHAR NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS environment_identity (
	id SERIAL NOT NULL,
	name VARCHAR NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS rate_windows (
	key VARCHAR NOT NULL,
	window_start INTEGER NOT NULL,
	count INTEGER NOT NULL,
	PRIMARY KEY (key)
);

CREATE TABLE IF NOT EXISTS users (
	id SERIAL NOT NULL,
	username VARCHAR NOT NULL,
	display_name VARCHAR NOT NULL,
	password_hash VARCHAR NOT NULL,
	role VARCHAR NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (username)
);

CREATE TABLE IF NOT EXISTS auth_sessions (
	id SERIAL NOT NULL,
	user_id INTEGER NOT NULL,
	token_hash VARCHAR NOT NULL,
	expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	UNIQUE (token_hash)
);

CREATE TABLE IF NOT EXISTS conversations (
	id SERIAL NOT NULL,
	user_id INTEGER NOT NULL,
	title VARCHAR NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_leases (
	user_id INTEGER NOT NULL,
	token VARCHAR NOT NULL,
	expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (user_id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
	id SERIAL NOT NULL,
	conversation_id INTEGER NOT NULL,
	role VARCHAR NOT NULL,
	content VARCHAR NOT NULL,
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_facts (
	id SERIAL NOT NULL,
	user_id INTEGER NOT NULL,
	fact_key VARCHAR NOT NULL,
	fact_value VARCHAR NOT NULL,
	source VARCHAR NOT NULL,
	source_message_id INTEGER,
	created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (user_id, fact_key),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
	FOREIGN KEY(source_message_id) REFERENCES messages (id) ON DELETE SET NULL
);

ALTER TABLE public."apartments" ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE public."apartments" FROM PUBLIC, anon, authenticated;
ALTER TABLE public."environment_identity" ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE public."environment_identity" FROM PUBLIC, anon, authenticated;
ALTER TABLE public."rate_windows" ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE public."rate_windows" FROM PUBLIC, anon, authenticated;
ALTER TABLE public."users" ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE public."users" FROM PUBLIC, anon, authenticated;
ALTER TABLE public."auth_sessions" ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE public."auth_sessions" FROM PUBLIC, anon, authenticated;
ALTER TABLE public."conversations" ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE public."conversations" FROM PUBLIC, anon, authenticated;
ALTER TABLE public."user_leases" ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE public."user_leases" FROM PUBLIC, anon, authenticated;
ALTER TABLE public."messages" ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE public."messages" FROM PUBLIC, anon, authenticated;
ALTER TABLE public."user_facts" ENABLE ROW LEVEL SECURITY;
REVOKE ALL PRIVILEGES ON TABLE public."user_facts" FROM PUBLIC, anon, authenticated;
DO $$
DECLARE r record;
BEGIN
 FOR r IN SELECT DISTINCT s.relname FROM pg_class s
 JOIN pg_namespace sn ON sn.oid=s.relnamespace
 JOIN pg_depend d ON d.objid=s.oid AND d.deptype IN ('a','i')
 JOIN pg_class t ON t.oid=d.refobjid JOIN pg_namespace tn ON tn.oid=t.relnamespace
 WHERE s.relkind='S' AND sn.nspname='public' AND tn.nspname='public' AND t.relname IN ('apartments', 'environment_identity', 'rate_windows', 'users', 'auth_sessions', 'conversations', 'user_leases', 'messages', 'user_facts')
 LOOP EXECUTE format('REVOKE ALL PRIVILEGES ON SEQUENCE public.%I FROM PUBLIC, anon, authenticated', r.relname); END LOOP;
END $$;
INSERT INTO public.environment_identity (id, name) VALUES (1, 'production') ON CONFLICT (id) DO NOTHING;
COMMIT;
