import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import urllib.parse
import re

# -------------------------
# 新增功能：將「中文股票名稱」自動轉換為「股票代號」
# -------------------------
def resolve_ticker(user_input):
    user_input = str(user_input).strip()
    
    # 情況 1：如果全都是數字，代表使用者輸入的是代號，直接回傳
    if user_input.isdigit():
        return user_input
        
    # 情況 2：如果輸入的是中文或英文，呼叫 Yahoo 搜尋 API 找代號
    try:
        # 將中文進行 URL 安全編碼
        encoded_input = urllib.parse.quote(user_input)
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={encoded_input}&quotesCount=5&newsCount=0"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        response = requests.get(url, headers=headers, timeout=5)
        data = response.json()
        
        if 'quotes' in data and len(data['quotes']) > 0:
            # 優先尋找帶有 .TW (上市) 或 .TWO (上櫃) 的台灣股票
            for quote in data['quotes']:
                symbol = quote.get('symbol', '')
                if symbol.endswith('.TW') or symbol.endswith('.TWO'):
                    return symbol.split('.')[0]
                    
            # 如果都沒找到台股綴字，提取第一個搜尋結果中的「數字部分」
            first_symbol = data['quotes'][0].get('symbol', '')
            match = re.search(r'\d+', first_symbol)
            if match:
                return match.group()
    except:
        pass
        
    # 如果轉換失敗，原封不動回傳，讓後續的錯誤處理去擋下
    return user_input

# -------------------------
# 輔助功能：從 Yahoo 奇摩股市抓取中文名稱
# -------------------------
def get_chinese_stock_name(ticker_symbol):
    try:
        clean_ticker = ticker_symbol.split('.')[0]
        url = f"https://tw.stock.yahoo.com/quote/{clean_ticker}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        title_tag = soup.find('title')
        if title_tag:
            title_text = title_tag.text
            if '(' in title_text:
                return title_text.split('(')[0].strip()
        return '未知名稱'
    except:
        return '未知名稱'

# -------------------------
# 1. 核心運算邏輯 
# -------------------------
@st.cache_data(show_spinner=False)
def find_all_gaps(ticker_symbol, start_date, end_date, gap_type):
    stock_name = get_chinese_stock_name(ticker_symbol)

    start_str = start_date.strftime('%Y-%m-%d')
    end_date_plus_1 = end_date + timedelta(days=1)
    end_str = end_date_plus_1.strftime('%Y-%m-%d')
    
    # 建立專屬 Session 繞過雲端防機器人阻擋
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    
    stock_data = yf.download(ticker_symbol, start=start_str, end=end_str, auto_adjust=False, session=session)
    
    if stock_data.empty:
        return pd.DataFrame(), 0, 0, stock_name

    if isinstance(stock_data.columns, pd.MultiIndex):
        stock_data.columns = [col[0] for col in stock_data.columns]

    for col in ['High', 'Low', 'Volume']:
        if col not in stock_data.columns:
            return pd.DataFrame(), len(stock_data), 0, stock_name
            
    stock_data['High'] = stock_data['High'].astype(float)
    stock_data['Low'] = stock_data['Low'].astype(float)
    stock_data['Volume'] = stock_data['Volume'].astype(float)
    
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
        
    return result_df, len(stock_data), len(target_gaps), stock_name

# -------------------------
# 2. 網頁視覺介面 (Streamlit)
# -------------------------
st.set_page_config(page_title="股票缺口查詢系統", layout="wide")

st.title("📈 股票缺口自動篩選系統")
st.markdown("---")

col1, col2, col3, col4, col5 = st.columns(5)

min_allowed_date = datetime(1980, 1, 1)
max_allowed_date = datetime.today()

with col1:
    # 【更新 UI】提示使用者可以輸入名稱
    ticker_input = st.text_input("股票代號或名稱", value="聯電", help="可輸入如: 2303, 聯電, 台積電...")
with col2:
    start_date = st.date_input("起始日期", value=datetime(1998, 3, 9), min_value=min_allowed_date, max_value=max_allowed_date)
with col3:
    end_date = st.date_input("結束日期", value=datetime.today(), min_value=min_allowed_date, max_value=max_allowed_date)
with col4:
    gap_type = st.selectbox("缺口型態", ["下缺口", "上缺口"])
with col5:
    status_type = st.selectbox("補缺狀態", ["未補", "已補", "全部"])

btn_col1, btn_col2 = st.columns([1, 10])
with btn_col1:
    search_clicked = st.button("查詢", type="primary")

st.markdown("---")

# -------------------------
# 3. 按下查詢後的動作
# -------------------------
if search_clicked:
    if not ticker_input:
        st.warning("⚠️ 請輸入股票代號或名稱！")
    else:
        with st.spinner(f"正在搜尋並分析 {gap_type} 資料，請稍候..."):
            
            # 【重點更新】先將使用者的輸入 (例如: 聯電) 轉換成純數字代號 (例如: 2303)
            actual_ticker = resolve_ticker(ticker_input)
            
            ticker_try = f"{actual_ticker}.TW" 
            result_df, total_days, raw_gaps, stock_name = find_all_gaps(ticker_try, start_date, end_date, gap_type)
            
            if total_days == 0:
                ticker_try = f"{actual_ticker}.TWO"
                result_df, total_days, raw_gaps, stock_name = find_all_gaps(ticker_try, start_date, end_date, gap_type)
                if total_days > 0:
                    st.toast(f"已自動切換至上櫃股票", icon="🔄")
            
            # 顯示時使用轉換後的 actual_ticker
            st.info(f"💡 系統資訊：正在查詢 **{stock_name} ({actual_ticker})**。共抓取到 {total_days} 天的歷史股價，這段期間共產生過 {raw_gaps} 個 {gap_type}。")
            
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
                    
                    st.dataframe(
                        display_df, 
                        use_container_width=True, 
                        hide_index=True 
                    )
                    
                    csv = display_df.to_csv(index=False).encode('utf-8-sig')
                    st.download_button(
                        label="📥 下載報表 (CSV 檔案)",
                        data=csv,
                        file_name=f"{actual_ticker}_{stock_name}_{gap_type}報表.csv",
                        mime="text/csv",
                    )