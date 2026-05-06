-- Sales pipeline + customer CRM tables.
-- Run this in the Supabase SQL editor (Project → SQL → New query).
-- Idempotent: safe to re-run.

-- ----------------------------------------------------------------------
-- customers — corporate accounts
-- ----------------------------------------------------------------------
create table if not exists evone_billing.customers (
    id uuid primary key default gen_random_uuid(),
    name text not null unique,
    status text not null default 'prospect',
        -- conventional values: prospect, active, churned
    account_manager_id uuid references evone_billing.users(id) on delete set null,
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- ----------------------------------------------------------------------
-- contacts — people at customer companies
-- ----------------------------------------------------------------------
create table if not exists evone_billing.contacts (
    id uuid primary key default gen_random_uuid(),
    customer_id uuid not null references evone_billing.customers(id) on delete cascade,
    name text not null,
    email text,
    phone text,
    role text,
    notes text,
    created_at timestamptz not null default now()
);

create index if not exists contacts_customer_idx
    on evone_billing.contacts(customer_id);

-- ----------------------------------------------------------------------
-- deals — sales pipeline
-- ----------------------------------------------------------------------
create table if not exists evone_billing.deals (
    id uuid primary key default gen_random_uuid(),
    customer_id uuid references evone_billing.customers(id) on delete set null,
    title text not null,
    stage text not null default 'new',
    amount numeric(14, 2),
    currency text default 'SGD',
    owner_id uuid references evone_billing.users(id) on delete set null,
    expected_close_date date,
    notes text,
    closed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint deals_stage_check
        check (stage in ('new', 'quoted', 'negotiating', 'won', 'lost'))
);

create index if not exists deals_stage_idx on evone_billing.deals(stage);
create index if not exists deals_customer_idx on evone_billing.deals(customer_id);
create index if not exists deals_owner_idx on evone_billing.deals(owner_id);

-- ----------------------------------------------------------------------
-- Grants — the service_role key (used by the FastAPI backend) needs
-- explicit table-level access. Supabase does not auto-grant on tables
-- created via the SQL editor.
-- ----------------------------------------------------------------------
grant usage on schema evone_billing to service_role;
grant select, insert, update, delete
    on evone_billing.customers,
       evone_billing.contacts,
       evone_billing.deals
    to service_role;
