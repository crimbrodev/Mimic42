create type public.agent_runtime_status as enum (
    'draft',
    'stopped',
    'starting',
    'running',
    'stopping',
    'error'
);

create type public.telegram_authorization_status as enum (
    'not_started',
    'code_requested',
    'password_required',
    'authorized',
    'revoked',
    'error'
);

create type public.agent_message_direction as enum (
    'incoming',
    'outgoing',
    'dashboard_trigger',
    'agent_response',
    'tool_call',
    'tool_result'
);

create type public.agent_event_status as enum (
    'pending',
    'running',
    'succeeded',
    'failed',
    'cancelled'
);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create table public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    email text,
    display_name text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table public.agents (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references public.profiles(id) on delete cascade,
    name text not null,
    status public.agent_runtime_status not null default 'draft',
    system_prompt text not null,
    soul_prompt text not null default '',
    settings jsonb not null default '{}'::jsonb,
    last_started_at timestamptz,
    last_stopped_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint agents_name_not_blank check (btrim(name) <> ''),
    constraint agents_system_prompt_not_blank check (btrim(system_prompt) <> '')
);

create table public.agent_onboarding_sessions (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null unique references public.profiles(id) on delete cascade,
    api_id integer,
    api_hash_ciphertext text,
    phone_number text,
    phone_code_hash_ciphertext text,
    session_ciphertext text,
    authorization_status public.telegram_authorization_status not null default 'not_started',
    agent_name text,
    system_prompt text,
    soul_prompt text,
    completed_agent_id uuid unique references public.agents(id) on delete set null,
    last_error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint agent_onboarding_sessions_phone_not_blank check (phone_number is null or btrim(phone_number) <> '')
);

create table public.telegram_sessions (
    id uuid primary key default gen_random_uuid(),
    agent_id uuid not null unique references public.agents(id) on delete cascade,
    session_name text not null,
    phone_number text,
    api_id integer,
    api_hash_ciphertext text,
    session_ciphertext text,
    authorization_status public.telegram_authorization_status not null default 'not_started',
    last_authorized_at timestamptz,
    last_error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint telegram_sessions_session_name_not_blank check (btrim(session_name) <> '')
);

create table public.message_threads (
    id uuid primary key default gen_random_uuid(),
    agent_id uuid not null references public.agents(id) on delete cascade,
    telegram_peer_id text not null,
    title text,
    last_message_at timestamptz,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (agent_id, telegram_peer_id)
);

create table public.agent_messages (
    id uuid primary key default gen_random_uuid(),
    agent_id uuid not null references public.agents(id) on delete cascade,
    thread_id uuid references public.message_threads(id) on delete set null,
    direction public.agent_message_direction not null,
    role text not null,
    telegram_message_id text,
    content text not null,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint agent_messages_role_not_blank check (btrim(role) <> ''),
    constraint agent_messages_content_not_blank check (btrim(content) <> '')
);

create table public.agent_events (
    id uuid primary key default gen_random_uuid(),
    agent_id uuid not null references public.agents(id) on delete cascade,
    actor_user_id uuid references public.profiles(id) on delete set null,
    event_type text not null,
    status public.agent_event_status not null default 'pending',
    payload jsonb not null default '{}'::jsonb,
    result jsonb,
    error text,
    created_at timestamptz not null default now(),
    started_at timestamptz,
    completed_at timestamptz,
    constraint agent_events_event_type_not_blank check (btrim(event_type) <> '')
);

create index agents_owner_id_idx on public.agents(owner_id);
create index agents_status_idx on public.agents(status);
create index agent_onboarding_sessions_owner_id_idx on public.agent_onboarding_sessions(owner_id);
create index agent_onboarding_sessions_status_idx on public.agent_onboarding_sessions(
    authorization_status
);
create index message_threads_agent_id_idx on public.message_threads(agent_id);
create index agent_messages_agent_id_created_at_idx on public.agent_messages(agent_id, created_at desc);
create index agent_messages_thread_id_created_at_idx on public.agent_messages(thread_id, created_at desc);
create index agent_events_agent_id_status_created_at_idx on public.agent_events(
    agent_id,
    status,
    created_at desc
);
create index agent_events_actor_user_id_idx on public.agent_events(actor_user_id);

create trigger profiles_set_updated_at
before update on public.profiles
for each row execute function public.set_updated_at();

