"""Lazy Bear Screener — dashboard Streamlit.

Jalankan lokal:  streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app import charts, data_source as ds  # noqa: E402
from screener.config import CONFIG, sector_label  # noqa: E402

st.set_page_config(page_title="IDX Momentum Screener", page_icon="📈", layout="wide")

st.markdown(
    """
<style>
.block-container {padding-top: 1.6rem;}
.kpi {border-radius: 14px; padding: 14px 18px; background: #131c2e; border: 1px solid #1f2a44;
      border-left: 5px solid var(--c); height: 100%;}
.kpi .lbl {font-size: .78rem; color: #94a3b8; text-transform: uppercase; letter-spacing: .06em;}
.kpi .val {font-size: 1.9rem; font-weight: 700; color: #f1f5f9; line-height: 1.2;}
.kpi .sub {font-size: .8rem; color: #94a3b8;}
.hero h1 {font-size: 1.9rem; margin-bottom: .2rem;}
.chip {display:inline-block; padding: 2px 10px; border-radius: 999px; font-size: .78rem;
       font-weight: 600; margin-right: 6px; border: 1px solid #334155; color:#e2e8f0;}
.chip.baru {background: rgba(34,197,94,.18); border-color:#22c55e; color:#86efac;}
.chip.masih {background: rgba(59,130,246,.18); border-color:#3b82f6; color:#93c5fd;}
.chip.keluar {background: rgba(239,68,68,.15); border-color:#ef4444; color:#fca5a5;}
.sec-head {display:flex; justify-content:space-between; align-items:center;}
.regime {border-radius: 16px; padding: 16px 20px; border: 1px solid #1f2a44; background: #131c2e;
         border-left: 8px solid var(--c); display:flex; gap: 22px; align-items:center; flex-wrap: wrap;}
.regime .light {font-size: 2.1rem; font-weight: 800; color: var(--c); line-height: 1; white-space: nowrap;}
.regime .light small {display:block; font-size: .72rem; color:#94a3b8; font-weight: 600; letter-spacing:.06em; margin-top: 4px;}
.regime .trig {display:flex; gap: 10px; flex-wrap: wrap; flex: 1;}
.trig .t {border-radius: 10px; padding: 8px 12px; background:#0b1220; border:1px solid #1f2a44; min-width: 180px;}
.trig .t .n {font-size:.72rem; color:#94a3b8; text-transform:uppercase; letter-spacing:.05em;}
.trig .t .v {font-size:.95rem; font-weight:700; color:#f1f5f9; margin-top:2px;}
.trig .t.ok {border-color:#22c55e;} .trig .t.ok .v {color:#86efac;}
.trig .t.no {border-color:#ef4444;} .trig .t.no .v {color:#fca5a5;}
.regime .advice {font-size:.85rem; color:#cbd5e1; max-width: 100%; margin-top: 8px;}
</style>
""",
    unsafe_allow_html=True,
)

STATUS_ICON = {"BARU": "🟢 BARU", "MASIH": "🔵 MASIH"}
MACD_LABEL = {"CROSS_UP_0": "⬆️ Baru tembus 0", "ABOVE_0": "✅ Di atas 0"}


def kpi(col, label, value, sub="", color="#64748b"):
    col.markdown(
        f'<div class="kpi" style="--c:{color}"><div class="lbl">{label}</div>'
        f'<div class="val">{value}</div><div class="sub">{sub}</div></div>',
        unsafe_allow_html=True,
    )


def fmt_value(v):
    if pd.isna(v):
        return "-"
    return f"Rp{v/1e12:,.2f} T" if v >= 1e12 else f"Rp{v/1e9:,.1f} M"


REGIME_META = {
    "HIJAU": ("#22c55e", "🟢", "Pola momentum boleh dipakai. Sebar ke 3–5 saham, cut loss di bawah SMA20 / −8%."),
    "KUNING": ("#f59e0b", "🟡", "Hati-hati: porsi kecil, utamakan saham likuid dengan zona ideal ≥ 2. Jangan kejar harga."),
    "MERAH": ("#ef4444", "🔴", "Mode bertahan. Secara historis pola momentum hanya ±16% kena +10% di fase ini, 62% rugi ≥ 10%."),
}


def regime_banner(m: dict | None, n_pass: int, n_best: int):
    """Banner kondisi pasar: lampu + 3 pemicu + saran."""
    if m is None:
        st.info("Kondisi pasar belum tersedia untuk tanggal ini. Jalankan `supabase/schema.sql` versi terbaru dan "
                "workflow **Daily IDX Screener** agar tabel `market_daily` terisi.")
        return
    reg = m.get("regime") or "MERAH"
    color, icon, advice = REGIME_META.get(reg, REGIME_META["MERAH"])
    has_idx = m.get("close") is not None and not pd.isna(m.get("close"))
    trend_ok = bool(m.get("trend_score") == 3) if has_idx else False
    parts = []
    if has_idx:
        parts.append(f"IHSG {m['close']:,.0f} ({m['change_pct']:+.2f}%) · SMA20 {'✔' if m.get('above_sma20') else '✘'} · "
                     f"EMA50 {'✔' if m.get('above_ema50') else '✘'} · MACD {'✔' if m.get('macd_positive') else '✘'}")
    else:
        parts.append("data IHSG tidak tersedia")
    prev = m.get("passed_count_prev")
    breadth_txt = (f"{int(prev)} → {int(m.get('passed_count') or n_pass)} saham" if prev is not None and not pd.isna(prev)
                   else f"{n_pass} saham (belum ada pembanding)")
    best_txt = f"{int(m.get('best_count') if m.get('best_count') is not None else n_best)} saham (min. {CONFIG.regime_min_best})"
    trig = [("1 · Tren IHSG", parts[0], trend_ok),
            (f"2 · Breadth ({CONFIG.regime_breadth_days} hari)", breadth_txt, bool(m.get("breadth_up"))),
            ("3 · Pola terbaik", best_txt, bool(m.get("best_ok")))]
    html = (f'<div class="regime" style="--c:{color}"><div class="light">{icon} {reg}'
            f'<small>KONDISI PASAR · {int(m.get("triggers") or 0)}/3 PEMICU</small></div><div class="trig">'
            + "".join(f'<div class="t {"ok" if ok else "no"}"><div class="n">{n}</div><div class="v">{"✔" if ok else "✘"} {v}</div></div>'
                      for n, v, ok in trig)
            + f'</div><div class="advice">{advice}</div></div>')
    st.markdown(html, unsafe_allow_html=True)


def display_table(df: pd.DataFrame) -> pd.DataFrame:
    t = pd.DataFrame({
        "Status": df["status"].map(STATUS_ICON),
        "Kode": df["ticker"],
        "Nama": df["name"].fillna(""),
        "Industri": df["industry"],
        "Harga": df["close"],
        "Chg %": df["change_pct"],
        "Umur tren (hari)": df["days_since_cross"].astype("Int64"),
        "Tgl Cross": df["cross_date"],
        "MACD": df["macd_state"].map(MACD_LABEL),
        "Spread SMA/EMA %": df["spread_pct"],
        "Streak": df["streak"].astype("Int64"),
        "Nilai Transaksi 20H (Rp M)": df["avg_value_20d"] / 1e9,
        "vs SMA20 %": df.get("dist_sma20_pct"),
        "MACD % harga": df.get("macd_pct"),
        "Pola": df.apply(lambda r: ("⛔ Suspensi" if r.get("suspended") else
                                   "⭐ Terbaik" if r.get("pola_terbaik") else
                                   "Dasar" if r.get("pola_dasar") else "–"), axis=1) if len(df) else [],
        "Zona ideal": df.get("zone_score"),
    })
    return t


def style_table(t: pd.DataFrame):
    def status_css(v):
        if isinstance(v, str) and "BARU" in v:
            return "background-color: rgba(34,197,94,.20); color:#86efac; font-weight:700"
        if isinstance(v, str) and "MASIH" in v:
            return "background-color: rgba(59,130,246,.18); color:#93c5fd; font-weight:600"
        return ""

    def chg_css(v):
        if pd.isna(v):
            return ""
        return "color:#4ade80" if v > 0 else ("color:#f87171" if v < 0 else "")

    return t.style.map(status_css, subset=["Status"]).map(chg_css, subset=["Chg %"])


COLUMN_CONFIG = {
    "Harga": st.column_config.NumberColumn(format="%.0f"),
    "Chg %": st.column_config.NumberColumn(format="%+.2f%%"),
    "Spread SMA/EMA %": st.column_config.NumberColumn(format="%.2f%%"),
    "Nilai Transaksi 20H (Rp M)": st.column_config.ProgressColumn(format="%.1f", min_value=0,
                                                                  max_value=500),
    "Nama": st.column_config.TextColumn(width="medium"),
    "vs SMA20 %": st.column_config.NumberColumn(format="%+.1f%%", help="Jarak close ke SMA20"),
    "MACD % harga": st.column_config.NumberColumn(format="%.1f%%", help="MACD dibagi harga"),
    "Zona ideal": st.column_config.ProgressColumn(format="%d", min_value=0, max_value=3,
                                                  help="0–3: close 15–40% di atas SMA20, 25–40% di atas EMA50, MACD 7–10%"),
}

# ---------------------------------------------------------------- data
try:
    runs = ds.list_runs()
except Exception as exc:  # noqa: BLE001
    st.title("📈 IDX Momentum Screener")
    st.error(f"Gagal membaca Supabase: {exc}")
    st.stop()
if runs.empty:
    st.cache_data.clear()  # jangan simpan hasil kosong di cache
    st.title("📈 IDX Momentum Screener")
    if ds.mode() == "local":
        st.warning("Secrets **SUPABASE_URL** / **SUPABASE_ANON_KEY** tidak terbaca, sehingga dashboard "
                   "berjalan di mode lokal. Periksa *Manage app → Settings → Secrets* lalu reboot app.")
    else:
        st.info("Terhubung ke Supabase, tetapi belum ada baris `screening_runs` berstatus **success** "
                "yang bisa dibaca. Cek status run di Supabase atau jalankan workflow **Daily IDX Screener**.")
    st.caption(f"Mode sumber data: **{ds.mode()}**")
    if st.button("🔄 Coba lagi"):
        st.rerun()
    st.stop()

with st.sidebar:
    st.markdown("### ⚙️ Filter")
    run_date = st.selectbox("Tanggal bursa", runs["run_date"].tolist(), index=0,
                            format_func=lambda d: d.strftime("%a, %d %b %Y"))
    res = ds.get_results(run_date)
    older = runs[runs["run_date"] < run_date]
    prev_date = older["run_date"].iloc[0] if not older.empty else None
    prev = ds.get_results(prev_date) if prev_date else pd.DataFrame()

    market_hist = ds.list_market()
    market = ds.get_market(run_date)
    if not res.empty:
        res["sector_label"] = res["sector"].map(sector_label)
        for c, d in (("suspended", False), ("pola_dasar", False), ("pola_terbaik", False), ("zone_score", 0),
                     ("dist_sma20_pct", None), ("macd_pct", None), ("hist_rising", False), ("market_regime", None)):
            if c not in res.columns:
                res[c] = d
        res["suspended"] = res["suspended"].fillna(False).astype(bool)
        res["pola_terbaik"] = res["pola_terbaik"].fillna(False).astype(bool)
        res["pola_dasar"] = res["pola_dasar"].fillna(False).astype(bool)
        res["zone_score"] = pd.to_numeric(res["zone_score"], errors="coerce").fillna(0).astype(int)
    status_pick = st.multiselect("Status", ["BARU", "MASIH"], default=["BARU", "MASIH"])
    hide_susp = st.checkbox("Sembunyikan saham suspensi (volume 0)", value=True)
    pola_pick = st.radio("Pola momentum", ["Semua", "⭐ Pola terbaik saja", "Pola dasar & terbaik"])
    sectors = sorted(res["sector_label"].unique()) if not res.empty else []
    sector_pick = st.multiselect("Sektor", sectors, placeholder="Semua sektor")
    macd_pick = st.radio("Kondisi MACD", ["Semua", "Baru tembus 0", "Sudah di atas 0"],
                         horizontal=False)
    max_age_all = int(res["days_since_cross"].max()) if not res.empty else 0
    max_age = st.slider("Maks. umur tren (hari sejak golden cross)", 0, max(max_age_all, 1),
                        max(max_age_all, 1), help="Geser ke kiri untuk melihat setup yang masih segar saja")
    min_val = st.number_input("Min. nilai transaksi 20H (Rp miliar)", 0.0, 1000.0, 0.0, 1.0)
    search = st.text_input("Cari kode / nama", "").strip().upper()
    st.divider()
    st.caption(f"Sumber data: **{'Supabase' if ds.mode() == 'supabase' else 'Lokal (output/)'}** · "
               "Harga & grafik: Yahoo Finance")
    if st.button("🔄 Muat ulang data", width="stretch"):
        st.cache_data.clear()
        st.rerun()

view = res.copy()
if not view.empty:
    view = view[view["status"].isin(status_pick)]
    if sector_pick:
        view = view[view["sector_label"].isin(sector_pick)]
    if macd_pick != "Semua":
        view = view[view["macd_state"] == ("CROSS_UP_0" if macd_pick.startswith("Baru") else "ABOVE_0")]
    view = view[view["avg_value_20d"].fillna(0) >= min_val * 1e9]
    view = view[view["days_since_cross"].fillna(0) <= max_age]
    if hide_susp:
        view = view[~view["suspended"]]
    if pola_pick.startswith("⭐"):
        view = view[view["pola_terbaik"]]
    elif pola_pick.startswith("Pola dasar"):
        view = view[view["pola_dasar"] | view["pola_terbaik"]]
    if search:
        view = view[view["ticker"].str.contains(search) | view["name"].fillna("").str.upper().str.contains(search)]

exited = pd.DataFrame()
if not prev.empty:
    cur_set = set(res["ticker"]) if not res.empty else set()
    exited = prev[~prev["ticker"].isin(cur_set)].copy()

# ---------------------------------------------------------------- header
st.markdown(
    f"""<div class="hero"><h1>📈 IDX Momentum Screener</h1>
<span class="chip">SMA {CONFIG.sma_period} ↗ EMA {CONFIG.ema_period}</span>
<span class="chip">MACD &gt; 0</span>
<span class="chip">Tampil selama tren valid</span>
<span class="chip">Nilai transaksi ≥ Rp{CONFIG.min_avg_value_idr/1e9:,.0f} M/hari</span>
<span class="chip">Data per {run_date:%d %b %Y}</span></div>""",
    unsafe_allow_html=True,
)
st.write("")

n_all = len(res)
n_new = int((res["status"] == "BARU").sum()) if n_all else 0
n_still = n_all - n_new
n_best = int(res["pola_terbaik"].sum()) if n_all else 0
n_susp = int(res["suspended"].sum()) if n_all else 0
prev_n = len(prev)
regime_banner(market, n_all, n_best)
st.write("")
c1, c2, c3, c4, c5, c6 = st.columns(6)
kpi(c1, "Total lolos", n_all, f"{n_all - prev_n:+d} vs run sebelumnya" if prev_date else "run pertama", "#a78bfa")
kpi(c2, "🟢 BARU", n_new, "baru masuk hari ini", "#22c55e")
kpi(c3, "🔵 MASIH", n_still, "lolos di run sebelumnya juga", "#3b82f6")
kpi(c4, "🔴 KELUAR", len(exited), f"vs {prev_date:%d %b}" if prev_date else "-", "#ef4444")
kpi(c5, "⭐ Pola terbaik", n_best, f"{n_susp} saham volume 0 (suspensi)" if n_susp else "tanpa suspensi", "#fbbf24")
kpi(c6, "Sektor", res["sector_label"].nunique() if n_all else 0,
    f"{res['industry'].nunique() if n_all else 0} industri", "#f59e0b")
st.write("")

tab0, tab_mkt, tab1, tab2, tab3, tab4 = st.tabs(["🎯 Kandidat", "🌐 Kondisi Pasar", "🏭 Per Sektor & Industri",
                                                  "📊 Grafik Teknikal", "🔄 Keluar & Riwayat", "ℹ️ Metodologi"])

# ---------------------------------------------------------------- tab 0: kandidat
with tab0:
    reg_now = (market or {}).get("regime") or "–"
    cand = res[~res["suspended"]].copy() if n_all else pd.DataFrame()
    if cand.empty:
        st.warning("Tidak ada saham di daftar hari ini.")
    else:
        if reg_now == "MERAH":
            st.error("🔴 **Pasar MERAH** — kandidat di bawah ditampilkan untuk pemantauan, bukan untuk dibeli. "
                     "Tunggu minimal 2 pemicu terpenuhi.")
        elif reg_now == "KUNING":
            st.warning("🟡 **Pasar KUNING** — hanya kandidat dengan zona ideal ≥ 2 dan nilai transaksi ≥ Rp5 M, porsi kecil.")
        else:
            st.success("🟢 **Pasar HIJAU** — pola momentum boleh dipakai sesuai aturan posisi.")

        best = cand[cand["pola_terbaik"]].copy()
        best["_rank"] = (best["zone_score"] * 10 + best["hist_rising"].astype(int) * 3
                         + (best["avg_value_20d"] >= 5e9).astype(int) * 2 + (best["change_pct"] > -5).astype(int))
        best = best.sort_values(["_rank", "avg_value_20d"], ascending=False)
        st.markdown(f"##### ⭐ Pola terbaik ({len(best)}) — diurutkan: zona ideal → MACD histogram naik → likuiditas")
        if best.empty:
            st.caption("Tidak ada saham yang memenuhi pola terbaik hari ini (close > SMA20 ≥ 10%, MACD ≥ 5% harga, "
                       "histogram positif, nilai transaksi < Rp50 M).")
        else:
            cols_c = {"ticker": "Kode", "name": "Nama", "sector_label": "Sektor", "close": "Harga", "change_pct": "Chg %",
                      "dist_sma20_pct": "vs SMA20 %", "dist_ema50_pct": "vs EMA50 %", "macd_pct": "MACD % harga",
                      "hist_rising": "Hist. naik", "zone_score": "Zona ideal", "days_since_cross": "Umur tren",
                      "avg_value_20d": "Nilai trx (Rp M)", "streak": "Streak"}
            t = best[list(cols_c)].rename(columns=cols_c)
            t["Nilai trx (Rp M)"] = t["Nilai trx (Rp M)"] / 1e9
            st.dataframe(t, hide_index=True, width="stretch", column_config={
                "Harga": st.column_config.NumberColumn(format="%.0f"),
                "Chg %": st.column_config.NumberColumn(format="%+.2f%%"),
                "vs SMA20 %": st.column_config.NumberColumn(format="%+.1f%%"),
                "vs EMA50 %": st.column_config.NumberColumn(format="%+.1f%%"),
                "MACD % harga": st.column_config.NumberColumn(format="%.1f%%"),
                "Zona ideal": st.column_config.ProgressColumn(format="%d", min_value=0, max_value=3),
                "Nilai trx (Rp M)": st.column_config.NumberColumn(format="%.1f"),
                "Hist. naik": st.column_config.CheckboxColumn(),
            })
            st.caption("Zona ideal (0–3): close 15–40% di atas SMA20 · 25–40% di atas EMA50 · MACD 7–10% dari harga. "
                       "Historis (25 Sep–13 Nov 2026): zona ideal penuh ≈ 40–43% kena +10% dalam 3 minggu di fase naik.")

        mid = cand[(~cand["pola_terbaik"]) & (cand["dist_sma20_pct"].fillna(-1) > 0)
                   & (cand["spread_pct"] > 0) & (cand["days_since_cross"].fillna(0) >= 15)].copy()
        mid = mid.sort_values(["spread_pct", "avg_value_20d"], ascending=False).head(15)
        st.markdown(f"##### 📈 Mid-term uptrend ({len(mid)}) — umur tren ≥ 15 hari, close di atas SMA20, bukan pola terbaik")
        if mid.empty:
            st.caption("Tidak ada.")
        else:
            cols_m = {"ticker": "Kode", "name": "Nama", "sector_label": "Sektor", "close": "Harga", "change_pct": "Chg %",
                      "days_since_cross": "Umur tren", "spread_pct": "Spread SMA/EMA %", "dist_sma20_pct": "vs SMA20 %",
                      "macd_pct": "MACD % harga", "avg_value_20d": "Nilai trx (Rp M)", "streak": "Streak"}
            t = mid[list(cols_m)].rename(columns=cols_m); t["Nilai trx (Rp M)"] = t["Nilai trx (Rp M)"] / 1e9
            st.dataframe(t, hide_index=True, width="stretch", column_config={
                "Harga": st.column_config.NumberColumn(format="%.0f"), "Chg %": st.column_config.NumberColumn(format="%+.2f%%"),
                "Spread SMA/EMA %": st.column_config.NumberColumn(format="%.2f%%"),
                "vs SMA20 %": st.column_config.NumberColumn(format="%+.1f%%"),
                "MACD % harga": st.column_config.NumberColumn(format="%.1f%%"),
                "Nilai trx (Rp M)": st.column_config.NumberColumn(format="%.1f")})

        weak = cand[cand["dist_sma20_pct"].fillna(0) <= 0]
        if not weak.empty:
            st.markdown(f"##### ⚠️ Close di bawah SMA20 ({len(weak)}) — calon keluar dari daftar")
            st.caption(", ".join(weak.sort_values("dist_sma20_pct")["ticker"]))
        if n_susp:
            st.markdown(f"##### ⛔ Volume 0 / kemungkinan suspensi ({n_susp})")
            st.caption(", ".join(res[res["suspended"]]["ticker"]) + " — cek pengumuman BEI sebelum transaksi.")

# ---------------------------------------------------------------- tab: kondisi pasar
with tab_mkt:
    if market_hist.empty:
        st.info("Belum ada data `market_daily`. Jalankan `supabase/schema.sql` terbaru lalu workflow harian.")
    else:
        mcol1, mcol2 = st.columns([2, 1], gap="large")
        with mcol1:
            st.markdown("##### IHSG (^JKSE) · SMA20 / EMA50 / MACD · pita lampu harian")
            try:
                ipx = ds.get_index_prices(CONFIG.index_symbol, "1y")
            except Exception as exc:  # noqa: BLE001
                ipx = pd.DataFrame(); st.error(f"Gagal mengambil IHSG dari Yahoo: {exc}")
            if ipx.empty or len(ipx) < CONFIG.ema_period + 5:
                st.warning("Data IHSG dari Yahoo tidak tersedia saat ini.")
            else:
                st.plotly_chart(charts.index_chart(ipx, market_hist, "1y"), width="stretch")
        with mcol2:
            st.markdown("##### Breadth: lolos screener vs pola terbaik")
            st.plotly_chart(charts.breadth_chart(market_hist.head(60)), width="stretch")
            st.markdown("##### Riwayat lampu (30 hari)")
            h = market_hist.head(30)[["run_date", "regime", "triggers", "close", "change_pct", "passed_count", "best_count", "note"]]
            h = h.rename(columns={"run_date": "Tanggal", "regime": "Lampu", "triggers": "Pemicu", "close": "IHSG",
                                  "change_pct": "Chg %", "passed_count": "Lolos", "best_count": "Pola terbaik", "note": "Catatan"})
            st.dataframe(h.style.map(lambda v: {"HIJAU": "color:#86efac;font-weight:700", "KUNING": "color:#fcd34d;font-weight:700",
                                                 "MERAH": "color:#fca5a5;font-weight:700"}.get(v, ""), subset=["Lampu"]),
                         hide_index=True, width="stretch", height=380,
                         column_config={"IHSG": st.column_config.NumberColumn(format="%.0f"),
                                        "Chg %": st.column_config.NumberColumn(format="%+.2f%%")})
        st.caption("Lampu: HIJAU = 3 pemicu · KUNING = 2 · MERAH = 0–1. Pemicu: (1) IHSG > SMA20 & EMA50 dan MACD > 0; "
                   f"(2) jumlah saham lolos naik vs {CONFIG.regime_breadth_days} hari bursa lalu; "
                   f"(3) ≥ {CONFIG.regime_min_best} saham pola terbaik.")

# ---------------------------------------------------------------- tab 1
with tab1:
    if view.empty:
        st.warning("Tidak ada saham yang sesuai filter.")
    else:
        left, right = st.columns([1, 1], gap="large")
        with left:
            st.markdown("##### Sebaran per sektor")
            st.plotly_chart(charts.sector_bar(view), width="stretch")
        with right:
            st.markdown("##### Ringkasan per industri")
            summ = (view.groupby(["sector_label", "industry"])
                    .agg(Saham=("ticker", "count"), BARU=("status", lambda s: int((s == "BARU").sum())),
                         Kode=("ticker", lambda s: ", ".join(s)))
                    .reset_index().rename(columns={"sector_label": "Sektor", "industry": "Industri"})
                    .sort_values(["Sektor", "Industri"]))
            st.dataframe(summ, hide_index=True, width="stretch",
                         height=min(420, 38 * (len(summ) + 1) + 4))

        st.markdown(f"##### {len(view)} saham, dikelompokkan per sektor → industri")
        order = sorted(view["sector_label"].unique())
        for sec in order:
            g = view[view["sector_label"] == sec].sort_values(
                ["industry", "status", "avg_value_20d"], ascending=[True, True, False])
            nb = int((g["status"] == "BARU").sum())
            title = f"**{sec}** · {len(g)} saham" + (f" · 🟢 {nb} BARU" if nb else "")
            with st.expander(title, expanded=len(order) <= 6):
                st.dataframe(style_table(display_table(g)), hide_index=True,
                             width="stretch", column_config=COLUMN_CONFIG)
        st.download_button(
            "⬇️ Unduh hasil (CSV)", view.drop(columns=["sector_label"]).to_csv(index=False),
            file_name=f"screener_{run_date}.csv", mime="text/csv")

# ---------------------------------------------------------------- tab 2
with tab2:
    opts = view["ticker"].tolist() if not view.empty else []
    labels = {r.ticker: f"{r.ticker} — {r.name or ''} ({r.status})" for r in view.itertuples()} if opts else {}
    a, b, c = st.columns([2, 1, 1])
    pick = a.selectbox("Saham hasil screening", opts, format_func=lambda t: labels.get(t, t)) if opts else None
    other = b.text_input("…atau cek kode lain", "", placeholder="mis. BBCA").strip().upper()
    period = c.radio("Periode", ["6mo", "1y", "2y"], index=1, horizontal=True)
    ticker = other or pick

    if ticker:
        with st.spinner(f"Mengambil harga {ticker}.JK dari Yahoo Finance…"):
            try:
                px = ds.get_prices(ticker, period)
            except Exception as exc:  # noqa: BLE001
                px = pd.DataFrame()
                st.error(f"Gagal mengambil data Yahoo: {exc}")
        if px.empty or len(px) < CONFIG.ema_period + 5:
            st.warning(f"Data harga {ticker}.JK tidak tersedia / terlalu pendek.")
        else:
            from screener.signals import evaluate_stock

            m = evaluate_stock(px) or {}
            row = res[res["ticker"] == ticker]
            status = row["status"].iloc[0] if not row.empty else None
            k1, k2, k3, k4, k5 = st.columns(5)
            kpi(k1, f"{ticker} · harga", f"{m.get('close', 0):,.0f}",
                f"{m.get('change_pct', 0):+.2f}% hari ini",
                "#22c55e" if m.get("change_pct", 0) >= 0 else "#ef4444")
            kpi(k2, f"SMA{CONFIG.sma_period} vs EMA{CONFIG.ema_period}",
                f"{m.get('spread_pct', 0):+.2f}%",
                f"cross {m['days_since_cross']} hari lalu" if m.get("days_since_cross") is not None else "belum ada cross",
                "#f59e0b")
            kpi(k3, "MACD", f"{m.get('macd', 0):,.1f}",
                MACD_LABEL.get(m.get("macd_state"), "⛔ Di bawah 0"), "#a78bfa")
            kpi(k4, "Nilai transaksi 20H", fmt_value(m.get("avg_value_20d")), "rata-rata harian", "#38bdf8")
            kpi(k5, "Status screener",
                STATUS_ICON.get(status, "⚪ Tidak lolos"),
                f"streak {int(row['streak'].iloc[0])} hari" if status else "kriteria belum terpenuhi",
                {"BARU": "#22c55e", "MASIH": "#3b82f6"}.get(status, "#64748b"))
            st.plotly_chart(charts.technical_chart(px, ticker, period), width="stretch")
            checks = [
                ("SMA20 di atas EMA50", m.get("sma20", 0) > m.get("ema50", 0)),
                ("MACD > 0 terus sejak entry", bool(m.get("trend_valid"))),
                ("MACD di atas garis 0", m.get("macd", 0) > 0),
                ("Lolos filter likuiditas", bool(m.get("is_liquid"))),
                ("Pola dasar (close>SMA20, MACD≥5%, trx<Rp50M)", bool(m.get("pola_dasar"))),
                ("⭐ Pola terbaik (+hist>0, ≥10% di atas SMA20)", bool(m.get("pola_terbaik"))),
                (f"Zona ideal {m.get('zone_score', 0)}/3", (m.get("zone_score") or 0) >= 2),
                ("Ada transaksi (bukan suspensi)", not m.get("suspended", False)),
            ]
            st.markdown(" ".join(f'<span class="chip {"baru" if ok else "keluar"}">{"✔" if ok else "✘"} {t}</span>'
                                 for t, ok in checks), unsafe_allow_html=True)
            st.caption("Harga dari Yahoo Finance (bisa tertunda). Indikator dihitung ulang di dashboard "
                       "dengan rumus yang sama dengan screener.")
    else:
        st.info("Pilih saham untuk melihat grafik.")

# ---------------------------------------------------------------- tab 3
with tab3:
    l, r = st.columns([1, 1], gap="large")
    with l:
        st.markdown(f"##### 🔴 Keluar dari daftar ({len(exited)})")
        if exited.empty:
            st.caption("Tidak ada saham yang keluar dibanding run sebelumnya.")
        else:
            st.caption(f"Lolos pada {prev_date:%d %b %Y}, tidak lolos pada {run_date:%d %b %Y} — "
                       "SMA20 turun ke bawah EMA50, MACD turun ke bawah 0, atau likuiditas turun.")
            ex = exited.assign(sector_label=exited["sector"].map(sector_label))
            st.dataframe(ex[["ticker", "name", "sector_label", "industry", "streak"]].rename(columns={
                "ticker": "Kode", "name": "Nama", "sector_label": "Sektor", "industry": "Industri",
                "streak": "Streak terakhir"}), hide_index=True, width="stretch")
    with r:
        st.markdown("##### 📅 Jumlah saham lolos per hari")
        st.plotly_chart(charts.history_chart(runs.head(60)), width="stretch")
    if n_all:
        st.markdown("##### 🔥 Streak terpanjang")
        top = res.sort_values(["streak", "avg_value_20d"], ascending=False).head(10)
        st.dataframe(style_table(display_table(top)), hide_index=True, width="stretch",
                     column_config=COLUMN_CONFIG)

# ---------------------------------------------------------------- tab 4
with tab4:
    st.markdown(f"""
**Masuk daftar (entry):**

1. **Golden cross** — SMA {CONFIG.sma_period} memotong ke atas EMA {CONFIG.ema_period}.
2. **MACD ({CONFIG.macd_fast},{CONFIG.macd_slow},{CONFIG.macd_signal})** — garis MACD **> 0**
   dalam **{CONFIG.cross_lookback} hari bursa** sejak golden cross (baru menembus 0 ⬆️ atau sudah di atas 0 ✅).

**Tetap di daftar — tanpa batas hari — selama:**
- SMA {CONFIG.sma_period} masih di atas EMA {CONFIG.ema_period}, **dan**
- MACD tidak pernah turun ke bawah 0 sejak entry, **dan**
- **Likuiditas** — rata-rata nilai transaksi {CONFIG.liquidity_window} hari ≥
   Rp{CONFIG.min_avg_value_idr/1e9:,.0f} miliar dan harga ≥ Rp{CONFIG.min_price:,.0f}.

**Status:**
- 🟢 **BARU** — lolos hari ini tetapi *tidak* lolos pada run sebelumnya.
- 🔵 **MASIH** — lolos hari ini *dan* pada run sebelumnya (kolom *Streak* = jumlah hari berturut-turut).
- 🔴 **KELUAR** — lolos pada run sebelumnya, tidak lolos hari ini.

Kolom *Umur tren* = jumlah hari bursa sejak golden cross. Gunakan slider di sidebar untuk
memfokuskan ke setup yang masih segar.

**Skor momentum per saham (ditambahkan Nov 2026, dari evaluasi 25 Sep – 13 Nov 2026):**
- **Pola dasar** — close di atas SMA20, MACD ≥ 5% dari harga, nilai transaksi < Rp50 M/hari.
- **⭐ Pola terbaik** — pola dasar + MACD histogram positif + close ≥ 10% di atas SMA20 + ada transaksi.
- **Zona ideal (0–3)** — close 15–40% di atas SMA20 · 25–40% di atas EMA50 · MACD 7–10% dari harga.
- **⛔ Suspensi** — volume 0 pada candle terakhir atau 2 dari 3 hari terakhir; dikeluarkan dari kandidat.

**Kondisi pasar (lampu):** HIJAU = 3 pemicu, KUNING = 2, MERAH = 0–1.
Pemicu: (1) IHSG di atas SMA20 & EMA50 dan MACD > 0; (2) jumlah saham lolos naik dibanding
{CONFIG.regime_breadth_days} hari bursa lalu; (3) ≥ {CONFIG.regime_min_best} saham pola terbaik.
Hasil uji: pola terbaik kena +10% dalam 3 minggu **61%** di fase naik, **16%** di fase crash (62% rugi ≥ 10%),
**24%** di fase pemulihan. Karena itu pola hanya dipakai saat lampu HIJAU/KUNING.

**Pengurutan:** sektor → industri → BARU dulu → nilai transaksi terbesar.
Klasifikasi sektor/industri dari Yahoo Finance, bisa ditimpa dengan IDX-IC lewat `data/sector_override.csv`.

*Bukan rekomendasi jual/beli. Data Yahoo Finance dapat tertunda atau tidak lengkap.*
""")
