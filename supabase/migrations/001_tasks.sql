create table if not exists public.tasks (
  id text not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null,
  notes text not null default '',
  status text not null default 'open' check (status in ('open', 'completed')),
  due_at text,
  reminder text,
  recurrence text not null default 'none' check (recurrence in ('none', 'daily', 'weekly')),
  tags jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  primary key (user_id, id)
);

alter table public.tasks add column if not exists deleted_at timestamptz;

create index if not exists tasks_user_updated_at_idx on public.tasks (user_id, updated_at);

alter table public.tasks enable row level security;

create policy "Users can read their tasks"
  on public.tasks for select
  using (auth.uid() = user_id);

create policy "Users can create their tasks"
  on public.tasks for insert
  with check (auth.uid() = user_id);

create policy "Users can update their tasks"
  on public.tasks for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "Users can delete their tasks"
  on public.tasks for delete
  using (auth.uid() = user_id);
