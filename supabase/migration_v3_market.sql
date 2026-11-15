-- =====================================================================
-- Migrasi v3 (Nov 2026): kondisi pasar IHSG + skor momentum + harga harian
-- Aman dijalankan berulang pada database yang SUDAH ada. Tidak menghapus data.
-- (schema.sql lengkap juga sudah memuat semua ini untuk project baru.)
-- =====================================================================

-- kolom baru di hasil screening
alter table public.screening_results add column if not exists dist_sma20_pct numeric;
alter table public.screening_results add column if not exists dist_ema50_pct numeric;
alter table public.screening_results add column if not exists macd_pct       numeric;
alter table public.screening_results add column if not exists hist_rising    boolean;
alter table public.screening_results add column if not exists suspended      boolean;
alter table public.screening_results add column if not exists pola_dasar     boolean;
alter table public.screening_results add column if not exists pola_terbaik   boolean;
alter table public.screening_results add column if not exists zone_score     int;
alter table public.screening_results add column if not exists market_regime  text;
alter table public.screening_runs    add column if not exists best_count     int;
alter table public.screening_runs    add column if not exists market_regime  text;

-- kondisi pasar harian
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
    trend_score       int,
    passed_count      int,
    passed_count_prev int,
    breadth_up        boolean,
    best_count        int,
    best_ok           boolean,
    triggers          int,
    regime            text check (regime in ('HIJAU','KUNING','MERAH')),
    note              text,
    created_at        timestamptz not null default now()
);

-- harga harian seluruh universe
create table if not exists public.daily_prices (
    trade_date  date not null,
    ticker      text not null,
    close       numeric,
    volume      bigint,
    value       numeric,
    primary key (trade_date, ticker)
);
create index if not exists idx_prices_ticker on public.daily_prices (ticker, trade_date desc);

-- akses baca untuk dashboard (anon key)
alter table public.market_daily enable row level security;
alter table public.daily_prices enable row level security;
drop policy if exists "read market" on public.market_daily;
drop policy if exists "read prices" on public.daily_prices;
create policy "read market" on public.market_daily for select to anon, authenticated using (true);
create policy "read prices" on public.daily_prices for select to anon, authenticated using (true);
grant select on public.market_daily, public.daily_prices to anon, authenticated;

create or replace view public.v_latest_market
with (security_invoker = true) as
select m.* from public.market_daily m
where m.run_date = (select max(run_date) from public.market_daily);
grant select on public.v_latest_market to anon, authenticated;
