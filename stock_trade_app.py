import tkinter as tk
from tkinter import ttk, messagebox
import yfinance as yf
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from datetime import datetime, time as dt_time
import matplotlib.dates as mdates
import threading
import os
import time
import pytz
import pandas as pd
import glob
import webbrowser
import numpy as np

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from pathlib import Path

BASE_DIR = Path(__file__).parent

log_dir = BASE_DIR / "Log Files"
log_dir.mkdir(exist_ok=True)

CHROME_DRIVER_PATH = BASE_DIR / "chromedriver.exe"
CHROME_PROFILE_PATH = BASE_DIR / "ChromeSeleniumProfile"

def load_latest_tracked_tickers():
    log_dir = Path(__file__).parent / "Log Files"
    if not log_dir.exists():
        return []
    log_files = sorted(log_dir.glob("*.txt"), key=os.path.getmtime, reverse=True)
    for log_file in log_files:
        with open(log_file, "r") as f:
            for line in f:
                if line.startswith("TRACKED_TICKERS:"):
                    return line.strip().split(":")[1].split(",")
    return []

class MultiIndexTrackerFrame(ttk.LabelFrame):
    def __init__(self, parent, initial_delay_ms):
        super().__init__(parent, text="Index Tracker")
        self.eastern = pytz.timezone("US/Eastern")
        self.symbols = ["^DJI", "^IXIC", "^GSPC"]
        self.refresh_interval_ms = 60000
        self.last_cached_dfs = {}

        self.fig, self.ax = plt.subplots(figsize=(4, 2.5), dpi=100)
        formatter = mdates.DateFormatter('%I:%M %p', tz=self.eastern)
        self.ax.xaxis.set_major_formatter(formatter)
        self.ax.set_xlabel("Time")
        self.ax.set_ylabel("Change from Opening (%)")
        self.ax.grid(True)

        self.lines = {}
        friendly_labels = {"^DJI": "DOW", "^IXIC": "NASDAQ", "^GSPC": "S&P500"}
        for symbol in self.symbols:
            line, = self.ax.plot([], [], label=friendly_labels.get(symbol, symbol))
            self.lines[symbol] = line

        self.ax.legend()
 
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        self.after(initial_delay_ms, self.update_graph)

    def update_graph(self):
        self.update_plot()
        self.after(self.refresh_interval_ms, self.update_graph)

    def update_plot(self):
        try:
            any_data = False
            now = datetime.now(pytz.UTC)
            today = now.date()
            start_time = pd.Timestamp(f"{today} 13:30:00", tz="UTC")
            end_time = pd.Timestamp(f"{today} 20:00:00", tz="UTC")

            in_trading_hours = start_time <= now <= end_time

            for line in self.lines.values():
                line.set_data([], [])

            for child in self.ax.lines[3:]:
                child.remove()

            for symbol in self.symbols:
                interval = "1m" if in_trading_hours else "5m"
                df_full = yf.download(symbol, period="2d", interval=interval, progress=False, auto_adjust=True)
                df_full.dropna(inplace=True)

                if df_full.empty:
                    continue

                if isinstance(df_full.columns, pd.MultiIndex):
                    close_col = ('Close', symbol)
                    if close_col in df_full.columns:
                        df_full = df_full[close_col].to_frame(name='Close')
                    else:
                        continue
                elif symbol in df_full.columns:
                    df_full = df_full[[symbol]].rename(columns={symbol: 'Close'})
                elif 'Close' in df_full.columns:
                    df_full = df_full[['Close']]
                else:
                    continue

                today_date = today
                yesterday_date = today - pd.Timedelta(days=1)

                df_today = df_full[df_full.index.date == today_date]
                df_yesterday = df_full[df_full.index.date == yesterday_date]

                most_recent_date = df_full.index.normalize().max()
                df_most_recent = df_full[df_full.index.normalize() == most_recent_date]

                if in_trading_hours and not df_today.empty:
                    df = df_today
                    if not df_yesterday.empty:
                        ref_price = df_yesterday["Close"].iloc[-1]
                        print(f"Using yesterday close: {ref_price}")
                    else:
                        ref_price = df["Close"].iloc[0]
                        print(f"No yesterday data, using today first close: {ref_price}")
                else:
                    df = df_most_recent
                    if df.empty or df["Close"].empty:
                        continue
                    ref_price = df["Close"].iloc[0]

                normalized = (df["Close"] / ref_price * 100) - 100

                self.lines[symbol].set_data(df.index.to_pydatetime(), normalized.values)

                any_data = True

            if any_data:
                self.ax.relim()
                self.ax.autoscale_view()

                eastern = pytz.timezone("US/Eastern")
                formatter = mdates.DateFormatter('%I:%M %p', tz=eastern)
                self.ax.xaxis.set_major_formatter(formatter)
    
                all_times = []
                for line in self.lines.values():
                    xdata = line.get_xdata()
                    if len(xdata) > 0:
                        all_times.extend(xdata)

                if all_times:
                    min_time = min(all_times)
                    max_time = max(all_times)
                    self.ax.set_xlim([min_time, max_time])

                else:
                    print("⚠ No data points found to set xlim. Keeping autoscale only.")

                self.ax.legend()
                self.canvas.draw()
            else:
                print("⚠ No data found to plot any line.")

        except Exception as e:
            print(f"Graph update error in indices tracker: {e}")


