create table if not exists cms_admin_users (
  id bigserial primary key,
  email text not null unique,
  password_hash text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists cms_admin_sessions (
  token_hash text primary key,
  user_id bigint not null references cms_admin_users(id) on delete cascade,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);

create index if not exists cms_admin_sessions_expiry_idx on cms_admin_sessions (expires_at);

create table if not exists cms_setup_tokens (
  token_hash text primary key,
  email text not null,
  expires_at timestamptz not null,
  used_at timestamptz
);

create table if not exists cms_login_attempts (
  ip_hash text not null,
  attempted_at timestamptz not null default now()
);

create index if not exists cms_login_attempts_ip_time_idx
  on cms_login_attempts (ip_hash, attempted_at desc);

create table if not exists cms_content (
  content_key text primary key,
  content_value text not null,
  updated_by bigint references cms_admin_users(id) on delete set null,
  updated_at timestamptz not null default now()
);

alter table feedback_messages add column if not exists status text not null default 'new';
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'feedback_messages_status_check') then
    alter table feedback_messages add constraint feedback_messages_status_check check (status in ('new', 'read', 'resolved'));
  end if;
end $$;
