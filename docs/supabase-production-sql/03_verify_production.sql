-- Только чтение. Каждая строка с problem <> NULL требует внимания.
WITH expected(table_name,column_name,data_type,not_null) AS (VALUES
('apartments', 'id', 'character varying', true),
('apartments', 'building', 'character varying', true),
('apartments', 'rooms', 'integer', true),
('apartments', 'area', 'double precision', true),
('apartments', 'floor', 'integer', true),
('apartments', 'total_floors', 'integer', true),
('apartments', 'price', 'integer', true),
('apartments', 'finishing', 'boolean', true),
('apartments', 'delivery_year', 'integer', true),
('apartments', 'status', 'character varying', true),
('environment_identity', 'id', 'integer', true),
('environment_identity', 'name', 'character varying', true),
('rate_windows', 'key', 'character varying', true),
('rate_windows', 'window_start', 'integer', true),
('rate_windows', 'count', 'integer', true),
('users', 'id', 'integer', true),
('users', 'username', 'character varying', true),
('users', 'display_name', 'character varying', true),
('users', 'password_hash', 'character varying', true),
('users', 'role', 'character varying', true),
('users', 'created_at', 'timestamp without time zone', true),
('auth_sessions', 'id', 'integer', true),
('auth_sessions', 'user_id', 'integer', true),
('auth_sessions', 'token_hash', 'character varying', true),
('auth_sessions', 'expires_at', 'timestamp without time zone', true),
('auth_sessions', 'created_at', 'timestamp without time zone', true),
('conversations', 'id', 'integer', true),
('conversations', 'user_id', 'integer', true),
('conversations', 'title', 'character varying', true),
('conversations', 'created_at', 'timestamp without time zone', true),
('conversations', 'updated_at', 'timestamp without time zone', true),
('user_leases', 'user_id', 'integer', true),
('user_leases', 'token', 'character varying', true),
('user_leases', 'expires_at', 'timestamp without time zone', true),
('messages', 'id', 'integer', true),
('messages', 'conversation_id', 'integer', true),
('messages', 'role', 'character varying', true),
('messages', 'content', 'character varying', true),
('messages', 'created_at', 'timestamp without time zone', true),
('user_facts', 'id', 'integer', true),
('user_facts', 'user_id', 'integer', true),
('user_facts', 'fact_key', 'character varying', true),
('user_facts', 'fact_value', 'character varying', true),
('user_facts', 'source', 'character varying', true),
('user_facts', 'source_message_id', 'integer', false),
('user_facts', 'created_at', 'timestamp without time zone', true),
('user_facts', 'updated_at', 'timestamp without time zone', true)
), actual AS (
 SELECT c.relname AS table_name,a.attname AS column_name,format_type(a.atttypid,a.atttypmod) AS data_type,a.attnotnull AS not_null
 FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public' AND c.relname IN ('apartments', 'environment_identity', 'rate_windows', 'users', 'auth_sessions', 'conversations', 'user_leases', 'messages', 'user_facts') AND c.relkind IN ('r','p') AND a.attnum>0 AND NOT a.attisdropped
)
SELECT COALESCE(e.table_name,a.table_name) AS table_name, COALESCE(e.column_name,a.column_name) AS column_name,
 e.data_type AS expected_type,a.data_type AS actual_type,e.not_null AS expected_not_null,a.not_null AS actual_not_null,
 CASE WHEN e.column_name IS NULL THEN 'extra column' WHEN a.column_name IS NULL THEN 'missing column'
 WHEN e.data_type<>a.data_type OR e.not_null<>a.not_null THEN 'type or nullability mismatch' END AS problem
FROM expected e FULL JOIN actual a USING (table_name,column_name) ORDER BY 1,2;

