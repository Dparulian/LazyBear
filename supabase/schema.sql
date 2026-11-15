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

-- 2b. Log eksekusi weekly universe refresh (1 baris per eksekusi)
create table if not exists public.universe_runs (
    id                 bigserial primary key,
    started_at         timestamptz,
    finished_at        timestamptz,
    status             text not null check (status in ('success','partial','failed')),
    full_refresh       boolean,
    source             text,                      -- yahoo_screener | seed_fallback
    existing_count     int,
    fetched_count      int,
    upserted_count     int,
    new_count          int,
    deactivated_count  int,
    message            text
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

-- v3 (Nov 2026): skor momentum per saham + label kondisi pasar
alter table public.screening_results add column if not exists dist_sma20_pct numeric;  -- close/SMA20-1 (%)
alter table public.screening_results add column if not exists dist_ema50_pct numeric;  -- close/EMA50-1 (%)
alter table public.screening_results add column if not exists macd_pct       numeric;  -- MACD / close (%)
alter table public.screening_results add column if not exists hist_rising    boolean;  -- histogram naik vs kemarin
alter table public.screening_results add column if not exists suspended      boolean;  -- volume 0 (kemungkinan suspensi)
alter table public.screening_results add column if not exists pola_dasar     boolean;  -- close>SMA20, MACD>=5% harga, nilai trx<Rp50M
alter table public.screening_results add column if not exists pola_terbaik   boolean;  -- pola dasar + hist>0 + close>=10% di atas SMA20
alter table public.screening_results add column if not exists zone_score     int;      -- 0-3 zona ideal (hanya utk pola terbaik)
alter table public.screening_results add column if not exists market_regime  text;     -- HIJAU / KUNING / MERAH saat run
alter table public.screening_runs    add column if not exists best_count     int;
alter table public.screening_runs    add column if not exists market_regime  text;

-- 4. Kondisi pasar harian: indikator IHSG + 3 pemicu + lampu
create table if not exists public.market_daily (
    run_date          date primary key references public.screening_runs(run_date) on delete cascade,
    index_symbol      text,
    close             numeric,
    change_pct        numeric,
    sma20             numeric,
    ema50             numeric,
    macd              numeric,
    macd_signal       numeric,
    macd_hist         numeric,
    above_sma20       boolean,
    above_ema50       boolean,
    macd_positive     boolean,
    trend_score       int,                         -- 0-3 (pemicu 1 terpenuhi bila 3)
    passed_count      int,                         -- jumlah saham lolos screener
    passed_count_prev int,                         -- jumlah lolos N hari bursa lalu
    breadth_up        boolean,                     -- pemicu 2
    best_count        int,                         -- jumlah saham pola terbaik
    best_ok           boolean,                     -- pemicu 3
    triggers          int,                         -- 0-3
    regime            text check (regime in ('HIJAU','KUNING','MERAH')),
    note              text,
    created_at        timestamptz not null default now()
);

-- 5. Harga harian seluruh universe (untuk evaluasi setelah saham keluar dari daftar)
create table if not exists public.daily_prices (
    trade_date  date not null,
    ticker      text not null,
    close       numeric,
    volume      bigint,
    value       numeric,                           -- close * volume (Rp)
    primary key (trade_date, ticker)
);
create index if not exists idx_prices_ticker on public.daily_prices (ticker, trade_date desc);

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
alter table public.universe_runs     enable row level security;
alter table public.market_daily      enable row level security;
alter table public.daily_prices      enable row level security;

drop policy if exists "read stocks"  on public.stocks;
drop policy if exists "read runs"    on public.screening_runs;
drop policy if exists "read results" on public.screening_results;
drop policy if exists "read universe runs" on public.universe_runs;
drop policy if exists "read market" on public.market_daily;
drop policy if exists "read prices" on public.daily_prices;
create policy "read stocks"  on public.stocks            for select to anon, authenticated using (true);
create policy "read runs"    on public.screening_runs    for select to anon, authenticated using (true);
create policy "read results" on public.screening_results for select to anon, authenticated using (true);
create policy "read universe runs" on public.universe_runs for select to anon, authenticated using (true);
create policy "read market" on public.market_daily for select to anon, authenticated using (true);
create policy "read prices" on public.daily_prices for select to anon, authenticated using (true);

-- Pastikan role API boleh membaca (beberapa project baru tidak memberi grant otomatis)
grant usage on schema public to anon, authenticated;
grant select on public.stocks, public.screening_runs, public.screening_results, public.universe_runs,
  public.market_daily, public.daily_prices to anon, authenticated;

-- View praktis: hasil run sukses terakhir
create or replace view public.v_latest_results
with (security_invoker = true) as
select r.*
from public.screening_results r
where r.run_date = (select max(run_date) from public.screening_runs where status = 'success');

grant select on public.v_latest_results to anon, authenticated;

-- View: kondisi pasar terakhir
create or replace view public.v_latest_market
with (security_invoker = true) as
select m.* from public.market_daily m
where m.run_date = (select max(run_date) from public.market_daily);
grant select on public.v_latest_market to anon, authenticated;
