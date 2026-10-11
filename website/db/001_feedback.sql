create table if not exists feedback_messages (
  id bigint generated always as identity primary key,
  category text not null check (category in ('suggestion', 'feature', 'bug')),
  message text not null check (char_length(message) between 10 and 2000),
  reply_email text,
  ip_hash text not null,
  user_agent text,
  created_at timestamptz not null default now(),
  delivered_at timestamptz
);

create index if not exists feedback_messages_rate_limit_idx
  on feedback_messages (ip_hash, created_at desc);