WITH expected(table_name,kind,columns,target,delete_action) AS (VALUES
('apartments', 'p', 'id', '', ''),
('environment_identity', 'p', 'id', '', ''),
('rate_windows', 'p', 'key', '', ''),
('users', 'p', 'id', '', ''),
('users', 'u', 'username', '', ''),
('auth_sessions', 'f', 'user_id', 'users(id)', 'c'),
('auth_sessions', 'p', 'id', '', ''),
('auth_sessions', 'u', 'token_hash', '', ''),
('conversations', 'f', 'user_id', 'users(id)', 'c'),
('conversations', 'p', 'id', '', ''),
('user_leases', 'p', 'user_id', '', ''),
('user_leases', 'f', 'user_id', 'users(id)', 'c'),
('messages', 'f', 'conversation_id', 'conversations(id)', 'c'),
('messages', 'p', 'id', '', ''),
('user_facts', 'f', 'user_id', 'users(id)', 'c'),
('user_facts', 'u', 'user_id,fact_key', '', ''),
('user_facts', 'f', 'source_message_id', 'messages(id)', 'n'),
('user_facts', 'p', 'id', '', '')
), actual AS (
 SELECT c.relname AS table_name, con.contype::text AS kind,
 (SELECT string_agg(a.attname, ',' ORDER BY k.ord) FROM unnest(con.conkey) WITH ORDINALITY k(attnum,ord) JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=k.attnum) AS columns,
 CASE WHEN con.contype='f' THEN ref.relname || '(' ||
 (SELECT string_agg(a.attname, ',' ORDER BY k.ord) FROM unnest(con.confkey) WITH ORDINALITY k(attnum,ord) JOIN pg_attribute a ON a.attrelid=ref.oid AND a.attnum=k.attnum) || ')' ELSE '' END AS target,
 CASE WHEN con.contype='f' THEN con.confdeltype::text ELSE '' END AS delete_action,
 CASE WHEN con.contype IN ('p','u') THEN COALESCE(i.indisvalid AND i.indisready,false) ELSE true END AS index_ok
 FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
 LEFT JOIN pg_class ref ON ref.oid=con.confrelid LEFT JOIN pg_index i ON i.indexrelid=con.conindid
 WHERE n.nspname='public' AND c.relname IN ('apartments', 'environment_identity', 'rate_windows', 'users', 'auth_sessions', 'conversations', 'user_leases', 'messages', 'user_facts')
)
SELECT COALESCE(e.table_name,a.table_name) AS table_name, COALESCE(e.kind,a.kind) AS kind,
 COALESCE(e.columns,a.columns) AS columns, COALESCE(e.target,a.target) AS target,
 COALESCE(e.delete_action,a.delete_action) AS delete_action,
 CASE WHEN e.table_name IS NULL THEN 'unexpected constraint' WHEN a.table_name IS NULL THEN 'missing or mismatched constraint'
 WHEN NOT a.index_ok THEN 'invalid backing index' END AS problem
