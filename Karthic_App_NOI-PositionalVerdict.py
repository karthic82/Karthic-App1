import streamlit as st
import pandas as pd
import requests
import datetime
import time
import os
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit.components.v1 as components

# --- 1. Database & Extreme CSS Optimization ---
st.set_page_config(page_title="NIFTY OI Command Center", layout="wide", initial_sidebar_state="collapsed")

DB_DIR = "nifty_db"
os.makedirs(DB_DIR, exist_ok=True)

st.markdown("""
    <style>
    /* Force true fullscreen, remove all extra streamlit padding */
    [data-testid="collapsedControl"] { display: none; }
    .block-container { padding: 0.2rem 0.5rem 0rem 0.5rem !important; max-width: 100% !important; overflow: hidden; }
    header, footer { visibility: hidden !important; height: 0px !important; margin: 0px !important; }
    .stApp { background-color: #0b0f19; color: #f1f5f9; }
    
    /* Panel Containers */
    .panel-box { background-color: #111827; padding: 6px 10px; border-radius: 6px; border: 1px solid #1f2937; margin-bottom: 4px; }
    
    /* Metrics */
    div[data-testid="stMetricValue"] { font-size: 1.05rem !important; font-weight: 700 !important; color: #f8fafc; }
    div[data-testid="stMetricLabel"] { font-size: 0.60rem !important; color: #94a3b8 !important; margin-bottom: -5px; text-transform: uppercase;}
    
    /* Force Radio buttons horizontally */
    div[data-testid="stRadio"] > div { display: flex; flex-direction: row; flex-wrap: nowrap; gap: 10px !important; }
    div[data-testid="stRadio"] label { font-size: 0.70rem !important; font-weight: 600; white-space: nowrap; }
    .stSelectbox label { font-size: 0.70rem !important; color: #94a3b8; display: none; }
    .stCheckbox label { font-size: 0.70rem !important; font-weight: 600; }
    .stMarkdown { margin-bottom: -15px; }
    
    /* Custom Tables */
    .action-table { width: 100%; text-align: center; border-collapse: collapse; font-size: 10px; }
    .action-table th { padding: 2px; border-bottom: 1px solid #334155; color: #94a3b8; font-weight: normal; }
    .action-table td { padding: 2px; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# --- 2. Session State Initializations ---
if "oi_snapshots" not in st.session_state: st.session_state.oi_snapshots = []
if "last_bias" not in st.session_state: st.session_state.last_bias = "NEUTRAL / RANGEBOUND"
if "symbol" not in st.session_state: st.session_state.symbol = "NIFTY"
if "last_fetch_time" not in st.session_state: st.session_state.last_fetch_time = None

# --- 3. NSE Scraper Engine ---
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Accept': 'application/json,text/plain,*/*', 'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.nseindia.com/option-chain', 'Connection': 'keep-alive'
}

@st.cache_data(ttl=60)
def fetch_nse_data(symbol="NIFTY"):
    session = requests.Session()
    try:
        session.get("https://www.nseindia.com", headers=headers, timeout=8)
        session.get("https://www.nseindia.com/option-chain", headers=headers, timeout=8)
        c_res = session.get(f"https://www.nseindia.com/api/option-chain-contract-info?symbol={symbol}", headers=headers, timeout=8)
        c_res.raise_for_status()
        expiries = c_res.json().get("expiryDates", [])
        if not expiries: return None, []
        chain_res = session.get(f"https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol={symbol}&expiry={expiries[0]}", headers=headers, timeout=8)
        chain_res.raise_for_status()
        return chain_res.json(), expiries
    except Exception: return None, []

def format_oi(num):
    if abs(num) >= 10000000: return f"{num/10000000:.2f}Cr"
    elif abs(num) >= 100000: return f"{num/100000:.2f}L"
    else: return f"{num:,.0f}"

# ==========================================
# 🟩 TOP ROW: CONTROLS & METRICS
# ==========================================
top_left, top_right = st.columns([1.2, 1])

with top_left:
    st.markdown("<div class='panel-box'>", unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns([1, 1.5, 1.5, 1])
    with c1: market_mode = st.radio("Mode", ["🟢 LIVE", "⏪ REPLAY"], horizontal=True, label_visibility="collapsed")
    with c2: symbol = st.selectbox("Symbol", ["NIFTY", "BANKNIFTY"], index=0 if st.session_state.symbol == "NIFTY" else 1, label_visibility="collapsed")
    st.session_state.symbol = symbol
    with c3: strike_filter = st.selectbox("Strikes", ["5", "8", "10", "15", "All"], index=2, label_visibility="collapsed")
    
    if market_mode == "🟢 LIVE":
        with c4: enable_audio = st.checkbox("🔊 Voice Alerts", value=True)
        st.markdown("<hr style='margin: 4px 0px; border-color: #1e293b;'>", unsafe_allow_html=True)
        rc1, rc2 = st.columns([4, 1])
        with rc1: timeframe = st.radio("Velocity Window", ["1 min", "3 min", "5 min", "10 min", "15 min", "30 min", "1 hr", "Full Day"], horizontal=True, index=1)
        with rc2: refresh_rate = st.selectbox("Refresh", ["1 min", "3 min", "Manual"], index=1, label_visibility="collapsed")
        
        raw_data, expiries = fetch_nse_data(symbol)
        if not raw_data: st.error("API Error. Retrying..."); st.stop()
        records = raw_data.get('records', {}).get('data', [])
        spot_price = float(raw_data.get('records', {}).get('underlyingValue', 0.0))
        if spot_price == 0.0:
            for row in records:
                for leg in ("CE", "PE"):
                    if row.get(leg, {}).get("underlyingValue", 0): spot_price = float(row.get(leg).get("underlyingValue")); break
                if spot_price: break
        selected_expiry = expiries[0] if expiries else None
        
        rows = [{'strike': int(i.get('strikePrice', 0)), 'ce_oi': int(i.get('CE', {}).get('openInterest', 0)), 'ce_coi_day': int(i.get('CE', {}).get('changeinOpenInterest', 0)), 'pe_oi': int(i.get('PE', {}).get('openInterest', 0)), 'pe_coi_day': int(i.get('PE', {}).get('changeinOpenInterest', 0))} for i in records if i.get("expiryDate") == selected_expiry or not i.get("expiryDate")]
        df_current = pd.DataFrame(rows).sort_values('strike').reset_index(drop=True)
        now = datetime.datetime.now()
        
        if not df_current.empty:
            file_path = os.path.join(DB_DIR, f"{symbol}_{now.strftime('%Y-%m-%d')}.csv")
            df_save = df_current.copy(); df_save['timestamp'] = now.strftime("%Y-%m-%d %H:%M:%S"); df_save['spot_price'] = spot_price
            if st.session_state.last_fetch_time != df_save['timestamp'].iloc[0][:16]:
                if os.path.exists(file_path): df_save.to_csv(file_path, mode='a', header=False, index=False)
                else: df_save.to_csv(file_path, index=False)
                st.session_state.last_fetch_time = df_save['timestamp'].iloc[0][:16]
            st.session_state.oi_snapshots.append((now, df_current.copy(), spot_price))
            st.session_state.oi_snapshots = st.session_state.oi_snapshots[-240:]

    else:
        refresh_rate, enable_audio = "Manual", False
        files = sorted([f for f in os.listdir(DB_DIR) if f.startswith(symbol) and f.endswith('.csv')], reverse=True)
        if not files: st.warning(f"No DB files for {symbol}. Run Live mode to build database."); st.stop()
        
        with c4: sel_date = st.selectbox("Date", [f.split('_')[1].split('.')[0] for f in files], label_visibility="collapsed")
        st.markdown("<hr style='margin: 4px 0px; border-color: #1e293b;'>", unsafe_allow_html=True)
        
        filepath = os.path.join(DB_DIR, f"{symbol}_{sel_date}.csv")
        hist_df = pd.read_csv(filepath); hist_df['timestamp'] = pd.to_datetime(hist_df['timestamp'])
        unique_times = hist_df['timestamp'].dt.strftime("%H:%M:%S").unique()
        
        rc1, rc2 = st.columns([3, 1])
        with rc1: timeframe = st.radio("Velocity Window", ["1 min", "3 min", "5 min", "10 min", "15 min", "30 min", "1 hr", "Full Day"], horizontal=True, index=1)
        with rc2: sel_time_str = st.select_slider("Time", options=unique_times, value=unique_times[-1], label_visibility="collapsed")
        
        target_dt = pd.to_datetime(f"{sel_date} {sel_time_str}")
        past_data = hist_df[hist_df['timestamp'] <= target_dt]
        st.session_state.oi_snapshots = [(ts, grp[['strike', 'ce_oi', 'ce_coi_day', 'pe_oi', 'pe_coi_day']].copy(), grp['spot_price'].iloc[0]) for ts, grp in past_data.groupby('timestamp')]
        df_current = past_data[past_data['timestamp'] == target_dt][['strike', 'ce_oi', 'ce_coi_day', 'pe_oi', 'pe_coi_day']].copy()
        spot_price, now = past_data[past_data['timestamp'] == target_dt]['spot_price'].iloc[0], target_dt

    st.markdown("</div>", unsafe_allow_html=True)

# Data Processing Engine
df_display = df_current.copy()
prev_spot = None
if timeframe != "Full Day" and len(st.session_state.oi_snapshots) > 1:
    m_map = {"1 min": 1, "3 min": 3, "5 min": 5, "10 min": 10, "15 min": 15, "30 min": 30, "1 hr": 60}
    tgt_time = now - datetime.timedelta(minutes=m_map.get(timeframe, 3))
    closest = min(st.session_state.oi_snapshots, key=lambda x: abs(x[0] - tgt_time))
    prev_spot = closest[2]
    merged = pd.merge(df_display, closest[1], on='strike', suffixes=('', '_prev'))
    df_display['ce_coi'], df_display['pe_coi'] = merged['ce_oi'] - merged['ce_oi_prev'], merged['pe_oi'] - merged['pe_oi_prev']
else: 
    df_display['ce_coi'], df_display['pe_coi'] = df_display['ce_coi_day'], df_display['pe_coi_day']

step = 50 if symbol == "NIFTY" else 100; atm_strike = int(round(spot_price / step) * step)
if strike_filter != "All": df_display = df_display[abs(df_display['strike'] - atm_strike) <= (int(strike_filter) * step)]

p_dict = {ts: sum(max(0, ts - r['strike']) * r['ce_oi'] + max(0, r['strike'] - ts) * r['pe_oi'] for _, r in df_display.iterrows()) for ts in df_display['strike'].tolist()}
max_pain = min(p_dict, key=p_dict.get) if p_dict else atm_strike
res_strike = df_display.loc[df_display['ce_oi'].idxmax()]['strike'] if not df_display.empty else 0
sup_strike = df_display.loc[df_display['pe_oi'].idxmax()]['strike'] if not df_display.empty else 0

t_ce, t_pe = df_display['ce_oi'].sum(), df_display['pe_oi'].sum()
tc_coi, tp_coi = df_display['ce_coi'].sum(), df_display['pe_coi'].sum()
n_coi = tp_coi - tc_coi; pcr = t_pe / t_ce if t_ce > 0 else 1.0

if n_coi > 25000 and pcr >= 1.0: sig, bd = "BULLISH (Put Writing)", "Long Buildup"
elif n_coi < -25000 and pcr < 1.0: sig, bd = "BEARISH (Call Writing)", "Short Buildup"
elif tc_coi < 0 and tp_coi >= 0: sig, bd = "SHORT COVERING", "Bulls Squeezing"
elif tp_coi < 0 and tc_coi >= 0: sig, bd = "LONG UNWINDING", "Bears Breaking"
else: sig, bd = "NEUTRAL / RANGEBOUND", "Straddle Writing"

if enable_audio and sig != st.session_state.last_bias:
    components.html(f"""<script>var m=new SpeechSynthesisUtterance("Alert. Bias shifted to {sig.split('(')[0].strip()}");window.speechSynthesis.speak(m);</script>""", height=0, width=0)
    st.session_state.last_bias = sig

with top_right:
    st.markdown("<div class='panel-box'>", unsafe_allow_html=True)
    m1, m2, m3 = st.columns(3)
    m1.metric("Spot Price", f"{spot_price:,.2f}", f"ATM: {atm_strike}")
    m2.metric("Max Pain", f"{max_pain}", f"Shift: {max_pain - atm_strike:+d}")
    m3.metric("Intraday Bias", sig, f"PCR: {pcr:.2f}")
    m4, m5 = st.columns([1, 2])
    m4.metric("Walls (Sup/Res)", f"{sup_strike} | {res_strike}", f"Flow: {format_oi(n_coi)}")
    m5.metric("Market Regime", bd, f"{timeframe} Window | {now.strftime('%H:%M:%S')}")
    st.markdown("</div>", unsafe_allow_html=True)

# ==========================================
# 🟦 MIDDLE ROW: SPLIT GRID LAYOUT
# ==========================================
bot_left, bot_mid, bot_right = st.columns([3.3, 1.7, 5.0])
chart_bg = dict(plot_bgcolor='#0b0f19', paper_bgcolor='#0b0f19', font=dict(color='#94a3b8', size=10), yaxis=dict(gridcolor='#1e293b'))

with bot_left:
    st.markdown("<div class='panel-box'>", unsafe_allow_html=True)
    st.markdown("<p style='font-size:11px; font-weight:700; color:#38bdf8; margin: 0;'>📊 TOTAL OPEN INTEREST</p>", unsafe_allow_html=True)
    fig_tot = go.Figure()
    fig_tot.add_trace(go.Bar(x=df_display['strike'], y=df_display['ce_oi'], name='Call OI', marker_color='#ef4444'))
    fig_tot.add_trace(go.Bar(x=df_display['strike'], y=df_display['pe_oi'], name='Put OI', marker_color='#22c55e'))
    fig_tot.add_vline(x=spot_price, line_dash="dash", line_color="#38bdf8"); fig_tot.add_vline(x=max_pain, line_dash="dot", line_color="#facc15")
    fig_tot.update_layout(**chart_bg, margin=dict(l=5, r=5, t=15, b=5), height=155, barmode='group', legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1.0), xaxis=dict(tickmode='array', tickvals=df_display['strike'], tickangle=-45))
    st.plotly_chart(fig_tot, use_container_width=True, config={'displayModeBar': False}, key="c_tot")
    
    st.markdown(f"<p style='font-size:11px; font-weight:700; color:#facc15; margin-top:5px; margin-bottom: 0;'>⚡ VELOCITY CHANGE ({timeframe})</p>", unsafe_allow_html=True)
    fig_coi = go.Figure()
    fig_coi.add_trace(go.Bar(x=df_display['strike'], y=df_display['ce_coi'], name='Call ΔOI', marker_color='#f87171'))
    fig_coi.add_trace(go.Bar(x=df_display['strike'], y=df_display['pe_coi'], name='Put ΔOI', marker_color='#4ade80'))
    fig_coi.add_vline(x=spot_price, line_dash="dash", line_color="#38bdf8"); fig_coi.add_vline(x=max_pain, line_dash="dot", line_color="#facc15")
    fig_coi.update_layout(**chart_bg, margin=dict(l=5, r=5, t=15, b=5), height=155, barmode='group', legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1.0), xaxis=dict(tickmode='array', tickvals=df_display['strike'], tickangle=-45))
    st.plotly_chart(fig_coi, use_container_width=True, config={'displayModeBar': False}, key="c_coi")
    st.markdown("</div>", unsafe_allow_html=True)

with bot_mid:
    st.markdown("<div class='panel-box' style='height: 98%; padding-top: 10px;'>", unsafe_allow_html=True)
    bm1, bm2 = st.columns(2)
    with bm1:
        st.markdown(f"<p style='font-size:10px; color:#94a3b8; text-align:center; margin-bottom: 0;'><b>Net Flow ({timeframe})</b></p>", unsafe_allow_html=True)
        f_b1 = go.Figure(data=[go.Bar(x=['CE Δ', 'PE Δ'], y=[tc_coi, tp_coi], marker_color=['#ef4444', '#22c55e'], text=[format_oi(tc_coi), format_oi(tp_coi)], textposition='auto', textfont=dict(color='white'))])
        f_b1.update_layout(height=320, margin=dict(l=0, r=0, t=5, b=15), plot_bgcolor='#0b0f19', paper_bgcolor='#0b0f19', showlegend=False)
        st.plotly_chart(f_b1, use_container_width=True, config={'displayModeBar': False}, key="b_flo")
    with bm2:
        st.markdown(f"<p style='font-size:10px; color:#94a3b8; text-align:center; margin-bottom: 0;'><b>Total Chain OI</b></p>", unsafe_allow_html=True)
        f_b2 = go.Figure(data=[go.Bar(x=['Tot CE', 'Tot PE'], y=[t_ce, t_pe], marker_color=['#ef4444', '#22c55e'], text=[format_oi(t_ce), format_oi(t_pe)], textposition='auto', textfont=dict(color='white'))])
        f_b2.update_layout(height=320, margin=dict(l=0, r=0, t=5, b=15), plot_bgcolor='#0b0f19', paper_bgcolor='#0b0f19', showlegend=False)
        st.plotly_chart(f_b2, use_container_width=True, config={'displayModeBar': False}, key="b_tot")
    st.markdown("</div>", unsafe_allow_html=True)

with bot_right:
    st.markdown("<div class='panel-box'>", unsafe_allow_html=True)
    
    # Extract Net Flows for multi-timeframe alignment
    mtf_flows = {}
    flow_states = {}
    
    for m in [3, 5, 15, 30, 60]:
        if len(st.session_state.oi_snapshots) > 1:
            tgt = now - datetime.timedelta(minutes=m); snp = min(st.session_state.oi_snapshots, key=lambda x: abs(x[0] - tgt))
            tm = pd.merge(df_current, snp[1], on='strike', suffixes=('', '_prev'))
            if strike_filter != "All": tm = tm[abs(tm['strike'] - atm_strike) <= (int(strike_filter) * step)]
            cv, pv = (tm['ce_oi'] - tm['ce_oi_prev']).sum(), (tm['pe_oi'] - tm['pe_oi_prev']).sum()
        else: cv, pv = 0, 0
        net_f = pv - cv
        mtf_flows[f"{m}m"] = net_f
        flow_states[f"{m}m"] = net_f > 0
    
    total_ce_coi_day, total_pe_coi_day = df_display['ce_coi_day'].sum(), df_display['pe_coi_day'].sum()
    day_net = total_pe_coi_day - total_ce_coi_day
    mtf_flows["1D"] = day_net
    flow_states["1D"] = day_net > 0
    day_coi_pcr = (total_pe_coi_day/total_ce_coi_day) if total_ce_coi_day>0 else (9.9 if total_pe_coi_day>0 else 1.0)

    # 8-Column Grid for Donuts + Netflow Metrics
    d_cols = st.columns([1.4, 1.4, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9])
    
    with d_cols[0]:
        st.markdown(f"<div style='text-align:center; line-height:1.2; margin-bottom: 2px;'><span style='font-size:11px; color:#94a3b8; font-weight:bold;'>Cum. Ratio</span></div>", unsafe_allow_html=True)
        f_b3 = go.Figure(data=[go.Pie(labels=['Call', 'Put'], values=[max(t_ce, 1), max(t_pe, 1)], hole=0.6, marker_colors=['#ef4444', '#22c55e'], textinfo='percent', textposition='inside', textfont=dict(color='white', size=11))])
        f_b3.update_layout(height=110, margin=dict(l=0, r=0, t=0, b=0), showlegend=False, paper_bgcolor='#0b0f19', plot_bgcolor='#0b0f19', annotations=[dict(text=f"<b>{pcr:.2f}</b><br><span style='font-size:8px;'>{sig.split()[0]}</span>", x=0.5, y=0.5, font_size=15, font_color="white", showarrow=False)])
        st.plotly_chart(f_b3, use_container_width=True, config={'displayModeBar': False}, key="p_tot")
    
    with d_cols[1]:
        d_txt = "Bull" if day_coi_pcr>1.0 else "Bear" if day_coi_pcr<1.0 else "Neutral"
        st.markdown(f"<div style='text-align:center; line-height:1.2; margin-bottom: 2px;'><span style='font-size:11px; color:#38bdf8; font-weight:bold;'>Day COI</span></div>", unsafe_allow_html=True)
        f_dc = go.Figure(data=[go.Pie(labels=['C', 'P'], values=[abs(total_ce_coi_day) if total_ce_coi_day!=0 else 1, abs(total_pe_coi_day) if total_pe_coi_day!=0 else 1], hole=0.6, marker_colors=['#f87171', '#4ade80'], textinfo='percent', textposition='inside', textfont=dict(color='white', size=11))])
        f_dc.update_layout(height=110, margin=dict(l=0, r=0, t=0, b=0), showlegend=False, paper_bgcolor='#0b0f19', plot_bgcolor='#0b0f19', annotations=[dict(text=f"<b>{day_coi_pcr:.2f}</b><br><span style='font-size:8px;'>{d_txt}</span>", x=0.5, y=0.5, font_size=15, font_color="white", showarrow=False)])
        st.plotly_chart(f_dc, use_container_width=True, config={'displayModeBar': False}, key="d_dcoi")

    # Compact & Leveled Net Flow Metric Boxes
    for col, (label, val) in zip(d_cols[2:], mtf_flows.items()):
        with col:
            color = "#4ade80" if val > 0 else "#f87171" if val < 0 else "#94a3b8"
            sign = "+" if val > 0 else ""
            txt_bias = "Bullish" if val > 0 else "Bearish" if val < 0 else "Neutral"
            html = f"""
            <div style='background-color:#0f172a; border:1px solid #1e293b; border-radius:4px; padding:6px 2px; text-align:center; height:110px; display:flex; flex-direction:column; justify-content:center;'>
                <span style='font-size:10px; color:#facc15; font-weight:bold; white-space:nowrap;'>Net ({label})</span>
                <span style='font-size:12px; color:{color}; font-weight:bold; margin-top:8px; white-space:nowrap;'>{sign}{format_oi(val)}</span>
                <span style='font-size:9px; color:{color}; opacity:0.85; margin-top:4px;'>{txt_bias}</span>
            </div>
            """
            st.markdown(html, unsafe_allow_html=True)
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    st.markdown("<div class='panel-box'>", unsafe_allow_html=True)
    st.markdown("<p style='font-size:11px; font-weight:700; margin: 0; color:#c084fc;'>📈 DIVERGENCE EDGE: Spot vs. Net Flow</p>", unsafe_allow_html=True)
    div_t, div_s, div_f = [], [], []
    for s in st.session_state.oi_snapshots: div_t.append(s[0]); div_s.append(s[2]); div_f.append(s[1]['pe_coi_day'].sum() - s[1]['ce_coi_day'].sum())
    fig_div = make_subplots(specs=[[{"secondary_y": True}]])
    if div_t:
        fig_div.add_trace(go.Scatter(x=div_t, y=div_s, name="Spot", line=dict(color="#38bdf8", width=2)), secondary_y=False)
        fig_div.add_trace(go.Scatter(x=div_t, y=div_f, name="Flow", fill='tozeroy', fillcolor='rgba(250,204,21,0.1)', line=dict(color="#facc15", width=1.5)), secondary_y=True)
    
    # Strictly lock X-Axis from 9:15 AM to 4:00 PM
    start_dt = now.replace(hour=9, minute=15, second=0, microsecond=0)
    end_dt = now.replace(hour=16, minute=0, second=0, microsecond=0)
    
    fig_div.update_layout(plot_bgcolor='#0b0f19', paper_bgcolor='#0b0f19', font=dict(color='#94a3b8', size=10), margin=dict(l=10, r=10, t=10, b=10), height=165, legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1.0))
    fig_div.update_xaxes(range=[start_dt, end_dt], tickformat="%H:%M", showgrid=True, gridcolor='#1e293b')
    fig_div.update_yaxes(title_text="Spot", secondary_y=False, showgrid=False)
    fig_div.update_yaxes(title_text="Flow", secondary_y=True, showgrid=False)
    st.plotly_chart(fig_div, use_container_width=True, config={'displayModeBar': False}, key="c_div")
    st.markdown("</div>", unsafe_allow_html=True)

# ==========================================
# 🟪 BOTTOM ROW: NTM STRIKE ACTION & PRO TRADER INSIGHT
# ==========================================
st.markdown("<div class='panel-box'>", unsafe_allow_html=True)
ntm_strikes = sorted(df_display['strike'].tolist(), key=lambda x: abs(x - spot_price))[:5]
ntm_strikes.sort()

spot_chg = 0
if prev_spot is not None: spot_chg = spot_price - prev_spot
if abs(spot_chg) < 0.5: spot_chg = 0

def get_action(coi, is_ce):
    if coi == 0: return "Neutral", "#64748b"
    if spot_chg > 0: return ("Long Buildup", "#22c55e") if coi > 0 else ("Short Covering", "#facc15") if is_ce else ("Short Buildup", "#ef4444") if coi > 0 else ("Long Unwinding", "#f97316")
    elif spot_chg < 0: return ("Short Buildup", "#ef4444") if coi > 0 else ("Long Unwinding", "#f97316") if is_ce else ("Long Buildup", "#22c55e") if coi > 0 else ("Short Covering", "#facc15")
    else: return ("Buildup", "#38bdf8") if coi > 0 else ("Unwinding", "#c084fc")

table_html = "<table class='action-table'><tr><th>Call Action</th><th>Strike</th><th>Put Action</th></tr>"
for strk in ntm_strikes:
    row = df_display[df_display['strike'] == strk].iloc[0]
    ce_a, ce_c = get_action(row['ce_coi'], True); pe_a, pe_c = get_action(row['pe_coi'], False)
    bg = "background-color: #1e293b;" if strk == atm_strike else ""
    table_html += f"<tr style='{bg}'><td style='color:{ce_c}'>{ce_a}</td><td style='color:#fff;'>{strk}</td><td style='color:{pe_c}'>{pe_a}</td></tr>"
table_html += "</table>"

# --- TIMEFRAME ALIGNMENT ALGORITHM (AI INSIGHT) ---
all_bull = all(flow_states.values())
all_bear = not any(flow_states.values())

macro_bull = flow_states["1D"] and flow_states["60m"] and flow_states["30m"] and flow_states["15m"]
macro_bear = not flow_states["1D"] and not flow_states["60m"] and not flow_states["30m"] and not flow_states["15m"]

micro_bull = flow_states["3m"] and flow_states["5m"]
micro_bear = not flow_states["3m"] and not flow_states["5m"]

expert_verdict, user_action, my_action = "", "", ""

if all_bull:
    expert_verdict = "🟢 ALL-CLEAR TREND DAY (BULLISH): Every timeframe from 3m to 1D is showing positive Put writing flow. Buyers are in total control."
    user_action = "Aggressive sizing. Buy every dip. Hold winners longer. Do not attempt to short."
    my_action = f"Riding directional longs. Scaling into Call options or Futures. Trailing stop-loss just below {sup_strike}."
elif all_bear:
    expert_verdict = "🔴 ALL-CLEAR TREND DAY (BEARISH): Every timeframe from 3m to 1D is showing negative Call writing flow. Sellers are in total control."
    user_action = "Aggressive sizing. Sell every rip. Hold winners longer. Do not attempt to buy."
    my_action = f"Riding directional shorts. Scaling into Put options or short Futures. Trailing stop-loss just above {res_strike}."
elif macro_bull and micro_bear:
    expert_verdict = "🟡 THE 'BUY THE DIP' TRAP: The macro trend (15m to 1D) is Bullish, but micro momentum (3m, 5m) is pulling back. This is a mechanical trap."
    user_action = "Wait for the 3m/5m flow to turn Green again, then enter long. Do not short the pullback."
    my_action = f"Placing limit buy orders near {sup_strike}. Waiting for micro flow alignment to pull the trigger."
elif macro_bear and micro_bull:
    expert_verdict = "🟠 THE 'SELL THE RIP' TRAP: The macro trend (15m to 1D) is Bearish, but micro momentum (3m, 5m) is spiking. This is a dead-cat bounce."
    user_action = "Wait for the 3m/5m flow to turn Red again, then enter short. Do not buy the breakout."
    my_action = f"Placing limit sell orders near {res_strike}. Waiting for micro flow alignment to execute shorts."
elif flow_states["15m"] != flow_states["60m"] or flow_states["30m"] != flow_states["1D"]:
    expert_verdict = f"⚪ CHOP ZONE (DIVERGENCE): The intraday trend is fighting the daily structural trend. Market is trapped between {sup_strike} and {res_strike}."
    user_action = "Reduce position sizing. Scalp strictly from support to resistance. Do not hold for big targets."
    my_action = f"Deploying Iron Condors or Strangles to farm theta decay. Taking quick 10-15 point scalps on extreme edges."
else:
    if flow_states["1D"] and flow_states["3m"]:
        expert_verdict = f"Moderate Bullish Continuation. Macro is Bullish and current 3m momentum aligns."
        user_action = f"Focus on 'Buy on Dips' near the {atm_strike} or {sup_strike} zones."
        my_action = f"Deploying Short Put Spreads to collect premium. Holding directional longs."
    elif not flow_states["1D"] and not flow_states["3m"]:
        expert_verdict = f"Moderate Bearish Continuation. Macro is Bearish and current 3m momentum aligns."
        user_action = f"Focus on 'Sell on Rise' opportunities near {res_strike}."
        my_action = f"Holding Short Call Spreads and initiating short scalps on pullbacks."
    else:
        expert_verdict = f"Mixed Flow. Macro and Micro are out of sync. Waiting for timeframe alignment."
        user_action = "Stay cautious. Wait for 15m and 3m to align before committing size."
        my_action = "Sitting on hands. Preserving capital until a high-probability alignment occurs."

insight_html = f"""
<div style='background-color:#0f172a; padding:8px 12px; border-radius:6px; font-size:11px; color:#f8fafc; border-left:4px solid #c084fc; height:100%;'>
    <div style='margin-bottom:4px;'><span style='color:#c084fc; font-weight:bold;'>🧑‍💼 TRADER'S VERDICT:</span> {expert_verdict}</div>
    <div style='margin-bottom:4px;'><span style='color:#38bdf8; font-weight:bold;'>💡 YOUR PLAY:</span> {user_action}</div>
    <div><span style='color:#facc15; font-weight:bold;'>🎯 MY PLAY:</span> {my_action}</div>
</div>
"""

ac1, ac2 = st.columns([1.1, 1.9])
with ac1: st.markdown(table_html, unsafe_allow_html=True)
with ac2: st.markdown(insight_html, unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

if market_mode == "🟢 LIVE" and refresh_rate != "Manual":
    time.sleep(60 if refresh_rate == "1 min" else 180)
    st.cache_data.clear(); st.rerun()