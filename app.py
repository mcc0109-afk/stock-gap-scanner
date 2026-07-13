import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta
import urllib.parse
import gc

# 【最高準則：網頁排版設定必須是全程式第一行】
st.set_page_config(page_title="股票缺口查詢系統", layout="wide")

APP_PASSWORD = "1788" 

def check_password():
    if st.session_state.get("password_correct", False):
        return True
    st.title("🔒 系統已鎖定")
    st.info("此為私人專屬的股票缺口運算伺服器，請輸入密碼以解鎖使用。")
    password = st.text_input("請輸入密碼：", type="password")
    if password:
        if password == APP_PASSWORD:
            st.session_state["password_correct"] = True
            st.rerun() 
        else:
            st.error("❌ 密碼錯誤，請重新輸入。")
    return False

def resolve_ticker(user_input):
    user_input = str(user_input).strip()
    if user_input.isdigit(): return user_input
    try:
        url = f"https://tw.stock.yahoo.com/_td-stock/api/resource/AutocompleteService;limit=5;query={urllib.parse.quote(user_input)}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5).json()
        for item in res.get('ResultSet', {}).get('Result', []):
            if item.get('symbol', '').endswith(('.TW', '.TWO')):
                return item['symbol'].split('.')[0]
    except: pass
    return user_input

def get_chinese_stock_name(ticker_symbol):
    clean_ticker = ticker_symbol.split('.')[0]
    try:
        url = f"https://tw.stock.yahoo.com/_td-stock/api/resource/AutocompleteService;limit=5;query={clean_ticker}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5).json()
        for item in res.get('ResultSet', {}).get('Result', []):
            if item.get('symbol', '').startswith(clean_ticker):
                return item.get('name', '未知名稱')
    except: pass
    return '未知名稱'

def find_all_gaps(ticker_symbol, start_date, end_date, gap_type):
    gc.collect() # 執行前先強迫清理記憶體
    
    stock_name = get_chinese_stock_name(ticker_symbol)
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = (end_date + timedelta(days=1)).strftime('%Y-%m-%d')
    
    # 載入資料
    df = yf.download(ticker_symbol, start=start_str, end=end_str, auto_adjust=False, progress=False)
    if df.empty: return pd.DataFrame(), 0, 0, stock_name, "", 0.0
    if isinstance(df.columns, pd.MultiIndex): df.columns = [c[0] for c in df.columns]
    
    needed_cols = ['High', 'Low', 'Close', 'Volume']
    if not all(col in df.columns for col in needed_cols): return pd.DataFrame(), len(df), 0, stock_name, "", 0.0
    
    # 極度輕量化：只取需要的欄位並降階為 float32
    df = df[needed_cols].astype('float32')
    total_days = len(df)
    last_date = df.index[-1].strftime('%Y/%m/%d')
    last_close = round(float(df['Close'].iloc[-1]), 2)
    
    # 向量化運算前日高低點
    df['Prev_High'] = df['High'].shift(1)
    df['Prev_Low'] = df['Low'].shift(1)
    
    all_gaps = []
    
    # 向量化篩選：只抓出真正發生缺口的那幾天 (避開無效的迴圈)
    if gap_type == "下缺口":
        target_gaps = df[df['High'] < df['Prev_Low']].copy()
    else:
        target_gaps = df[df['Low'] > df['Prev_High']].copy()
        
    raw_gaps = len(target_gaps)
    
    for gap_date, row in target_gaps.iterrows():
        future_df = df.loc[gap_date:].iloc[1:]
        target_price = float(row['Prev_Low'] if gap_type == "下缺口" else row['Prev_High'])
        
        is_filled = False
        fill_date = "-"
        
        if not future_df.empty:
            if gap_type == "下缺口":
                fill_candidates = future_df[future_df['High'] >= target_price]
            else:
                fill_candidates = future_df[future_df['Low'] <= target_price]
                
            if not fill_candidates.empty:
                is_filled = True
                fill_date = fill_candidates.index[0].strftime('%Y/%m/%d')
                
        all_gaps.append({
            '股票代號': ticker_symbol.split('.')[0],
            '股票名稱': stock_name,
            '缺口型態': gap_type,
            '缺口產生日期': gap_date.strftime('%Y/%m/%d'),
            '需回補價格': round(target_price, 2), 
            '補缺狀態': '已補' if is_filled else '未補',
            '回補日期': fill_date,
            '缺口日成交量': f"{int(row['Volume']):,}" 
        })
        
    del df, target_gaps
    gc.collect()
    
    result_df = pd.DataFrame(all_gaps)
    if not result_df.empty:
        result_df = result_df.sort_values(by='缺口產生日期', ascending=False).reset_index(drop=True)
        
    return result_df, total_days, raw_gaps, stock_name, last_date, last_close