FROM expected e FULL JOIN actual a USING (table_name,kind,columns,target,delete_action) ORDER BY 1,2,3;
SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' AND tablename IN ('apartments', 'environment_identity', 'rate_windows', 'users', 'auth_sessions', 'conversations', 'user_leases', 'messages', 'user_facts') ORDER BY 1,2;
SELECT c.relname, c.relrowsecurity AS rls_enabled,
 has_table_privilege('anon', c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') AS anon_any,
 has_table_privilege('authenticated', c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') AS authenticated_any
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind IN ('r','p') AND c.relname IN ('apartments', 'environment_identity', 'rate_windows', 'users', 'auth_sessions', 'conversations', 'user_leases', 'messages', 'user_facts') ORDER BY 1;
SELECT c.relname, a.attname,
 has_column_privilege('anon', c.oid, a.attnum, 'SELECT,INSERT,UPDATE,REFERENCES') AS anon_any,
 has_column_privilege('authenticated', c.oid, a.attnum, 'SELECT,INSERT,UPDATE,REFERENCES') AS authenticated_any
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid
WHERE n.nspname='public' AND c.relkind IN ('r','p') AND c.relname IN ('apartments', 'environment_identity', 'rate_windows', 'users', 'auth_sessions', 'conversations', 'user_leases', 'messages', 'user_facts') AND a.attnum>0 AND NOT a.attisdropped ORDER BY 1,2;
SELECT schemaname,tablename,policyname,roles,cmd FROM pg_policies WHERE schemaname='public' AND tablename IN ('apartments', 'environment_identity', 'rate_windows', 'users', 'auth_sessions', 'conversations', 'user_leases', 'messages', 'user_facts');
SELECT s.relname AS sequence_name,
 has_sequence_privilege('anon', s.oid, 'USAGE,SELECT,UPDATE') AS anon_any,
 has_sequence_privilege('authenticated', s.oid, 'USAGE,SELECT,UPDATE') AS authenticated_any
FROM pg_class s JOIN pg_depend d ON d.objid=s.oid AND d.deptype IN ('a','i')
JOIN pg_class t ON t.oid=d.refobjid JOIN pg_namespace n ON n.oid=t.relnamespace
WHERE s.relkind='S' AND n.nspname='public' AND t.relname IN ('apartments', 'environment_identity', 'rate_windows', 'users', 'auth_sessions', 'conversations', 'user_leases', 'messages', 'user_facts') ORDER BY 1;
SELECT id,name FROM public.environment_identity WHERE id=1;
SELECT count(*) AS apartment_count, count(DISTINCT id) AS distinct_apartments FROM public.apartments;

-- Должны отсутствовать любые строки расхождений; дополнительно apartment_count должен быть 12.
WITH expected(id,building,rooms,area,floor,total_floors,price,finishing,delivery_year,status) AS (VALUES
('A-101', 'Корпус A', 1, 38.2, 1, 12, 5500000, TRUE, 2027, 'available'),
('A-406', 'Корпус A', 1, 39.5, 4, 12, 5900000, FALSE, 2027, 'available'),
('A-905', 'Корпус A', 1, 41.0, 9, 12, 6400000, FALSE, 2027, 'available'),
('B-203', 'Корпус B', 2, 58.0, 2, 16, 8100000, TRUE, 2027, 'available'),
('B-705', 'Корпус B', 2, 61.0, 7, 16, 8700000, TRUE, 2027, 'available'),
('B-1201', 'Корпус B', 2, 60.0, 12, 16, 8800000, FALSE, 2027, 'available'),
('C-804', 'Корпус C', 2, 64.0, 8, 16, 9400000, TRUE, 2028, 'available'),
('C-1104', 'Корпус C', 3, 74.0, 11, 16, 10200000, TRUE, 2028, 'available'),
('C-301', 'Корпус C', 3, 78.0, 3, 16, 10800000, FALSE, 2028, 'available'),
('C-1403', 'Корпус C', 3, 82.0, 14, 16, 11700000, TRUE, 2028, 'available'),
('A-1203', 'Корпус A', 0, 27.0, 12, 12, 4300000, TRUE, 2027, 'available'),
('B-102', 'Корпус B', 2, 56.0, 1, 16, 7800000, TRUE, 2027, 'available'))
SELECT COALESCE(e.id,a.id) AS id FROM expected e FULL JOIN public.apartments a ON a.id=e.id WHERE e.id IS NULL OR a.id IS NULL OR ROW(e.building,e.rooms,e.area,e.floor,e.total_floors,e.price,e.finishing,e.delivery_year,e.status) IS DISTINCT FROM ROW(a.building,a.rooms,a.area,a.floor,a.total_floors,a.price,a.finishing,a.delivery_year,a.status);
SELECT (SELECT count(*) FROM public.users) AS users, (SELECT count(*) FROM public.conversations) AS conversations, (SELECT count(*) FROM public.messages) AS messages, (SELECT count(*) FROM public.user_facts) AS facts, (SELECT count(*) FROM public.auth_sessions) AS sessions;