create trigger agents_set_updated_at
before update on public.agents
for each row execute function public.set_updated_at();

create trigger agent_onboarding_sessions_set_updated_at
before update on public.agent_onboarding_sessions
for each row execute function public.set_updated_at();

create trigger telegram_sessions_set_updated_at
before update on public.telegram_sessions
for each row execute function public.set_updated_at();

create trigger message_threads_set_updated_at
before update on public.message_threads
for each row execute function public.set_updated_at();

alter table public.profiles enable row level security;
alter table public.agents enable row level security;
alter table public.agent_onboarding_sessions enable row level security;
alter table public.telegram_sessions enable row level security;
alter table public.message_threads enable row level security;
alter table public.agent_messages enable row level security;
alter table public.agent_events enable row level security;

create policy "Users can read their own profile"
on public.profiles
for select
to authenticated
using (id = auth.uid());

create policy "Users can insert their own profile"
on public.profiles
for insert
to authenticated
with check (id = auth.uid());

create policy "Users can update their own profile"
on public.profiles
for update
to authenticated
using (id = auth.uid())
with check (id = auth.uid());

create policy "Users can read their agents"
on public.agents
for select
to authenticated
using (owner_id = auth.uid());

create policy "Users can create their agents"
on public.agents
for insert
to authenticated
with check (owner_id = auth.uid());

create policy "Users can update their agents"
on public.agents
for update
to authenticated
using (owner_id = auth.uid())
with check (owner_id = auth.uid());

create policy "Users can delete their agents"
on public.agents
for delete
to authenticated
using (owner_id = auth.uid());

create policy "Users can manage their onboarding sessions"
on public.agent_onboarding_sessions
for all
to authenticated
using (owner_id = auth.uid())
with check (owner_id = auth.uid());

create policy "Users can read their telegram sessions"
on public.telegram_sessions
for select
to authenticated
using (
    exists (
        select 1
        from public.agents
        where agents.id = telegram_sessions.agent_id
            and agents.owner_id = auth.uid()
    )
);

create policy "Users can create their telegram sessions"
on public.telegram_sessions
for insert
to authenticated
with check (
    exists (
        select 1
        from public.agents
        where agents.id = telegram_sessions.agent_id
            and agents.owner_id = auth.uid()
    )
);

create policy "Users can update their telegram sessions"
on public.telegram_sessions
for update
to authenticated
using (
    exists (
        select 1
        from public.agents
        where agents.id = telegram_sessions.agent_id
            and agents.owner_id = auth.uid()
    )
)
with check (
    exists (
        select 1
        from public.agents
        where agents.id = telegram_sessions.agent_id
            and agents.owner_id = auth.uid()
    )
);

create policy "Users can manage their message threads"
on public.message_threads
for all
to authenticated
using (
    exists (
        select 1
        from public.agents
        where agents.id = message_threads.agent_id
            and agents.owner_id = auth.uid()
    )
)
with check (
    exists (
        select 1
        from public.agents
        where agents.id = message_threads.agent_id
            and agents.owner_id = auth.uid()
    )
);

create policy "Users can manage their agent messages"
on public.agent_messages
for all
to authenticated
using (
    exists (
        select 1
        from public.agents
        where agents.id = agent_messages.agent_id
            and agents.owner_id = auth.uid()
    )
)
with check (
    exists (
        select 1
        from public.agents
        where agents.id = agent_messages.agent_id
            and agents.owner_id = auth.uid()
    )
);

create policy "Users can manage their agent events"
on public.agent_events
for all
to authenticated
using (
    exists (
        select 1
        from public.agents
        where agents.id = agent_events.agent_id
            and agents.owner_id = auth.uid()
    )
)
with check (
    actor_user_id = auth.uid()
    and exists (
        select 1
        from public.agents
        where agents.id = agent_events.agent_id
            and agents.owner_id = auth.uid()
    )
);

alter publication supabase_realtime add table public.agent_events;
alter publication supabase_realtime add table public.agent_messages;

-- Automatically create a profile when a user signs up
create or replace function public.handle_new_user()
returns trigger
security definer set search_path = public
language plpgsql
as $$
begin
    insert into public.profiles (id, email, display_name)
    values (
        new.id,
        new.email,
        coalesce(new.raw_user_meta_data->>'display_name', new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1))
    );
    return new;
end;
$$;

create or replace trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();