# -------------------------
# 網頁視覺介面
# -------------------------
if not check_password(): st.stop()

st.title("📈 股票缺口自動篩選系統")
st.markdown("---")

col1, col2, col3, col4, col5 = st.columns(5)
with col1: ticker_input = st.text_input("股票代號或名稱", value="", placeholder="請輸入代號或名稱...")
with col2: start_date = st.date_input("起始日期", value=datetime.today() - timedelta(days=3*365), min_value=datetime(1980, 1, 1), max_value=datetime.today())
with col3: end_date = st.date_input("結束日期", value=datetime.today(), min_value=datetime(1980, 1, 1), max_value=datetime.today())
with col4: gap_type = st.selectbox("缺口型態", ["下缺口", "上缺口"])
with col5: status_type = st.selectbox("補缺狀態", ["未補", "已補", "全部"])

btn_col1, btn_col2, info_col = st.columns([1, 1.2, 7.8])
with btn_col1: search_clicked = st.button("查詢", type="primary")
with btn_col2: clear_clicked = st.button("清除畫面")
info_placeholder = info_col.empty()
st.markdown("---")

if clear_clicked:
    for key in ['current_df', 'info_html', 'sys_info']:
        if key in st.session_state: del st.session_state[key]
    gc.collect()
    st.rerun()

if search_clicked:
    if not ticker_input:
        st.warning("⚠️ 請輸入股票代號或名稱！")
    else:
        with st.spinner(f"正在搜尋並分析 {gap_type} 資料，請稍候..."):
            actual_ticker = resolve_ticker(ticker_input)
            market_type, ticker_try = "上市", f"{actual_ticker}.TW" 
            res_df, t_days, r_gaps, s_name, l_date, l_close = find_all_gaps(ticker_try, start_date, end_date, gap_type)
            
            if t_days == 0:
                market_type, ticker_try = "上櫃", f"{actual_ticker}.TWO"
                res_df, t_days, r_gaps, s_name, l_date, l_close = find_all_gaps(ticker_try, start_date, end_date, gap_type)
                if t_days > 0: st.toast(f"已自動切換至上櫃股票", icon="🔄")
            
            if t_days > 0:
                st.session_state.info_html = f"<div style='padding-top: 6px; font-size: 16px; color: #4F8BF9;'>個股收盤資訊 **{actual_ticker} {s_name}** 收盤 **{l_close}** {l_date} {market_type}</div>"
                st.session_state.sys_info = f"💡 系統資訊：共抓取到 {t_days} 天的歷史股價，這段期間共產生過 {r_gaps} 個 {gap_type}。"
                
                if not res_df.empty:
                    if status_type != "全部": res_df = res_df[res_df['補缺狀態'] == status_type]
                    st.session_state.current_df = res_df.copy()
                else:
                    st.session_state.current_df = pd.DataFrame()
                
                del res_df
                gc.collect()
            else:
                st.error(f"❌ 抓取失敗：無法解析「{ticker_input}」或查無歷史資料，請確認輸入是否正確。")
                st.session_state.current_df = None

if st.session_state.get('info_html'): info_placeholder.markdown(st.session_state.info_html, unsafe_allow_html=True)
if st.session_state.get('sys_info'): st.info(st.session_state.sys_info)

if st.session_state.get('current_df') is not None:
    df = st.session_state.current_df
    if df.empty:
        st.warning(f"⚠️ 條件篩選結果：這段期間內沒有符合狀態的 {gap_type}。")
    else:
        st.success(f"✅ 查詢成功！共 {len(df)} 筆。")
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button("📥 下載報表 (CSV 檔案)", data=df.to_csv(index=False).encode('utf-8-sig'), file_name=f"股票缺口報表.csv", mime="text/csv")