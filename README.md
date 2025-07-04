# Stock Trading Tracker & Selenium Autofill

This is a Python application for tracking multiple stocks in real-time with Tkinter and Matplotlib, alongside normalized index plots. It also integrates Selenium to autofill trade orders on Fidelity.

## Features
- Track up to 8 individual stock tickers with automatic updates. Only during trading hours. Usage outside of normal hours will only pull up the previous days data
- Displays normalized index comparison (Dow, Nasdaq, S&P 500).
- Buy & sell buttons trigger Selenium autofill on Fidelity's trading page and tracker horizontals to mark approximate purchase price and 1% gain price.
- Automatic logging of trades and tracked tickers on close for reuse.
- Reference horizontals on each track which are ticker dependent (Blue; +/-1% based on opening price).
- Additional features, but early development.

## Requirements
- Python 3.10+ recommended
- Google Chrome installed
- ChromeDriver matching your Chrome version (included in this folder)
- A fidelity trading account

## Installation
1. Clone or download this repository.
2. Open a terminal or command prompt in this directory and install required packages:
    ```
    pip install -r requirements.txt
    ```
# ChromeDriver setup
This project expects `chromedriver.exe` to be in the same folder. 

- ⚠ Due to repository best practices, this file is not included in the GitHub repo.
- Please download the ChromeDriver version matching your installed Chrome from:
  https://chromedriver.chromium.org/downloads
- Place `chromedriver.exe` in this directory alongside `stock_trade_app.py`.


## Usage
1. Ensure `chromedriver.exe` is present in this folder and matches your installed Chrome version.
2. Run the app with:
    ```
    python stock_trade_app.py
    ```
3. Enter stock tickers, set amounts, and execute trades. 
4. When you close the application, your session log and currently tracked tickers are saved to make it easy to pick up next time.

## License
© 2025 Mike McClellan. For personal use only. Redistribution, modification, or resale without express permission is prohibited.
