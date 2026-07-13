import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np  
import requests
from datetime import datetime, timedelta
import urllib.parse
import gc

# 【最高準則：網頁排版設定必須是全程式第一行，防白畫面】
st.set_page_config(page_title="股票缺口查詢系統", layout="wide")

# ==========================================
# 🔑 密碼設定區
# ==========================================
APP_PASSWORD = "1688" 

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

# 智慧代號解析 (輕量字串快取，保留)
@st.cache_data(ttl=86400, max_entries=20, show_spinner=False)
def resolve_ticker(user_input):
    user_input = str(user_input).strip()
    if user_input.isdigit():
        return user_input
    try:
        encoded_input = urllib.parse.quote(user_input)
        url = f"https://tw.stock.yahoo.com/_td-stock/api/resource/AutocompleteService;limit=5;query={encoded_input}"
        headers = {'User-Agent': 'Mozilla/5.0'}
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

# 抓取乾淨的中文名稱 (輕量字串快取，保留)
@st.cache_data(ttl=86400, max_entries=20, show_spinner=False)
def get_chinese_stock_name(ticker_symbol):
    clean_ticker = ticker_symbol.split('.')[0]
    try:
        url = f"https://tw.stock.yahoo.com/_td-stock/api/resource/AutocompleteService;limit=5;query={clean_ticker}"
        headers = {'User-Agent': 'Mozilla/5.0'}
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

# -------------------------------------------------------------
# 🔥 【核心手術】完全拔除 @st.cache_data 快取！拒絕讓 Streamlit 在記憶體留存大表格
# -------------------------------------------------------------
def find_all_gaps(ticker_symbol, start_date, end_date, gap_type):
    stock_name = get_chinese_stock_name(ticker_symbol)
    start_str = start_date.strftime('%Y-%m-%d')
    end_date_plus_1 = end_date + timedelta(days=1)
    end_str = end_date_plus_1.strftime('%Y-%m-%d')
    
    # 不再重複建立 Session，直接下載，交由 yfinance 內部釋放連線
    stock_data = yf.download(ticker_symbol, start=start_str, end=end_str, auto_adjust=False, progress=False)
    
    if stock_data.empty:
        return pd.DataFrame(), 0, 0, stock_name, "", 0.0

    if isinstance(stock_data.columns, pd.MultiIndex):
        stock_data.columns = [col[0] for col in stock_data.columns]

    needed_cols = ['High', 'Low', 'Close', 'Volume']
    for col in needed_cols:
        if col not in stock_data.columns:
            return pd.DataFrame(), len(stock_data), 0, stock_name, "", 0.0
            
    # 只提取必要數據並轉成 float32 陣列
    stock_data = stock_data[needed_cols].astype('float32')
    total_days = len(stock_data)
    
    high_vals = stock_data['High'].values
    low_vals = stock_data['Low'].values
    close_vals = stock_data['Close'].values
    vol_vals = stock_data['Volume'].values
    date_vals = stock_data.index.strftime('%Y/%m/%d').values
    
    last_date = date_vals[-1]
    last_close = round(float(close_vals[-1]), 2)
    
    # 抽取完 NumPy 陣列，立斬 DataFrame
    del stock_data
    gc.collect() 
    
    all_gaps = []
    
    for i in range(1, total_days):
        gap_date_str = date_vals[i]
        vol_val = float(vol_vals[i])
        
        if gap_type == "下缺口":
            if high_vals[i] < low_vals[i-1]:
                target_price = float(low_vals[i-1])
                future_highs = high_vals[i+1:]
                fill_indices = np.where(future_highs >= target_price)[0]
                is_filled = len(fill_indices) > 0
                fill_date = date_vals[i + 1 + fill_indices[0]] if is_filled else "-"
                
                all_gaps.append({
                    '股票代號': ticker_symbol.split('.')[0],
                    '股票名稱': stock_name,
                    '缺口型態': gap_type,
                    '缺口產生日期': gap_date_str,
                    '需回補價格': round(target_price, 2), 
                    '補缺狀態': '已補' if is_filled else '未補',
                    '回補日期': fill_date,
                    '缺口日成交量': f"{int(vol_val):,}" 
                })
        else:
            if low_vals[i] > high_vals[i-1]:
                target_price = float(high_vals[i-1])
                future_lows = low_vals[i+1:]
                fill_indices = np.where(future_lows <= target_price)[0]
                is_filled = len(fill_indices) > 0
                fill_date = date_vals[i + 1 + fill_indices[0]] if is_filled else "-"
                
                all_gaps.append({
                    '股票代號': ticker_symbol.split('.')[0],
                    '股票名稱': stock_name,
                    '缺口型態': gap_type,
                    '缺口產生日期': gap_date_str,
                    '需回補價格': round(target_price, 2), 
                    '補缺狀態': '已補' if is_filled else '未補',
                    '回補日期': fill_date,
                    '缺口日成交量': f"{int(vol_val):,}" 
                })
                
    raw_gaps = len(all_gaps)
    result_df = pd.DataFrame(all_gaps)
    if not result_df.empty:
        result_df = result_df.sort_values(by='缺口產生日期', ascending=False).reset_index(drop=True)
    
    del high_vals, low_vals, close_vals, vol_vals, date_vals
    gc.collect()
        
    return result_df, total_days, raw_gaps, stock_name, last_date, last_close

# -------------------------
# 網頁視覺介面
# -------------------------
if not check_password():
    st.stop()

st.title("📈 股票缺口自動篩選系統")
st.markdown("---")

col1, col2, col3, col4, col5 = st.columns(5)

min_allowed_date = datetime(1980, 1, 1)
max_allowed_date = datetime.today()

with col1:
    ticker_input = st.text_input("股票代號或名稱", value="", placeholder="請輸入代號或名稱...")
with col2:
    # 🔥 【重點優化】將預設起始日期改為 3 年前，進一步提升速度並降低記憶體消耗。
    default_start = datetime.today() - timedelta(days=3*365)
    start_date = st.date_input("起始日期", value=default_start, min_value=min_allowed_date, max_value=max_allowed_date)
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
    gc.collect() 
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
        st.warning(f"⚠️ 條件篩選結果：這段期間內沒有符合狀態的 {gap_type}。")
    else:
        st.success(f"✅ 查詢成功！共 {len(st.session_state.current_df)} 筆。")
        st.dataframe(st.session_state.current_df, use_container_width=True, hide_index=True)
        
        csv = st.session_state.current_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 下載報表 (CSV 檔案)",
            data=csv,
            file_name=f"{actual_ticker}_{stock_name}_{gap_type}報表.csv",
            mime="text/csv",
        )