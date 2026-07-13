import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta
import urllib.parse
import gc

# ==========================================
# 🔑 密碼設定區 (您可以在這裡隨時修改密碼)
# ==========================================
APP_PASSWORD = "1788" 

# -------------------------
# 密碼驗證系統
# -------------------------
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
# 智慧代號解析 (24小時快取)
# -------------------------
@st.cache_data(ttl=86400, show_spinner=False)
def resolve_ticker(user_input):
    user_input = str(user_input).strip()
    if user_input.isdigit():
        return user_input
        
    try:
        encoded_input = urllib.parse.quote(user_input)
        url = f"https://tw.stock.yahoo.com/_td-stock/api/resource/AutocompleteService;limit=5;query={encoded_input}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=5)
        data = response.json() 
        
        if 'ResultSet' in data and 'Result' in data['ResultSet']:
            for item in data['ResultSet']['Result']:
                symbol = item.get('symbol', '')
                if symbol.endswith('.TW') or symbol.endswith('.TWO'):
                    return symbol.split('.')[0]
    except:
        pass
    return user_input

# -------------------------
# 從 API 抓取乾淨的中文名稱 (24小時快取)
# -------------------------
@st.cache_data(ttl=86400, show_spinner=False)
def get_chinese_stock_name(ticker_symbol):
    clean_ticker = ticker_symbol.split('.')[0]
    try:
        url = f"https://tw.stock.yahoo.com/_td-stock/api/resource/AutocompleteService;limit=5;query={clean_ticker}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=5)
        data = response.json()
        
        if 'ResultSet' in data and 'Result' in data['ResultSet']:
            for item in data['ResultSet']['Result']:
                symbol = item.get('symbol', '')
                if symbol.startswith(clean_ticker):
                    return item.get('name', '未知名稱')
    except:
        pass
    return '未知名稱'

# -------------------------
# 核心運算邏輯 (30分鐘快取 + 極致記憶體優化)
# -------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def find_all_gaps(ticker_symbol, start_date, end_date, gap_type):
    stock_name = get_chinese_stock_name(ticker_symbol)
    start_str = start_date.strftime('%Y-%m-%d')
    end_date_plus_1 = end_date + timedelta(days=1)
    end_str = end_date_plus_1.strftime('%Y-%m-%d')
    
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    
    stock_data = yf.download(ticker_symbol, start=start_str, end=end_str, auto_adjust=False, session=session, progress=False)
    
    if stock_data.empty:
        return pd.DataFrame(), 0, 0, stock_name, "", 0.0

    if isinstance(stock_data.columns, pd.MultiIndex):
        stock_data.columns = [col[0] for col in stock_data.columns]

    for col in ['High', 'Low', 'Close', 'Volume']:
        if col not in stock_data.columns:
            return pd.DataFrame(), len(stock_data), 0, stock_name, "", 0.0
            
    # 【記憶體優化】降轉為 float32，節省 50% RAM
    for col in ['High', 'Low', 'Close', 'Volume']:
        stock_data[col] = stock_data[col].astype('float32')
    
    last_date = stock_data.index[-1].strftime('%Y/%m/%d')
    last_close = round(float(stock_data['Close'].iloc[-1]), 2)
    
    stock_data['Prev_High'] = stock_data['High'].shift(1)
    stock_data['Prev_Low'] = stock_data['Low'].shift(1)
    
    all_gaps = []
    
    if gap_type == "下缺口":
        target_gaps = stock_data[stock_data['High'] < stock_data['Prev_Low']].copy()
    else:
        target_gaps = stock_data[stock_data['Low'] > stock_data['Prev_High']].copy()
        
    for gap_date, row in target_gaps.iterrows():
        future_data = stock_data.loc[gap_date:].iloc[1:] 
        is_filled = False
        fill_date = "-" 
        
        if gap_type == "下缺口":
            target_price = float(row['Prev_Low']) 
            if not future_data.empty:
                fill_candidates = future_data[future_data['High'] >= target_price]
                if not fill_candidates.empty:
                    is_filled = True
                    fill_date = fill_candidates.index[0].strftime('%Y/%m/%d')
        else:
            target_price = float(row['Prev_High']) 
            if not future_data.empty:
                fill_candidates = future_data[future_data['Low'] <= target_price]
                if not fill_candidates.empty:
                    is_filled = True
                    fill_date = fill_candidates.index[0].strftime('%Y/%m/%d')
                    
        vol_val = float(row['Volume'])
        
        all_gaps.append({
            '股票代號': ticker_symbol.split('.')[0],
            '股票名稱': stock_name,
            '缺口型態': gap_type,
            '缺口產生日期': gap_date.strftime('%Y/%m/%d'),
            '需回補價格': round(target_price, 2), 
            '補缺狀態': '已補' if is_filled else '未補',
            '回補日期': fill_date,
            '缺口日成交量': f"{int(vol_val):,}" 
        })
            
    result_df = pd.DataFrame(all_gaps)
    if not result_df.empty:
        result_df = result_df.sort_values(by='缺口產生日期', ascending=False).reset_index(drop=True)
    
    total_days = len(stock_data)
    raw_gaps = len(target_gaps)
    
    # 【記憶體優化】刪除龐大原始資料，呼叫垃圾回收
    del stock_data
    del target_gaps
    gc.collect()
        
    return result_df, total_days, raw_gaps, stock_name, last_date, last_close