class StockTrackerFrame(ttk.LabelFrame):
    def __init__(self, parent, tracker_id, app, initial_delay_ms, initial_symbol):
        super().__init__(parent, text=f"Stock Tracker {tracker_id}")
        self.app = app
        self.eastern = pytz.timezone("US/Eastern")
        self.stock_symbol = initial_symbol if initial_symbol else ""
        self.amount = "50"
        self.refresh_interval_ms = 60000
        self.highlight_price = None
        self.last_cached_df = None
        self.tooltip = None

        self.default_font = ("Helvetica", 15)

        try:
            if self.stock_symbol:
                company_name = yf.Ticker(self.stock_symbol).info.get('longName', self.stock_symbol)
            else:
                company_name = "No Symbol"
        except Exception as e:
            print(f"Could not fetch company name for {self.stock_symbol}: {e}")
            company_name = self.stock_symbol or "No Symbol"

        self.fig, self.ax = plt.subplots(figsize=(4, 2.5), dpi=100)
        formatter = mdates.DateFormatter('%I:%M %p', tz=self.eastern)
        self.ax.xaxis.set_major_formatter(formatter)
        self.ax.set_xlabel("Time")
        self.ax.set_ylabel("Price ($)")
        self.title_text = self.ax.set_title(company_name, fontsize=18, fontweight='bold')
        self.title_text.set_picker(True)
        self.ax.grid(True)

        self.line, = self.ax.plot([], [], label=self.stock_symbol)
        self.hlines = []

        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        self.canvas.mpl_connect("pick_event", self.on_title_click)
        self.canvas.mpl_connect("motion_notify_event", self.on_hover)

        self.controls = ttk.Frame(self)
        self.controls.pack(fill=tk.X, padx=2, pady=2)

        self.top_controls = ttk.Frame(self.controls)
        self.top_controls.pack(fill=tk.X)

        self.top_controls.columnconfigure(0, weight=1)
        self.top_controls.columnconfigure(1, weight=1)
        self.top_controls.columnconfigure(2, weight=1)
        self.top_controls.columnconfigure(3, weight=1)
        self.top_controls.columnconfigure(4, weight=1)
        self.top_controls.columnconfigure(5, weight=1)

        self.symbol_label = ttk.Label(self.top_controls, text="Ticker:", font=self.default_font)
        self.symbol_label.grid(row=0, column=0, sticky="e", padx=4)
        self.symbol_entry = ttk.Entry(self.top_controls, width=6, font=self.default_font)
        self.symbol_entry.insert(0, self.stock_symbol)
        self.symbol_entry.grid(row=0, column=1, sticky="w", padx=4)

        self.amount_label = ttk.Label(self.top_controls, text="Amount ($):", font=self.default_font)
        self.amount_label.grid(row=0, column=2, sticky="e", padx=4)
        self.amount_entry = ttk.Entry(self.top_controls, width=8, font=self.default_font)
        self.amount_entry.insert(0, self.amount)
        self.amount_entry.grid(row=0, column=3, sticky="w", padx=4)

        self.load_button = ttk.Button(self.top_controls, text="Load", command=self.update_symbol)
        self.load_button.grid(row=0, column=5, sticky="w", padx=4)

        self.bottom_controls = ttk.Frame(self.controls)
        self.bottom_controls.pack(fill=tk.X, pady=(5,0))

        self.bottom_controls.columnconfigure(0, weight=1)
        self.bottom_controls.columnconfigure(1, weight=1)
        self.bottom_controls.columnconfigure(2, weight=1)

        self.buy_button = ttk.Button(self.bottom_controls, text="Buy", command=self.mark_price_and_buy)
        self.buy_button.grid(row=1, column=0, sticky="n", padx=4)

        self.sell_button = ttk.Button(self.bottom_controls, text="Sell", command=self.mark_price_and_sell)
        self.sell_button.grid(row=1, column=1, sticky="n", padx=4)
        self.sell_button.config(state="disabled")

        self.reset_button = ttk.Button(self.bottom_controls, text="Reset", command=self.reset_buttons)
        self.reset_button.grid(row=1, column=2, sticky="n", padx=4)

        style = ttk.Style()
        style.configure("Big.TButton", font=self.default_font)
        self.load_button.config(style="Big.TButton")
        self.buy_button.config(style="Big.TButton")
        self.sell_button.config(style="Big.TButton")
        self.reset_button.config(style="Big.TButton")

        self.after(initial_delay_ms, self.update_graph)

    def on_title_click(self, event):
        if event.artist == self.title_text:
            self.hide_tooltip()
            url = f"https://finance.yahoo.com/quote/{self.stock_symbol}/latest-news/"
            webbrowser.open(url)

    def on_hover(self, event):
        contains, _ = self.title_text.contains(event)
        if contains:
            self.show_tooltip(event)
        else:
            self.hide_tooltip()

    def show_tooltip(self, event):
        if self.tooltip is None:
            self.tooltip = tk.Toplevel(self)
            self.tooltip.wm_overrideredirect(True)
            self.tooltip.attributes("-topmost", True)
            label = tk.Label(self.tooltip,
                             text=f"Current {self.stock_symbol} News",
                             font=("Helvetica", 12),
                             bg="yellow", relief="solid", bd=1)
            label.pack(ipadx=5, ipady=2)
        offset_x = 20
        offset_y = 10
        x = self.winfo_pointerx()
        y = self.winfo_pointery()
        self.tooltip.geometry(f"+{x + offset_x}+{y + offset_y}")

        self.after(1000, self.hide_tooltip)

    def clear_all_horizontal_lines(self):
        for line in list(self.ax.lines):
            ydata = line.get_ydata()        
            if len(ydata) > 0:
                try:
                    ref_y = float(ydata.iloc[0])
                except AttributeError:
                    ref_y = float(ydata[0]) 
                if all(y == ref_y for y in ydata):
                    try:
                        line.remove()
                    except ValueError:
                        pass

    def hide_tooltip(self):
        if self.tooltip is not None:
            self.tooltip.destroy()
            self.tooltip = None

    def update_symbol(self):
        new_symbol = self.symbol_entry.get().strip().upper()
        if new_symbol:
            self.clear_all_horizontal_lines()
            try:
                df = yf.download(new_symbol, period="1d", interval="1m", progress=False, auto_adjust=True)
                df.dropna(inplace=True)
                if df.empty:
                    raise ValueError("No data returned.")
            except Exception:
                messagebox.showerror("Invalid Symbol", f"The ticker '{new_symbol}' could not be loaded.\nPlease check the symbol and try again.")
                return

            self.stock_symbol = new_symbol
            self.highlight_price = None
            company_name = yf.Ticker(self.stock_symbol).info.get('longName', self.stock_symbol)
            self.title_text = self.ax.set_title(company_name, fontsize=18, fontweight='bold')
            self.line.set_label(self.stock_symbol)
            if self.ax.legend_:
                self.ax.legend_.remove()
            self.ax.legend()
            self.update_plot()
            self.canvas.draw_idle()

    def is_positive_number(self,value):
        try:
            return float(value) > 0
        except (ValueError, TypeError):
            return False

    def reset_buttons(self):
        confirm = messagebox.askyesno(
            "Confirm Reset",
            "Are you sure you want to reset this tracker?\n"
            "This will clear all purchase markers and re-enable Buy."
        )
        if not confirm:
            return

        self.highlight_price = None
        self.update_plot()
        self.buy_button.config(state="normal")
        self.sell_button.config(state="disabled")
        self.amount_label.config(text="Amount ($):")
        self.app.status_label.config(text="Buttons reset: Buy enabled, Sell disabled.")
        self.canvas.draw()

    def mark_price_and_sell(self):
        self.amount = self.amount_entry.get().strip()
        if not self.is_positive_number(self.amount):
            messagebox.showerror("Input Error", "Amount must be a positive number.")
            return
        self.highlight_price = None
        self.update_plot()
        self.post_sale_action()
        self.amount_label.config(text="Amount ($):")
        self.app.enable_all_trackers()
        threading.Thread(
            target=self.app._launch_selenium_order,
            args=(self.stock_symbol, self.amount, "sell"),
            daemon=True
        ).start()

    def post_sale_action(self):
        current_price = self.get_current_price()
        if current_price is None:
            self.app.status_label.config(text="Could not get price to log sale.")
            return

        line = f"[{datetime.now().strftime('%H:%M:%S')}] Sale Price for {self.stock_symbol}: ${current_price:.2f}\n"
        self.app.log_file.write(line)
        self.app.log_file.flush()
        self.app.status_label.config(text=f"Sale logged at ${current_price:.2f}.")

    def post_purchase_action(self):
        current_price = self.get_current_price()
        if current_price is None:
            self.app.status_label.config(text="Could not get price to log purchase.")
            return

        line = f"[{datetime.now().strftime('%H:%M:%S')}] Purchase Price for {self.stock_symbol}: ${current_price:.2f}\n"
        self.app.log_file.write(line)
        self.app.log_file.flush()

        with open(self.app.log_file.name, "r") as f:
            lines = f.readlines()
            for line in reversed(lines):
                if f"Purchase Price for {self.stock_symbol}" in line:
                    import re
                    match = re.search(r"\$([0-9,.]+)", line)
                    if match:
                        self.highlight_price = float(match.group(1).replace(",", ""))
                    break

        self.highlight_price = current_price
        self.update_plot()

        self.app.status_label.config(text=f"Purchase logged & horizontals drawn at ${current_price:.2f}")

    def mark_price_and_buy(self):
        self.amount = self.amount_entry.get().strip()
        if not self.is_positive_number(self.amount):
            messagebox.showerror("Input Error", "Amount must be a positive number.")
            return
        self.app.disable_all_trackers()
        self.buy_button.config(state="disabled")
        self.sell_button.config(state="normal")
        self.reset_button.config(state="normal")
        self.amount_label.config(text="Amount (Shares):")
        threading.Thread(
            target=self.app._launch_selenium_order,
            args=(self.stock_symbol, self.amount, "buy", self),
            daemon=True
        ).start()

    def get_current_price(self):
        if not self.stock_symbol:
            return None         
        try:
            df = yf.download(self.stock_symbol, period="1d", interval="1m", progress=False, auto_adjust=True)
            df.dropna(inplace=True)
            if not df.empty:
                return df["Close"].iloc[-1].item()
        except Exception:
            return None

    def update_graph(self):
        self.update_plot()
        self.after(self.refresh_interval_ms, self.update_graph)

    def update_plot(self):
        if not self.stock_symbol:
            return 
        try:
            stock_symbol = self.stock_symbol
            now = datetime.now(pytz.UTC)
            today = now.date()
            weekday = now.weekday()  # Monday=0, Sunday=6

            # Define trading hours in UTC (approximate; adjust for exchange if needed)
            start_time_utc = pd.Timestamp(f"{today} 13:30:00", tz="UTC")
            end_time_utc = pd.Timestamp(f"{today} 20:00:00", tz="UTC")

            in_trading_hours = start_time_utc <= now <= end_time_utc

            # Always get 2 days to have yesterday for prepending
            df_full = yf.download(self.stock_symbol, period="2d", interval="1m", progress=False, auto_adjust=True)
            df_full.dropna(inplace=True)
            if df_full.empty:
                return
            # Keep index in UTC (default from yfinance)

            # Normalize for clean slicing
            date_index = df_full.index.normalize()
            target_yesterday = pd.Timestamp(today - pd.Timedelta(days=1))
            target_today = pd.Timestamp(today)
            most_recent_date = date_index.max()

            df_yesterday = df_full[date_index == target_yesterday]
            df_today = df_full[date_index == target_today]

            # 🔍 1) Handle outside trading hours first (including weekends)
            if not in_trading_hours or weekday >= 5:
                # Use full day slice for last available day
                start_of_day = most_recent_date
                end_of_day = start_of_day + pd.Timedelta(days=1)
                df = df_full.loc[start_of_day:end_of_day - pd.Timedelta(microseconds=1)]
                if not df.empty:
                    ref_price = df["Close"].iloc[0]
                    if isinstance(ref_price, pd.Series):
                        ref_price = ref_price.iloc[0]
                else:
                    return

            # 🔍 2) Otherwise, handle trading hours during the week
            else:
                if not df_today.empty:
                    if not df_yesterday.empty:
                        last_close_yesterday = df_yesterday["Close"].iloc[-1]
                        first_time_today = df_today.index[0] - pd.Timedelta(minutes=1)
                        prepend_df = pd.DataFrame({"Close": [last_close_yesterday]}, index=[first_time_today])
                        prepend_array = pd.concat([prepend_df, df_today])
                        merged_series = prepend_array["Close"]
                        df = merged_series.to_frame(name="Close")
                        ref_price = last_close_yesterday
                    else:
                        df = df_today
                        ref_price = df["Close"].iloc[0]
                        if isinstance(ref_price, pd.Series):
                            ref_price = ref_price.iloc[0]
                else:
                    # trading hours but no data? fallback
                    start_of_day = most_recent_date
                    end_of_day = start_of_day + pd.Timedelta(days=1)
                    df = df_full.loc[start_of_day:end_of_day - pd.Timedelta(microseconds=1)]
                    if not df.empty:
                        ref_price = df["Close"].iloc[0]
                        if isinstance(ref_price, pd.Series):
                            ref_price = ref_price.iloc[0]
                    else:
                        return

            # 🔍 Plotting
            current_prices = df["Close"]
            if isinstance(current_prices, pd.DataFrame):
                current_prices = current_prices.iloc[:,0]
            self.line.set_data(df.index, current_prices)
            self.line.set_label(self.stock_symbol)
            self.ax.relim()
            self.ax.autoscale_view()

            # x-axis still in UTC but format ticks in Eastern for readability
            eastern = pytz.timezone("US/Eastern")
            formatter = mdates.DateFormatter('%I:%M %p', tz=eastern)
            self.ax.xaxis.set_major_formatter(formatter)

            first_ts = df.index[0].to_pydatetime()
            last_ts = df.index[-1].to_pydatetime()
            if (first_ts <= start_of_day) and (last_ts >= end_of_day):
                self.ax.set_xlim([start_of_day, end_of_day])
            else:
                self.ax.set_xlim([df.index[0], df.index[-1]])

            # 🔍 Reference bands
            for h in self.hlines:
                h.remove()
            self.hlines.clear()
            self.hlines.append(self.ax.axhline(y=ref_price * 1.01, color="blue", linestyle="--"))
            self.hlines.append(self.ax.axhline(y=ref_price * 0.99, color="blue", linestyle="--"))

            # 🔍 Purchase lines
            if hasattr(self, 'purchase_lines'):
                self.purchase_lines = [l for l in self.purchase_lines if l in self.ax.lines]
                for l in self.purchase_lines:
                    try:
                        l.remove()
                    except ValueError:
                        pass
                self.purchase_lines.clear()

            if isinstance(self.highlight_price, (float, int)):
                h1 = self.ax.axhline(y=self.highlight_price, color="green", linestyle="-", label="Purchase Price")
                h2 = self.ax.axhline(y=self.highlight_price * 1.01, color="red", linestyle="-", label="Sell Price")
                self.hlines.extend([h1, h2])

            self.ax.legend()
            self.canvas.draw()

        except Exception as e:
            print(f"Graph update error: {e}")


class StockApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("8-Tracker Stock Viewer with Normalized Index + Staggered Updates + Trade Autofill")
        self.geometry("1700x950")

        tracked_tickers = load_latest_tracked_tickers()

        now = datetime.now()
        filename = now.strftime("%d%b%y_%H.%M.%S.txt")
        log_path = log_dir / filename
        self.log_file = open(log_path, "a")
        self.log_file.write(f"Session started at {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
        self.log_file.flush()

        self.default_font = ("Helvetica", 15)

        self.top_frame = ttk.Frame(self)
        self.top_frame.pack(fill=tk.BOTH, expand=True)

        ROWS = 2
        COLS = 4
        tracker_id = 1
        symbol_index = 0
        for r in range(ROWS):
            self.top_frame.rowconfigure(r, weight=1)
            for c in range(COLS):
                self.top_frame.columnconfigure(c, weight=1)
                delay_ms = ((r * COLS + c) % 8) * 1000
                if r == 0 and c == 0:
                    tracker = MultiIndexTrackerFrame(self.top_frame, delay_ms)
                else:
                    initial_symbol = tracked_tickers[symbol_index] if symbol_index < len(tracked_tickers) else ""
                    tracker = StockTrackerFrame(self.top_frame, tracker_id, self, delay_ms, initial_symbol)
                    tracker_id += 1
                    symbol_index += 1
                tracker.grid(row=r, column=c, padx=4, pady=4, sticky="nsew")

        self.bottom_frame = ttk.Frame(self)
        self.bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)

        self.check_button = ttk.Button(self.bottom_frame, text="Check Fidelity Page", command=self.check_fidelity_elements)
        self.check_button.pack(side=tk.LEFT, padx=5)
        self.check_button.config(style="Big.TButton")

        self.status_label = ttk.Label(self.bottom_frame, text="Ready.", font=self.default_font)
        self.status_label.pack(side=tk.LEFT, padx=20)

        self.override_button = ttk.Button(self.bottom_frame, text="Override Enable Buttons", command=self.enable_all_trackers)
        self.override_button.pack(side=tk.RIGHT, padx=5)
        self.override_button.config(style="Big.TButton")

        threading.Thread(target=self.init_selenium_driver, daemon=True).start()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def init_selenium_driver(self):
        try:
            self.after(0, lambda: self.status_label.config(text="Starting browser..."))
            self.driver = self.start_driver()
            self.after(0, lambda: self.status_label.config(text="Browser started."))
            self.start_keepalive_monitor()
        except Exception as e:
            self.after(0, lambda e=e: self.status_label.config(text=f"Error starting browser: {e}"))
            self.after(0, lambda: messagebox.showerror("Browser Error", f"Could not start Selenium:\n{e}"))

    def start_keepalive_monitor(self):
        def keepalive_check():
            while True:
                time.sleep(5)
                try:
                    if not self.driver or not self.driver.service.process:
                        raise Exception("Driver process missing.")
                    _ = self.driver.title
                except Exception:
                    self.restart_browser()
                    break
        threading.Thread(target=keepalive_check, daemon=True).start()

    def restart_browser(self):
        try:
            self.status_label.config(text="Browser closed. Restarting...")
            self.driver = self.start_driver()
            self.status_label.config(text="Browser restarted.")
            self.start_keepalive_monitor()
        except Exception as e:
            self.status_label.config(text=f"Error restarting: {e}")

    def start_driver(self):
        service = Service(executable_path=str(CHROME_DRIVER_PATH))
        options = webdriver.ChromeOptions()
        options.add_argument("start-maximized")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)

        driver = webdriver.Chrome(service=service, options=options)
        print("✅ Selenium Chrome driver started successfully.")

        driver.get("https://digital.fidelity.com/ftgw/digital/trade-equity/index/orderEntry")

        wait = WebDriverWait(driver, 300)
        target_url_snippet = "/ftgw/digital/trade-equity/index/orderEntry"

        while True:
            try:
                current_url = driver.current_url
                if target_url_snippet in current_url:
                    print(f"✅ Trading page URL detected: {current_url}")
                    break

                wait.until(EC.presence_of_element_located((By.ID, "eq-ticket-dest-symbol")))
                print("✅ Logged in and trading page loaded.")
                break
            except:
                print(f"⌛ Waiting for login to complete... Currently at {current_url}")
                time.sleep(3)

        return driver

    def ensure_browser_alive(self):
        try:
            if not self.driver or not self.driver.service.process:
                raise Exception("Browser not running.")
            _ = self.driver.title
        except Exception:
            self.status_label.config(text="Browser lost. Restarting...")
            self.restart_browser()

    def _launch_selenium_order(self, symbol, amount, action_text, tracker_frame=None):
        try:
            self.ensure_browser_alive()

            self.status_label.config(text=f"Running trade autofill ({action_text.capitalize()})...")

            driver = self.driver
            wait = WebDriverWait(driver, 20)
            driver.execute_script("window.open('https://digital.fidelity.com/ftgw/digital/trade-equity/index/orderEntry', '_blank');")
            driver.switch_to.window(driver.window_handles[-1])
            wait.until(lambda d: d.execute_script('return document.readyState') == 'complete')
            time.sleep(2)
            symbol_input = wait.until(EC.visibility_of_element_located((By.ID, "eq-ticket-dest-symbol")))
            symbol_input.clear()
            symbol_input.send_keys(symbol)
            symbol_input.send_keys(Keys.TAB)

            xpath_query = f"//s-assigned-wrapper[normalize-space()='{action_text.capitalize()}']"
            buttons = driver.find_elements(By.XPATH, xpath_query)

            action_button = wait.until(EC.element_to_be_clickable((
                By.XPATH, f"//s-assigned-wrapper[normalize-space()='{action_text.capitalize()}']"
            )))
            driver.execute_script("arguments[0].scrollIntoView(true);", action_button)
            time.sleep(0.2)
            action_button.click()

            if action_text.lower() == "buy":
                type_label = "Dollars"
            else:
                type_label = "Shares"
            type_option = wait.until(EC.element_to_be_clickable((
                By.XPATH, f"//s-assigned-wrapper[normalize-space()='{type_label}']"
            )))
            driver.execute_script("arguments[0].scrollIntoView(true);", type_option)
            type_option.click()

            quantity_input = wait.until(EC.visibility_of_element_located((By.ID, "eqt-shared-quantity")))
            quantity_input.clear()
            quantity_input.send_keys(amount)
            market_option = wait.until(EC.element_to_be_clickable((
                By.XPATH, "//s-assigned-wrapper[normalize-space()='Market']"
            )))
            driver.execute_script("arguments[0].scrollIntoView(true);", market_option)
            market_option.click()

            cash_option = wait.until(EC.element_to_be_clickable((
                By.XPATH, "//s-assigned-wrapper[normalize-space()='Cash']"
            )))
            driver.execute_script("arguments[0].scrollIntoView(true);", cash_option)
            cash_option.click()

            line = f"[{datetime.now().strftime('%H:%M:%S')}] Executed {action_text.capitalize()}: {symbol}, Qty: {amount}, Market, Cash\n"
            self.log_file.write(line)
            self.log_file.flush()
            self.status_label.config(text=f"Done autofill. Waiting for browser close...")
            
            messagebox.showinfo("Continue", "Close this trading tab when you are finished.\nThen click OK to confirm.")
            driver.close() 
            driver.switch_to.window(driver.window_handles[0])

            if action_text.lower() =="buy" and tracker_frame:
                tracker_frame.post_purchase_action()
            elif action_text.lower() == "sell" and tracker_frame:
                tracker_frame.post_sale_action()

            self.status_label.config(text=f"{action_text.capitalize()} completed. Ready.")

        except Exception as e:
            self.status_label.config(text=f"Error: {e}")
            messagebox.showerror("Selenium Error", f"Something went wrong:\n{e}")

    def check_fidelity_elements(self):
        threading.Thread(target=self._check_elements_thread, daemon=True).start()

    def disable_all_trackers(self):
        for child in self.top_frame.winfo_children():
            if isinstance(child, StockTrackerFrame):
                child.buy_button.config(state="disabled")
                child.sell_button.config(state="disabled")
                child.reset_button.config(state="disabled")

    def enable_all_trackers(self):
        for child in self.top_frame.winfo_children():
            if isinstance(child, StockTrackerFrame):
                child.buy_button.config(state="normal")
                child.sell_button.config(state="disabled")
                child.reset_button.config(state="normal")
                for h in list(child.hlines):
                    if hasattr(h, 'get_linestyle') and (h.get_linestyle() == '-'):
                        h.remove()
                child.hlines.clear()
                child.highlight_price = None
                child.canvas.draw()

    def _check_elements_thread(self):
        try:
            self.ensure_browser_alive()

            self.status_label.config(text="Checking Fidelity site elements...")
            driver = self.driver
            wait = WebDriverWait(driver, 20)
            driver.execute_script("window.open('https://digital.fidelity.com/ftgw/digital/trade-equity/index/orderEntry', '_blank');")
            driver.switch_to.window(driver.window_handles[-1])
            wait.until(lambda d: d.execute_script('return document.readyState') == 'complete')
            time.sleep(3)
            checks = [("eq-ticket-dest-symbol", "Stock symbol input"), ("eqt-shared-quantity", "Quantity input")]
            missing = []
            for element_id, description in checks:
                try:
                    wait.until(EC.presence_of_element_located((By.ID, element_id)))
                except:
                    missing.append(f"{description} (ID: {element_id})")
            if missing:
                missing_str = "\n".join(missing)
                messagebox.showerror("Fidelity Site Check Failed", f"The following expected elements were not found:\n\n{missing_str}")
                self.status_label.config(text="Fidelity site check failed.")
            else:
                messagebox.showinfo("Fidelity Site Check", "✔ Elements found. Page structure OK.")
                self.status_label.config(text="Fidelity site check passed.")
        except Exception as e:
            self.status_label.config(text=f"Error: {e}")
            messagebox.showerror("Fidelity Site Check Error", f"Could not complete site check:\n{e}")

    def on_close(self):
        try:
            tickers = []
            for child in self.top_frame.winfo_children():
                if isinstance(child, StockTrackerFrame):
                    tickers.append(child.stock_symbol)

            if tickers:
                self.log_file.write("\nTRACKED_TICKERS:" + ",".join(tickers) + "\n")
                self.log_file.flush()

            if hasattr(self, 'driver') and self.driver:
                try:
                    self.driver.quit()
                except Exception as e:
                    print(f"Driver quit failed: {e}")
                try:
                    self.driver.service.stop()
                except Exception as e:
                    print(f"Service stop failed: {e}")
                try:
                    if self.driver.service.process:
                        self.driver.service.process.kill()
                except Exception as e:
                    print(f"Direct kill failed: {e}")
        except Exception as e:
            print(f"Unexpected error on close: {e}")
        finally:
            try:
                self.log_file.close()
            except:
                pass
            self.destroy()
            os._exit(0)

if __name__ == "__main__":
    app = StockApp()
    app.mainloop()
