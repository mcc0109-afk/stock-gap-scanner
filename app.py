import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np  
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
# 智慧代號解析 (加入 max_entries 防止快取記憶體爆掉)
# -------------------------
@st.cache_data(ttl=86400, max_entries=50, show_spinner=False)
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
# 從 API 抓取乾淨的中文名稱 
# -------------------------
@st.cache_data(ttl=86400, max_entries=50, show_spinner=False)
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
    return