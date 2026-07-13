import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta
import urllib.parse
import gc

# 【最高準則：網頁排版設定必須是全程式第一行】
st.set_page_config(page_title="股票缺口查詢系統", layout="wide")

# ==========================================
# 🔑 密碼設定區
# ==========================================
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

# -------------------------
# 智慧代號與名稱解析
# -------------------------
@st.cache_data(ttl=86400, max_entries=20, show_spinner=False)
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

@st.cache_data(ttl=86400, max_entries=20, show_spinner=False)
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

# -------------------------
# 核心運算邏輯
# -------------------------
def find_all_gaps(ticker_symbol, start_date, end_date, gap_type):
    # 執行前強迫清理記憶體
    gc.collect()
    
    stock_name = get_chinese_stock_name(ticker_symbol)
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = (end_date + timedelta(days=1)).strftime('%Y-%m-%d')
    
    # 抓取資料
    df = yf.download(ticker_symbol, start=start_str, end=end_str, auto_adjust=False, progress=False)
    
    if df.empty: 
        return pd.DataFrame(), 0, 0, stock_name, "", 0.0
    
    if isinstance(df.columns, pd.MultiIndex): 
        df.columns = [c[0] for c in df.columns]
        
    needed_cols = ['High', 'Low', 'Close', 'Volume']
    if not all(col in df.columns for col in needed_cols): 
        return pd.DataFrame(), len(df), 0, stock_name, "", 0.0
        
    # 輕量化：只保留需要的欄位並降階為 float32
    df = df[needed_cols].astype('float32')
    total_days = len(df)
    last_date = df.index[-1].strftime('%Y/%m/%d')
    last_close = round(float(df['Close'].iloc[-1]), 2)
    
    # 運算前日高低點
    df['Prev_High'] = df['High'].shift(1)
    df['Prev_Low'] = df['Low'].shift(1)
    
    all_gaps = []
    
    # 過濾出產生缺口的日子
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
        
    # 銷毀大變數並回收記憶體
    del df, target_gaps
    gc.collect()
    
    result_df = pd.DataFrame(all_gaps)
    if not result_df.empty:
        result_df = result_df.sort_values(by='缺口產生日期', ascending=False).reset_index(drop=True)
        
    return result_df, total_days, raw_gaps, stock_name, last_date, last_close

# -------------------------
# 網頁視覺介面
# -------------------------
if not check_password(): 
    st.stop()

st.title("📈 股票缺口自動篩選系統")
st.markdown("---")

# 設定預設時間區間：預設 5 年前，允許拉到 1980 年
min_allowed_date = datetime(1980, 1, 1)
max_allowed_date = datetime.today()
default_start_date = datetime.today() - timedelta(days=5*365)

col1, col2, col3, col4, col5 = st.columns(5)
with col1: 
    ticker_input = st.text_input("股票代號或名稱", value="", placeholder="輸入代號/名稱...")
with col2: 
    start_date = st.date_input("起始日期", value=default_start_date, min_value=min_allowed_date, max_value=max_allowed_date)
with col3: 
    end_date = st.date_input("結束日期", value=datetime.today(), min_value=min_allowed_date, max_value=max_allowed_date)
with col4: 
    gap_type = st.selectbox("缺口型態", ["下缺口", "上缺口"])
with col5: 
    status_type = st.selectbox("補缺狀態", ["未補", "已補", "全部"])

col_btn1, col_btn2 = st.columns([1, 9])
with col_btn1: 
    search_clicked = st.button("查詢", type="primary", use_container_width=True)
with col_btn2: 
    clear_clicked = st.button("清除畫面")

st.markdown("---")

# 清除畫面功能 (安全清除 session)
if clear_clicked:
    st.session_state.pop('search_results', None)
    st.session_state.pop('sys_info', None)
    st.session_state.pop('stock_info', None)
    gc.collect()
    st.rerun()

# 查詢功能
if search_clicked:
    if not ticker_input:
        st.warning("⚠️ 請輸入股票代號或名稱！")
    else:
        with st.spinner(f"正在搜尋並分析 {gap_type} 資料，請稍候..."):
            actual_ticker = resolve_ticker(ticker_input)
            
            market_type, ticker_try = "上市", f"{actual_ticker}.TW" 
            res_df, t_days, r_gaps, s_name, l_date, l_close = find_all_gaps(ticker_try, start_date, end_date, gap_type)
            
            # 若查無上市，自動查上櫃
            if t_days == 0:
                market_type, ticker_try = "上櫃", f"{actual_ticker}.TWO"
                res_df, t_days, r_gaps, s_name, l_date, l_close = find_all_gaps(ticker_try, start_date, end_date, gap_type)
                if t_days > 0: 
                    st.toast(f"已自動切換至上櫃股票", icon="🔄")
            
            if t_days > 0:
                # 紀錄系統訊息到 session
                st.session_state['stock_info'] = f"個股收盤資訊 **{actual_ticker} {s_name}** 收盤 **{l_close}** {l_date} {market_type}"
                st.session_state['sys_info'] = f"💡 系統資訊：共抓取到 {t_days} 天的歷史股價，這段期間共產生過 {r_gaps} 個 {gap_type}。"
                
                # 狀態篩選
                if not res_df.empty:
                    if status_type != "全部": 
                        res_df = res_df[res_df['補缺狀態'] == status_type]
                    st.session_state['search_results'] = res_df.copy()
                else:
                    st.session_state['search_results'] = pd.DataFrame()
                
                del res_df
                gc.collect()
            else:
                st.error(f"❌ 抓取失敗：無法解析「{ticker_input}」或查無歷史資料，請確認輸入是否正確。")
                st.session_state.pop('search_results', None)
                st.session_state.pop('sys_info', None)
                st.session_state.pop('stock_info', None)

# 渲染結果畫面 (線性渲染，避免前端節點錯誤)
if 'stock_info' in st.session_state:
    st.markdown(f"<div style='padding-top: 6px; font-size: 16px; color: #4F8BF9;'>{st.session_state['stock_info']}</div>", unsafe_allow_html=True)

if 'sys_info' in st.session_state:
    st.info(st.session_state['sys_info'])

if 'search_results' in st.session_state:
    df = st.session_state['search_results']
    if df.empty:
        st.warning(f"⚠️ 條件篩選結果：這段期間內沒有符合「{status_type}」狀態的 {gap_type}。")
    else:
        st.success(f"✅ 查詢成功！符合條件的缺口共 {len(df)} 筆。")
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        csv_data = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 下載報表 (CSV 檔案)",
            data=csv_data,
            file_name=f"股票缺口報表_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )