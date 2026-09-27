-- =====================================================================
-- IDX SMA20 x EMA50 + MACD Screener — skema Supabase
-- Jalankan sekali di Supabase Dashboard > SQL Editor
-- =====================================================================

-- 1. Master saham (universe) + klasifikasi sektor/industri
create table if not exists public.stocks (
    ticker      text primary key,                 -- kode IDX tanpa .JK, mis. BBCA
    name        text,
    sector      text,
    industry    text,
    source      text default 'yahoo',             -- yahoo | override
    is_active   boolean not null default true,
    updated_at  timestamptz not null default now()
);

-- 2. Log setiap eksekusi harian (1 baris per tanggal bursa)
create table if not exists public.screening_runs (
    run_date          date primary key,           -- tanggal bar terakhir (tanggal bursa)
    started_at        timestamptz,
    finished_at       timestamptz,
    status            text not null check (status in ('running','success','failed')),
    universe_count    int,
    downloaded_count  int,
    liquid_count      int,
    passed_count      int,
    new_count         int,
    exited_count      int,
    message           text
);

-- 3. Hasil screening (hanya saham yang lolos)
create table if not exists public.screening_results (
    run_date           date not null references public.screening_runs(run_date) on delete cascade,
    ticker             text not null,
    name               text,
    sector             text,
    industry           text,
    status             text not null check (status in ('BARU','MASIH')),
    streak             int  not null default 1,   -- berapa run berturut-turut lolos
    first_passed_date  date,
    close              numeric,
    change_pct         numeric,
    sma20              numeric,
    ema50              numeric,
    spread_pct         numeric,                   -- (SMA20/EMA50 - 1) * 100
    macd               numeric,
    macd_signal        numeric,
    macd_hist          numeric,
    macd_state         text check (macd_state in ('CROSS_UP_0','ABOVE_0')),
    macd_cross_date    date,
    cross_date         date,                      -- tanggal golden cross SMA20/EMA50
    entry_date         date,                      -- bar pertama setup valid (cross + MACD > 0)
    days_since_cross   int,
    volume             bigint,
    avg_value_20d      numeric,                   -- rata-rata nilai transaksi 20 hari (Rp)
    created_at         timestamptz not null default now(),
    primary key (run_date, ticker)
);

-- untuk database yang sudah dibuat dengan versi skema sebelumnya
alter table public.screening_results add column if not exists entry_date date;

create index if not exists idx_results_run_date on public.screening_results (run_date desc);
create index if not exists idx_results_sector   on public.screening_results (run_date, sector, industry);
create index if not exists idx_results_ticker   on public.screening_results (ticker, run_date desc);

-- updated_at otomatis
create or replace function public.touch_updated_at() returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;
drop trigger if exists trg_stocks_touch on public.stocks;
create trigger trg_stocks_touch before update on public.stocks
for each row execute function public.touch_updated_at();

-- =====================================================================
-- Row Level Security
--   * Dashboard Streamlit memakai ANON key  -> hanya boleh SELECT
--   * GitHub Actions memakai SERVICE_ROLE key -> bypass RLS (boleh tulis)
-- =====================================================================
alter table public.stocks            enable row level security;
alter table public.screening_runs    enable row level security;
alter table public.screening_results enable row level security;

drop policy if exists "read stocks"  on public.stocks;
drop policy if exists "read runs"    on public.screening_runs;
drop policy if exists "read results" on public.screening_results;
create policy "read stocks"  on public.stocks            for select to anon, authenticated using (true);
create policy "read runs"    on public.screening_runs    for select to anon, authenticated using (true);
create policy "read results" on public.screening_results for select to anon, authenticated using (true);

-- View praktis: hasil run sukses terakhir
create or replace view public.v_latest_results
with (security_invoker = true) as
select r.*
from public.screening_results r
where r.run_date = (select max(run_date) from public.screening_runs where status = 'success');