# -------------------------
# 網頁視覺介面 (Streamlit)
# -------------------------
st.set_page_config(page_title="股票缺口查詢系統", layout="wide")

# 【重點防護】在載入主畫面與任何大量變數前，攔截未授權的使用者
if not check_password():
    st.stop()

# ==================== 通過密碼後才會執行以下內容 ====================
st.title("📈 股票缺口自動篩選系統")
st.markdown("---")

col1, col2, col3, col4, col5 = st.columns(5)

min_allowed_date = datetime(1980, 1, 1)
max_allowed_date = datetime.today()

with col1:
    ticker_input = st.text_input("股票代號或名稱", value="", placeholder="請輸入代號或名稱...")
with col2:
    start_date = st.date_input("起始日期", value=datetime(1998, 3, 9), min_value=min_allowed_date, max_value=max_allowed_date)
with col3:
    end_date = st.date_input("結束日期", value=datetime.today(), min_value=min_allowed_date, max_value=max_allowed_date)
with col4:
    gap_type = st.selectbox("缺口型態", ["下缺口", "上缺口"])
with col5:
    status_type = st.selectbox("補缺狀態", ["未補", "已補", "全部"])

btn_col1, btn_col2, info_col = st.columns([1, 1.2, 7.8])
with btn_col1:
    search_clicked = st.button("查詢", type="primary")
with btn_col2:
    clear_clicked = st.button("清除畫面")

info_placeholder = info_col.empty()

st.markdown("---")

if "current_df" not in st.session_state:
    st.session_state.current_df = None
if "info_html" not in st.session_state:
    st.session_state.info_html = ""
if "sys_info" not in st.session_state:
    st.session_state.sys_info = ""

if clear_clicked:
    st.session_state.current_df = None
    st.session_state.info_html = ""
    st.session_state.sys_info = ""
    gc.collect() # 清除畫面時一併清理記憶體
    st.rerun()

if search_clicked:
    if not ticker_input:
        st.warning("⚠️ 請輸入股票代號或名稱！")
    else:
        with st.spinner(f"正在搜尋並分析 {gap_type} 資料，請稍候..."):
            actual_ticker = resolve_ticker(ticker_input)
            
            market_type = "上市"
            ticker_try = f"{actual_ticker}.TW" 
            result_df, total_days, raw_gaps, stock_name, last_date, last_close = find_all_gaps(ticker_try, start_date, end_date, gap_type)
            
            if total_days == 0:
                market_type = "上櫃"
                ticker_try = f"{actual_ticker}.TWO"
                result_df, total_days, raw_gaps, stock_name, last_date, last_close = find_all_gaps(ticker_try, start_date, end_date, gap_type)
                if total_days > 0:
                    st.toast(f"已自動切換至上櫃股票", icon="🔄")
            
            if total_days > 0:
                st.session_state.info_html = f"<div style='padding-top: 6px; font-size: 16px; color: #4F8BF9;'>個股收盤資訊 **{actual_ticker} {stock_name}** 收盤 **{last_close}** {last_date} {market_type}</div>"
                st.session_state.sys_info = f"💡 系統資訊：共抓取到 {total_days} 天的歷史股價，這段期間共產生過 {raw_gaps} 個 {gap_type}。"
                
                if not result_df.empty:
                    if status_type == "未補":
                        filtered_df = result_df[result_df['補缺狀態'] == '未補'].copy()
                    elif status_type == "已補":
                        filtered_df = result_df[result_df['補缺狀態'] == '已補'].copy()
                    else:
                        filtered_df = result_df.copy()
                        
                    st.session_state.current_df = filtered_df
                    del filtered_df
                else:
                    st.session_state.current_df = pd.DataFrame()
                
                del result_df
                gc.collect()
            else:
                st.error(f"❌ 抓取失敗：無法解析「{ticker_input}」或查無歷史資料，請確認輸入是否正確。")
                st.session_state.current_df = None

if st.session_state.info_html:
    info_placeholder.markdown(st.session_state.info_html, unsafe_allow_html=True)

if st.session_state.sys_info:
    st.info(st.session_state.sys_info)

if st.session_state.current_df is not None:
    if st.session_state.current_df.empty:
        st.warning(f"⚠️ 條件篩選結果：這段期間內沒有符合「{status_type}」狀態的 {gap_type}。")
    else:
        st.success(f"✅ 查詢成功！符合「{status_type}」條件的缺口共有 {len(st.session_state.current_df)} 筆。")
        st.dataframe(st.session_state.current_df, use_container_width=True, hide_index=True)
        
        csv = st.session_state.current_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 下載報表 (CSV 檔案)",
            data=csv,
            file_name=f"{actual_ticker}_{stock_name}_{gap_type}報表.csv",
            mime="text/csv",
        )