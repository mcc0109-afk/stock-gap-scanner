import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from datetime import datetime, timedelta
import urllib.parse

# 【非常重要：網頁設定必須是所有 Streamlit 指令的第一行，以防畫面變白】
st.set_page_config(page_title="股票缺口查詢系統", layout="wide")

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
    st.info("請輸入專屬密碼以啟用「股票缺口自動篩選系統」。")
    
    password = st.text_input("請輸入密碼：", type="password")
    
    if password:
        if password == APP_PASSWORD:
            st.session_state["password_correct"] = True
            st.rerun() 
        else:
            st.error("❌ 密碼錯誤，請重新輸入。")
            
    return False

# -------------------------
# 將「中文股票名稱」自動轉換為「股票代號」
# -------------------------
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
# 輔助功能：從 API 抓取乾淨的中文名稱
# -------------------------
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
# 核心運算邏輯 (新增回傳最後收盤價與日期)
# -------------------------
@st.cache_data(show_spinner=False)
def find_all_gaps(ticker_symbol, start_date, end_date, gap_type):
    stock_name = get_chinese_stock_name(ticker_symbol)
    start_str = start_date.strftime('%Y-%m-%d')
    end_date_plus_1 = end_date + timedelta(days=1)
    end_str = end_date_plus_1.strftime('%Y-%m-%d')
    
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    
    stock_data = yf.download(ticker_symbol, start=start_str, end=end_str, auto_adjust=False, session=session)
    
    if stock_data.empty:
        return pd.DataFrame(), 0, 0, stock_name, "", 0.0

    if isinstance(stock_data.columns, pd.MultiIndex):
        stock_data.columns = [col[0] for col in stock_data.columns]

    # 【更新】確保有抓到 Close (收盤價) 欄位
    for col in ['High', 'Low', 'Close', 'Volume']:
        if col not in stock_data.columns:
            return pd.DataFrame(), len(stock_data), 0, stock_name, "", 0.0
            
    stock_data['High'] = stock_data['High'].astype(float)
    stock_data['Low'] = stock_data['Low'].astype(float)
    stock_data['Close'] = stock_data['Close'].astype(float)
    stock_data['Volume'] = stock_data['Volume'].astype(float)
    
    # 【新增】取得最後一天的收盤日期與收盤價
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
        
    return result_df, len(stock_data), len(target_gaps), stock_name, last_date, last_close

# -------------------------
# 網頁視覺介面 (Streamlit)
# -------------------------

if not check_password():
    st.stop() 

st.title("📈 股票缺口自動篩選系統")
st.markdown("---")

col1, col2, col3, col4, col5 = st.columns(5)

# 保留 1980 年為可選擇的最早日期
min_allowed_date = datetime(1980, 1, 1)
max_allowed_date = datetime.today()
# 【重點更新】計算今天的 5 年前作為預設起始日期
default_start_date = datetime.today() - timedelta(days=5*365)

with col1:
    ticker_input = st.text_input("股票代號或名稱", value="定穎投控")
with col2:
    # 套用 5 年前的預設日期
    start_date = st.date_input("起始日期", value=default_start_date, min_value=min_allowed_date, max_value=max_allowed_date)
with col3:
    end_date = st.date_input("結束日期", value=datetime.today(), min_value=min_allowed_date, max_value=max_allowed_date)
with col4:
    gap_type = st.selectbox("缺口型態", ["下缺口", "上缺口"])
with col5:
    status_type = st.selectbox("補缺狀態", ["未補", "已補", "全部"])

# 調整按鈕區塊的比例，加入「清除畫面」按鈕與「資訊顯示區」
btn_col1, btn_col2, info_col = st.columns([1, 1.2, 7.8])
with btn_col1:
    search_clicked = st.button("查詢", type="primary")
with btn_col2:
    # 點擊清除畫面會觸發網頁重新載入，自動清空下方的查詢結果
    clear_clicked = st.button("清除畫面")

# 建立一個隱藏的文字區塊，等一下用來塞入收盤資訊
info_placeholder = info_col.empty()

st.markdown("---")

if search_clicked:
    if not ticker_input:
        st.warning("⚠️ 請輸入股票代號或名稱！")
    else:
        with st.spinner(f"正在搜尋並分析 {gap_type} 資料，請稍候..."):
            actual_ticker = resolve_ticker(ticker_input)
            
            # 優先嘗試上市 (.TW)
            market_type = "上市"
            ticker_try = f"{actual_ticker}.TW" 
            result_df, total_days, raw_gaps, stock_name, last_date, last_close = find_all_gaps(ticker_try, start_date, end_date, gap_type)
            
            # 如果找不到，自動切換為上櫃 (.TWO)
            if total_days == 0:
                market_type = "上櫃"
                ticker_try = f"{actual_ticker}.TWO"
                result_df, total_days, raw_gaps, stock_name, last_date, last_close = find_all_gaps(ticker_try, start_date, end_date, gap_type)
                if total_days > 0:
                    st.toast(f"已自動切換至上櫃股票", icon="🔄")
            
            # 將收盤資訊填入按鈕旁邊的預留位置
            if total_days > 0:
                info_text = f"個股收盤資訊 **{actual_ticker} {stock_name}** 收盤 **{last_close}** {last_date} {market_type}"
                info_placeholder.markdown(f"<div style='padding-top: 6px; font-size: 16px; color: #4F8BF9;'>{info_text}</div>", unsafe_allow_html=True)
            
            st.info(f"💡 系統資訊：共抓取到 {total_days} 天的歷史股價，這段期間共產生過 {raw_gaps} 個 {gap_type}。")
            
            if total_days == 0:
                st.error(f"❌ 抓取失敗：無法解析「{ticker_input}」或查無歷史資料，請確認輸入是否正確。")
            elif result_df.empty:
                st.warning(f"⚠️ 查無任何 {gap_type} 資料。")
            else:
                if status_type == "未補":
                    display_df = result_df[result_df['補缺狀態'] == '未補']
                elif status_type == "已補":
                    display_df = result_df[result_df['補缺狀態'] == '已補']
                else:
                    display_df = result_df
                
                if display_df.empty:
                    st.warning(f"⚠️ 條件篩選結果：這段期間內沒有符合「{status_type}」狀態的 {gap_type}。")
                else:
                    st.success(f"✅ 查詢成功！符合「{status_type}」條件的缺口共有 {len(display_df)} 筆。")
                    st.dataframe(display_df, use_container_width=True, hide_index=True)
                    
                    csv = display_df.to_csv(index=False).encode('utf-8-sig')
                    st.download_button(
                        label="📥 下載報表 (CSV 檔案)",
                        data=csv,
                        file_name=f"{actual_ticker}_{stock_name}_{gap_type}報表.csv",
                        mime="text/csv",
                    )