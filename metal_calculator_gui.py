#!/usr/bin/env python3
"""
Metal Price Calculator - Multi-Metal Edition
Supports Gold, Silver, Platinum, and Copper

Features:
- Multiple metals with real-time pricing
- Customizable price formulas with weighted metrics
- Unit conversion (gram, oz, lb)
- State sales tax calculator
- Inventory tracking for any metal
- Export to CSV
- Price predictions with comprehensive metric tracking for algorithm improvement

HYBRID APPROACH:
- Current price: gold-api.com (FREE, unlimited, 24/7 spot prices)
- Historical data: Yahoo Finance/yfinance (FREE, reliable)

PREDICTION HISTORY saves ALL metrics for analysis:
- RSI, RSI signal, ATR, volatility %
- 7d/14d momentum, secondary momentum
- Metal ratio, ratio trend, ratio deviation
- Beta, correlation, pressure multiplier
- Confidence breakdown signals

To convert to .exe:
1. pip install pyinstaller yfinance requests
2. pyinstaller --onefile --windowed --icon=metal.ico --name="MetalCalculator" metal_calculator_gui.py

Requires: pip install yfinance requests
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import datetime, timedelta
import threading
import sys
import os
import json
import csv
import re
import requests
import math

# Try to import yfinance
try:
    import yfinance as yf
except ImportError:
    yf = None

# =============================================================================
# CONFIGURATION
# =============================================================================
APP_NAME = "MetalCalculator"
INVENTORY_FILE = "metal_inventory.json"
FORMULAS_FILE = "custom_formulas.json"
SETTINGS_FILE = "settings.json"
PREDICTIONS_FILE = "prediction_history.json"

# API endpoints
GOLD_API_BASE = "https://api.gold-api.com/price"

# Metal configurations
METALS = {
    'Gold': {'symbol': 'XAU', 'yf_ticker': 'GC=F', 'color': '#FFD700'},
    'Silver': {'symbol': 'XAG', 'yf_ticker': 'SI=F', 'color': '#C0C0C0'},
    'Platinum': {'symbol': 'XPT', 'yf_ticker': 'PL=F', 'color': '#E5E4E2'},
    'Copper': {'symbol': 'XCU', 'yf_ticker': 'HG=F', 'color': '#B87333'}
}

# Prediction secondary options (includes non-metals for correlation)
PREDICTION_SECONDARIES = {
    'Gold': {'yf_ticker': 'GC=F', 'type': 'metal'},
    'Silver': {'yf_ticker': 'SI=F', 'type': 'metal'},
    'Platinum': {'yf_ticker': 'PL=F', 'type': 'metal'},
    'Copper': {'yf_ticker': 'HG=F', 'type': 'metal'},
    'S&P 500': {'yf_ticker': '^GSPC', 'type': 'index'}
}

# Suggested secondary pairings (backtest: Silver/S&P 500 best in-range ~66%; Silver/Copper worst direction)
SUGGESTED_PAIRINGS = {
    'Silver': 'S&P 500',   # Best in-range and lowest error in backtests
    'Gold': 'Silver',      # Inverse GSR
    'Platinum': 'Gold',    # Both precious metals
    'Copper': 'S&P 500'    # Industrial correlation
}

# DXY (US Dollar Index) ticker for confidence calculation
DXY_TICKER = 'DX-Y.NYB'

# Square root of 7 for weekly volatility scaling
SQRT_7 = 2.6457513110645907  # math.sqrt(7)

# Prediction v4: Regime and clamp constants
SP500_TICKER_REGIME = '^GSPC'
VIX_TICKER = '^VIX'
REGIME_MA_DAYS = 20
CORRELATION_FAST_DAYS = 10
CORRELATION_REGIME_DIVERGENCE = 0.3   # fast vs slow correlation diff = regime change

# Clamp levels
CLAMP_NORMAL = 0.10      # ±10% normal volatility
CLAMP_ELEVATED = 0.15    # ±15% elevated vol
CLAMP_CRISIS = 0.25      # ±25% crisis / regime change
CLAMP_RECOVERY = 0.15    # ±15% recovery
CLAMP_CRASH_SIGMA = 3.0  # dynamic σ-based (3σ max) for crash

VOLATILITY_ELEVATED_PCT = 4.0   # ATR/price % threshold for elevated clamp
VOLATILITY_CRISIS_PCT = 8.0     # ATR/price % for crisis clamp

# Beta adjustments
BEAR_BETA_SHRINK = 0.7          # bear beta 0.7x
REGIME_BETA_SHRINK = 0.7        # shrink beta when regime change (reduce amplification)

# Crash detection thresholds (3/5 triggers needed)
CRASH_VIX_THRESHOLD = 25.0
CRASH_GSR_THRESHOLD = 85.0
CRASH_ATR_PCT_THRESHOLD = 5.0
CRASH_CONSECUTIVE_DAYS = 3       # 3+ days with >2% moves
CRASH_CONSECUTIVE_MOVE = 0.02    # 2% daily move threshold
CRASH_DXY_RISE = 0.01           # DXY +1% (5-day)
CRASH_METAL_DROP = -0.02        # Metal -2% (5-day)
CRASH_TRIGGERS_NEEDED = 3       # 3 out of 5 triggers
CRASH_REVERSION_FACTOR = 0.30   # 30% towards 50d MA
CRASH_REVERSION_MA = 50         # revert towards 50d MA

# Recovery constants
RECOVERY_BUFFER_DAYS = 10       # 10 day buffer after crash
RECOVERY_REVERSION_FACTOR = 0.20  # 20% towards 20d MA
RECOVERY_REVERSION_MA = 20      # revert towards 20d MA

# Ratio pressure
RATIO_BASE_MULTIPLIER_FACTOR = 0.15  # |ρ| × 0.15
RATIO_SIDEWAYS_BOOST = 2.0
BEARISH_MOMENTUM_CUT_RATIO = 0.0  # zero ratio pressure when primary 14d momentum negative

CONFIDENCE_CAP_REGIME_CHANGE = 50   # cap confidence % when regime change detected

# Confidence weights (8-factor, total = 100%)
CONF_W_CORRELATION = 40        # Correlation (60d) 40%
CONF_W_DXY = 7                 # DXY health 7% (4% for copper)
CONF_W_DXY_COPPER = 4          # Copper DXY weight
CONF_W_REGIME_FIT = 10         # Regime fit 10%
CONF_W_RSI = 10                # RSI range 10%
CONF_W_VOLATILITY = 5          # Volatility 5%
CONF_W_RATIO = 10              # Ratio stability 10%
CONF_W_RSI_DIVERGENCE = 8      # RSI Divergence 8%
CONF_W_CORR_AGREEMENT = 10     # Correlation Agreement 10%

# Conversion factors
TROY_OUNCE_TO_GRAMS = 31.1035
POUND_TO_GRAMS = 453.592

# Unit configurations
UNITS = {
    'gram': {'factor': 1, 'label': 'per gram'},
    'oz': {'factor': TROY_OUNCE_TO_GRAMS, 'label': 'per troy oz'},
    'lb': {'factor': POUND_TO_GRAMS, 'label': 'per lb'}
}

# Metal-specific purity grades
PURITY_GRADES = {
    'Gold': [
        ('99.99% (24K Pure)', 99.99),
        ('99.9% (Fine Gold)', 99.9),
        ('95.8% (23K)', 95.8),
        ('91.67% (22K)', 91.67),
        ('87.5% (21K)', 87.5),
        ('75% (18K)', 75.0),
        ('58.5% (14K)', 58.5),
        ('41.7% (10K)', 41.7),
        ('37.5% (9K)', 37.5),
        ('Custom...', -1)
    ],
    'Silver': [
        ('99.9% (Fine Silver)', 99.9),
        ('99% (.990)', 99.0),
        ('95.8% (Britannia)', 95.8),
        ('92.5% (Sterling)', 92.5),
        ('90% (Coin Silver)', 90.0),
        ('89.24% (Coin Silver)', 89.24),
        ('80% (.800)', 80.0),
        ('75% (Coin Silver)', 75.0),
        ('40% (Coin Silver)', 40.0),
        ('35% (Coin Silver)', 35.0),
        ('Custom...', -1)
    ],
    'Platinum': [
        ('99.95% (Pure)', 99.95),
        ('95% (Pt950)', 95.0),
        ('90% (Pt900)', 90.0),
        ('85% (Pt850)', 85.0),
        ('Custom...', -1)
    ],
    'Copper': [
        ('99.9% (Pure Copper)', 99.9),
        ('99% (Commercial)', 99.0),
        ('97% (Fire Refined)', 97.0),
        ('90% (Bronze avg)', 90.0),
        ('85% (Red Brass)', 85.0),
        ('Custom...', -1)
    ]
}

# Metric abbreviations for formula builder
METRIC_ABBREVS = {
    'current_price': 'cur',
    '7_day_avg': '7davg',
    '7_day_median': '7dmed',
    '7_day_high': '7dhi',
    '7_day_low': '7dlo',
    '14_day_avg': '14davg',
    '14_day_median': '14dmed',
    '28_day_avg': '28davg',
    '28_day_median': '28dmed',
    '1_year_avg': '1yavg'
}

# Reverse lookup
ABBREV_TO_METRIC = {v: k for k, v in METRIC_ABBREVS.items()}

# US State Sales Tax Rates (as of 2024)
# Note: Many states exempt precious metals from sales tax
STATE_TAX_RATES = {
    'None (0%)': 0.0,
    'Alabama (4%)': 4.0,
    'Alaska (0%)': 0.0,
    'Arizona (5.6%)': 5.6,
    'Arkansas (6.5%)': 6.5,
    'California (7.25%)': 7.25,
    'Colorado (2.9%)': 2.9,
    'Connecticut (6.35%)': 6.35,
    'Delaware (0%)': 0.0,
    'Florida (6%)': 6.0,
    'Georgia (4%)': 4.0,
    'Hawaii (4%)': 4.0,
    'Idaho (6%)': 6.0,
    'Illinois (6.25%)': 6.25,
    'Indiana (7%)': 7.0,
    'Iowa (6%)': 6.0,
    'Kansas (6.5%)': 6.5,
    'Kentucky (6%)': 6.0,
    'Louisiana (4.45%)': 4.45,
    'Maine (5.5%)': 5.5,
    'Maryland (6%)': 6.0,
    'Massachusetts (6.25%)': 6.25,
    'Michigan (6%)': 6.0,
    'Minnesota (6.875%)': 6.875,
    'Mississippi (7%)': 7.0,
    'Missouri (4.225%)': 4.225,
    'Montana (0%)': 0.0,
    'Nebraska (5.5%)': 5.5,
    'Nevada (6.85%)': 6.85,
    'New Hampshire (0%)': 0.0,
    'New Jersey (6.625%)': 6.625,
    'New Mexico (4.875%)': 4.875,
    'New York (4%)': 4.0,
    'North Carolina (4.75%)': 4.75,
    'North Dakota (5%)': 5.0,
    'Ohio (5.75%)': 5.75,
    'Oklahoma (4.5%)': 4.5,
    'Oregon (0%)': 0.0,
    'Pennsylvania (6%)': 6.0,
    'Rhode Island (7%)': 7.0,
    'South Carolina (6%)': 6.0,
    'South Dakota (4.5%)': 4.5,
    'Tennessee (7%)': 7.0,
    'Texas (6.25%)': 6.25,
    'Utah (6.1%)': 6.1,
    'Vermont (6%)': 6.0,
    'Virginia (5.3%)': 5.3,
    'Washington (6.5%)': 6.5,
    'West Virginia (6%)': 6.0,
    'Wisconsin (5%)': 5.0,
    'Wyoming (4%)': 4.0,
    'Washington DC (6%)': 6.0,
    'Custom...': -1  # Flag for custom entry
}

# Available metrics for formulas
AVAILABLE_METRICS = [
    'current_price',
    '7_day_avg',
    '7_day_median',
    '7_day_high',
    '7_day_low',
    '14_day_avg',
    '14_day_median',
    '28_day_avg',
    '28_day_median',
    '1_year_avg'
]

METRIC_LABELS = {
    'current_price': "Today's Price",
    '7_day_avg': '7-Day Average',
    '7_day_median': '7-Day Median',
    '7_day_high': '7-Day High',
    '7_day_low': '7-Day Low',
    '14_day_avg': '14-Day Average',
    '14_day_median': '14-Day Median',
    '28_day_avg': '28-Day Average',
    '28_day_median': '28-Day Median',
    '1_year_avg': '1-Year Average'
}


class MetalCalculatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Metal Price Calculator")
        self.root.geometry("900x900")
        self.root.resizable(True, True)
        self.root.minsize(850, 700)
        
        # Set icon
        self.set_icon()
        
        # Use system theme
        self.style = ttk.Style()
        self.style.theme_use('vista' if 'vista' in self.style.theme_names() else 'clam')
        
        # Configure custom styles
        self.style.configure("green.Horizontal.TProgressbar", troughcolor='#e0e0e0', background='#4CAF50')
        self.style.configure("yellow.Horizontal.TProgressbar", troughcolor='#e0e0e0', background='#FFC107')
        self.style.configure("orange.Horizontal.TProgressbar", troughcolor='#e0e0e0', background='#FF9800')
        self.style.configure("red.Horizontal.TProgressbar", troughcolor='#e0e0e0', background='#f44336')
        
        # Data storage - metrics per gram (base unit)
        self.metrics = {}  # Will hold all calculated metrics for current metal
        self.inventory_prices = {}  # Will hold current prices for ALL metals (for inventory tab)
        self.prediction_data = {}  # Will hold prediction metrics for each metal {metal: {daily_prices, rsi, atr, etc}}
        self.current_prediction_result = None  # Stores the most recent prediction for saving
        self.current_metal = 'Silver'
        self.current_unit = 'gram'
        
        # Storage
        self.inventory = []
        self.custom_formulas = []
        self.prediction_history = []  # Stores past predictions for grading
        self.settings = {
            'default_metal': 'Silver',
            'default_unit': 'gram',
            'sales_tax_state': 'None (0%)',
            'custom_tax_rate': 0.0
        }
        
        # Load saved data
        self.load_settings()
        self.load_inventory()
        self.load_formulas()
        self.load_prediction_history()
        
        # Apply settings
        self.current_metal = self.settings.get('default_metal', 'Silver')
        self.current_unit = self.settings.get('default_unit', 'gram')
        
        # Initialize tax variables (needed before UI creation)
        self.tax_state_var = tk.StringVar(value=self.settings.get('sales_tax_state', 'None (0%)'))
        self.custom_tax_var = tk.StringVar(value=str(self.settings.get('custom_tax_rate', 0.0)))
        
        # Check for yfinance
        if yf is None:
            self.show_install_message()
            return
        
        # Create UI
        self.create_widgets()
        
        # Check for matured predictions to grade on startup (delayed to not block UI)
        self.root.after(2000, self.check_and_auto_grade)
    
    def check_and_auto_grade(self):
        """Check for matured predictions and offer to grade them"""
        now = datetime.now()
        ungraded = [r for r in self.prediction_history 
                   if not r['graded'] and datetime.fromisoformat(r['target_date']) <= now]
        
        if ungraded:
            if messagebox.askyesno("Matured Predictions", 
                                  f"You have {len(ungraded)} prediction(s) ready to be graded.\n\n"
                                  "Would you like to grade them now?"):
                self.grade_predictions_thread()
        
    def show_install_message(self):
        """Show message if yfinance is not installed"""
        frame = ttk.Frame(self.root, padding="20")
        frame.pack(fill='both', expand=True)
        
        ttk.Label(frame, text="Missing Required Package", font=('Segoe UI', 14, 'bold')).pack(pady=(0, 20))
        ttk.Label(frame, text="Please install required packages by running:").pack()
        
        cmd_frame = ttk.Frame(frame)
        cmd_frame.pack(pady=10)
        cmd_text = tk.Text(cmd_frame, height=1, width=35, font=('Consolas', 10))
        cmd_text.insert('1.0', "pip install yfinance requests")
        cmd_text.config(state='disabled')
        cmd_text.pack()
        
        ttk.Label(frame, text="Then restart this application.").pack(pady=(10, 0))
        
    def set_icon(self):
        """Set the window icon"""
        try:
            if getattr(sys, 'frozen', False):
                base_path = sys._MEIPASS
            else:
                base_path = os.path.dirname(os.path.abspath(__file__))
            
            icon_path = os.path.join(base_path, 'metal.ico')
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
            elif os.path.exists('metal.ico'):
                self.root.iconbitmap('metal.ico')
        except Exception:
            pass
    
    def get_app_data_path(self):
        """Get the path for app data storage"""
        if sys.platform == 'win32':
            app_data = os.environ.get('APPDATA', os.path.expanduser('~'))
            app_folder = os.path.join(app_data, APP_NAME)
        else:
            app_folder = os.path.join(os.path.expanduser('~'), f'.{APP_NAME.lower()}')
        
        if not os.path.exists(app_folder):
            os.makedirs(app_folder)
        
        return app_folder
    
    def load_settings(self):
        """Load settings from JSON file"""
        try:
            path = os.path.join(self.get_app_data_path(), SETTINGS_FILE)
            if os.path.exists(path):
                with open(path, 'r') as f:
                    self.settings.update(json.load(f))
        except Exception as e:
            print(f"Error loading settings: {e}")
    
    def save_settings(self):
        """Save settings to JSON file"""
        try:
            path = os.path.join(self.get_app_data_path(), SETTINGS_FILE)
            with open(path, 'w') as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            print(f"Error saving settings: {e}")
    
    def load_inventory(self):
        """Load inventory from JSON file"""
        try:
            path = os.path.join(self.get_app_data_path(), INVENTORY_FILE)
            if os.path.exists(path):
                with open(path, 'r') as f:
                    self.inventory = json.load(f)
        except Exception as e:
            print(f"Error loading inventory: {e}")
            self.inventory = []
    
    def save_inventory(self):
        """Save inventory to JSON file"""
        try:
            path = os.path.join(self.get_app_data_path(), INVENTORY_FILE)
            with open(path, 'w') as f:
                json.dump(self.inventory, f, indent=2)
        except Exception as e:
            print(f"Error saving inventory: {e}")
            messagebox.showerror("Save Error", f"Could not save inventory: {e}")
    
    def load_formulas(self):
        """Load custom formulas from JSON file"""
        try:
            path = os.path.join(self.get_app_data_path(), FORMULAS_FILE)
            if os.path.exists(path):
                with open(path, 'r') as f:
                    self.custom_formulas = json.load(f)
        except Exception as e:
            print(f"Error loading formulas: {e}")
            self.custom_formulas = []
        
        # Add default formulas if none exist
        if not self.custom_formulas:
            self.custom_formulas = [
                {
                    'name': 'Goal Price',
                    'color': '#008000',  # Green
                    'expression': '((7davg * 2 + 28davg + 14davg * 2 + cur * 2) / 7) * 0.85',
                    'apply_tax': True,
                    'description': 'Weighted average with 15% safety margin',
                    'group': 'Default'
                },
                {
                    'name': 'Max Price',
                    'color': '#CC7000',  # Orange
                    'expression': '((((7davg * 2 + 14davg + 7dmed) / 4) + cur) / 2) * 0.95',
                    'apply_tax': True,
                    'description': 'Conservative price with 5% safety margin',
                    'group': 'Default'
                },
                {
                    'name': 'Break Even',
                    'color': '#CC0000',  # Red
                    'expression': '(cur + 7dmed) / 2',
                    'apply_tax': True,
                    'description': 'Simple average of current and median - no margin',
                    'group': 'Default'
                }
            ]
            self.save_formulas()
        
        # Ensure all formulas have a group (migrate old formulas)
        for formula in self.custom_formulas:
            if 'group' not in formula:
                formula['group'] = 'Default'
        
        # Load formula groups
        self.formula_groups = self.settings.get('formula_groups', ['Default'])
        if 'Default' not in self.formula_groups:
            self.formula_groups.insert(0, 'Default')
        
        # Current selected group for calculator display
        self.selected_formula_group = self.settings.get('selected_formula_group', 'All Groups')
    
    def save_formulas(self):
        """Save custom formulas to JSON file"""
        try:
            path = os.path.join(self.get_app_data_path(), FORMULAS_FILE)
            with open(path, 'w') as f:
                json.dump(self.custom_formulas, f, indent=2)
        except Exception as e:
            print(f"Error saving formulas: {e}")
    
    def load_prediction_history(self):
        """Load prediction history from JSON file"""
        try:
            path = os.path.join(self.get_app_data_path(), PREDICTIONS_FILE)
            if os.path.exists(path):
                with open(path, 'r') as f:
                    self.prediction_history = json.load(f)
        except Exception as e:
            print(f"Error loading prediction history: {e}")
            self.prediction_history = []
    
    def save_prediction_history(self):
        """Save prediction history to JSON file"""
        try:
            path = os.path.join(self.get_app_data_path(), PREDICTIONS_FILE)
            with open(path, 'w') as f:
                json.dump(self.prediction_history, f, indent=2)
        except Exception as e:
            print(f"Error saving prediction history: {e}")
        
    def create_widgets(self):
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Tab 1: Calculator
        calc_frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(calc_frame, text="  Calculator  ")
        self.create_calculator_tab(calc_frame)
        
        # Tab 2: Formula Builder
        formula_frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(formula_frame, text="  Formula Builder  ")
        self.create_formula_tab(formula_frame)
        
        # Tab 3: Predictions
        pred_frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(pred_frame, text="  Predictions  ")
        self.create_predictions_tab(pred_frame)
        
        # Tab 4: Inventory
        inv_frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(inv_frame, text="  Inventory  ")
        self.create_inventory_tab(inv_frame)
        
        # Tab 5: Settings
        settings_frame = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(settings_frame, text="  Settings  ")
        self.create_settings_tab(settings_frame)
        
        # Status bar at bottom
        status_bar = ttk.Frame(self.root)
        status_bar.pack(fill='x', side='bottom')
        ttk.Separator(status_bar, orient='horizontal').pack(fill='x')
        self.timestamp_label = ttk.Label(status_bar, text="Ready - Select a metal and fetch prices", foreground="gray", font=('Segoe UI', 8))
        self.timestamp_label.pack(side='left', padx=5, pady=2)
        
    def create_calculator_tab(self, parent):
        """Create the calculator tab content"""
        # Top control bar
        control_frame = ttk.Frame(parent)
        control_frame.pack(fill='x', pady=(0, 10))
        
        # Metal selector
        ttk.Label(control_frame, text="Metal:").pack(side='left')
        self.metal_var = tk.StringVar(value=self.current_metal)
        metal_combo = ttk.Combobox(control_frame, textvariable=self.metal_var, state='readonly', width=10)
        metal_combo['values'] = list(METALS.keys())
        metal_combo.pack(side='left', padx=(5, 15))
        metal_combo.bind('<<ComboboxSelected>>', self.on_metal_change)
        
        # Unit selector
        ttk.Label(control_frame, text="Unit:").pack(side='left')
        self.unit_var = tk.StringVar(value=self.current_unit)
        unit_combo = ttk.Combobox(control_frame, textvariable=self.unit_var, state='readonly', width=10)
        unit_combo['values'] = list(UNITS.keys())
        unit_combo.pack(side='left', padx=(5, 15))
        unit_combo.bind('<<ComboboxSelected>>', self.on_unit_change)
        
        # Fetch button
        self.fetch_btn = ttk.Button(control_frame, text="🔄 Fetch Live Prices", command=self.fetch_prices_thread)
        self.fetch_btn.pack(side='left', padx=(10, 0))
        
        self.status_label = ttk.Label(control_frame, text="", foreground="gray")
        self.status_label.pack(side='left', padx=(10, 0))
        
        # Progress bar (hidden initially)
        self.progress = ttk.Progressbar(parent, mode='indeterminate', length=300)
        
        # =====================
        # METRICS DISPLAY
        # =====================
        metrics_frame = ttk.LabelFrame(parent, text=" Price Metrics ", padding="10")
        metrics_frame.pack(fill='x', pady=(0, 10))
        
        # Create grid for metrics
        metrics_grid = ttk.Frame(metrics_frame)
        metrics_grid.pack(fill='x')
        
        # Create StringVars for all metrics
        self.metric_vars = {}
        row = 0
        col = 0
        for i, metric in enumerate(AVAILABLE_METRICS):
            label = METRIC_LABELS[metric]
            ttk.Label(metrics_grid, text=f"{label}:").grid(row=row, column=col*3, sticky='e', padx=(0, 5), pady=2)
            self.metric_vars[metric] = tk.StringVar(value="--")
            ttk.Label(metrics_grid, textvariable=self.metric_vars[metric], font=('Segoe UI', 9, 'bold')).grid(row=row, column=col*3+1, sticky='w', pady=2)
            
            col += 1
            if col >= 2:  # 2 columns
                col = 0
                row += 1
        
        # =====================
        # CALCULATED PRICES
        # =====================
        calc_frame = ttk.LabelFrame(parent, text=" Calculated Prices (per unit) ", padding="10")
        calc_frame.pack(fill='x', pady=(0, 10))
        
        # Formula group selector
        group_select_frame = ttk.Frame(calc_frame)
        group_select_frame.pack(fill='x', pady=(0, 10))
        
        ttk.Label(group_select_frame, text="Formula Group:").pack(side='left')
        self.formula_group_var = tk.StringVar(value=self.selected_formula_group)
        self.formula_group_combo = ttk.Combobox(group_select_frame, textvariable=self.formula_group_var, 
                                                 state='readonly', width=20)
        self.formula_group_combo.pack(side='left', padx=(5, 0))
        self.formula_group_combo.bind('<<ComboboxSelected>>', self.on_formula_group_change)
        self.update_formula_group_dropdown()
        
        self.calc_prices_frame = ttk.Frame(calc_frame)
        self.calc_prices_frame.pack(fill='x')
        
        # Will be populated by refresh_calculated_prices()
        self.calc_price_vars = {}
        
        # Tax info
        self.tax_info_var = tk.StringVar(value="")
        ttk.Label(calc_frame, textvariable=self.tax_info_var, foreground="gray", font=('Segoe UI', 8)).pack(anchor='w', pady=(5, 0))
        
        # =====================
        # QUICK CALCULATOR
        # =====================
        quick_frame = ttk.LabelFrame(parent, text=" Quick Calculator ", padding="10")
        quick_frame.pack(fill='x', pady=(0, 10))
        
        # Input grid
        input_grid = ttk.Frame(quick_frame)
        input_grid.pack(fill='x')
        
        # Purity selection (metal-specific)
        ttk.Label(input_grid, text="Purity:").grid(row=0, column=0, sticky='e', padx=(0, 5), pady=5)
        self.purity_var = tk.StringVar()
        self.purity_combo = ttk.Combobox(input_grid, textvariable=self.purity_var, width=20)
        self.purity_combo.grid(row=0, column=1, sticky='w', pady=5)
        self.purity_combo.bind('<<ComboboxSelected>>', self.on_purity_change)
        
        # Custom purity entry (hidden by default)
        self.custom_purity_var = tk.StringVar(value="100")
        self.custom_purity_entry = ttk.Entry(input_grid, textvariable=self.custom_purity_var, width=8)
        self.custom_purity_label = ttk.Label(input_grid, text="%")
        
        # Initialize purity options for current metal
        self.update_purity_options()
        
        # Weight
        ttk.Label(input_grid, text="Weight:").grid(row=1, column=0, sticky='e', padx=(0, 5), pady=5)
        self.weight_entry = ttk.Entry(input_grid, width=15)
        self.weight_entry.grid(row=1, column=1, sticky='w', pady=5)
        
        # Weight unit
        self.weight_unit_var = tk.StringVar(value="grams")
        weight_unit_combo = ttk.Combobox(input_grid, textvariable=self.weight_unit_var, state='readonly', width=8)
        weight_unit_combo['values'] = ['grams', 'oz', 'lb']
        weight_unit_combo.grid(row=1, column=2, sticky='w', padx=(5, 0), pady=5)
        
        # Shipping
        ttk.Label(input_grid, text="Shipping:").grid(row=2, column=0, sticky='e', padx=(0, 5), pady=5)
        self.shipping_entry = ttk.Entry(input_grid, width=15)
        self.shipping_entry.insert(0, "0")
        self.shipping_entry.grid(row=2, column=1, sticky='w', pady=5)
        ttk.Label(input_grid, text="$").grid(row=2, column=2, sticky='w', padx=(5, 0), pady=5)
        
        # Bind Enter key
        self.weight_entry.bind('<Return>', lambda e: self.calculate_quick())
        self.shipping_entry.bind('<Return>', lambda e: self.calculate_quick())
        
        # Calculate button
        ttk.Button(quick_frame, text="Calculate", command=self.calculate_quick).pack(pady=(10, 10))
        
        # Results
        results_frame = ttk.Frame(quick_frame)
        results_frame.pack(fill='x')
        
        ttk.Label(results_frame, text="Pure Metal Content:").grid(row=0, column=0, sticky='e', padx=(0, 5), pady=2)
        self.metal_content_var = tk.StringVar(value="--")
        ttk.Label(results_frame, textvariable=self.metal_content_var).grid(row=0, column=1, sticky='w', pady=2)
        
        ttk.Label(results_frame, text="Market Value:").grid(row=1, column=0, sticky='e', padx=(0, 5), pady=2)
        self.market_value_var = tk.StringVar(value="--")
        ttk.Label(results_frame, textvariable=self.market_value_var).grid(row=1, column=1, sticky='w', pady=2)
        
        ttk.Separator(results_frame, orient='horizontal').grid(row=2, column=0, columnspan=2, sticky='ew', pady=8)
        
        # Calculated price results (will be populated dynamically)
        self.quick_calc_frame = ttk.Frame(results_frame)
        self.quick_calc_frame.grid(row=3, column=0, columnspan=2, sticky='ew')
        
        self.quick_calc_vars = {}
        
        # Initialize calculated prices display
        self.refresh_calculated_prices_display()
        
    def create_formula_tab(self, parent):
        """Create the formula builder tab"""
        # Instructions
        ttk.Label(parent, text="Create custom price formulas using mathematical expressions with metric variables.", 
                 font=('Segoe UI', 9)).pack(anchor='w', pady=(0, 5))
        
        # Variable reference
        ref_frame = ttk.LabelFrame(parent, text=" Available Variables ", padding="10")
        ref_frame.pack(fill='x', pady=(0, 10))
        
        # Create grid of variable references
        ref_grid = ttk.Frame(ref_frame)
        ref_grid.pack(fill='x')
        
        row = 0
        col = 0
        for metric, abbrev in METRIC_ABBREVS.items():
            label_text = f"{abbrev} = {METRIC_LABELS[metric]}"
            ttk.Label(ref_grid, text=label_text, font=('Consolas', 9)).grid(row=row, column=col, sticky='w', padx=10, pady=1)
            col += 1
            if col >= 3:
                col = 0
                row += 1
        
        # Operators section
        ops_frame = ttk.LabelFrame(parent, text=" Operators & Functions ", padding="10")
        ops_frame.pack(fill='x', pady=(0, 10))
        
        ttk.Label(ops_frame, text="Math:  +  -  *  /  ( )", font=('Consolas', 9)).pack(anchor='w')
        ttk.Label(ops_frame, text="Compare:  <  >  <=  >=  ==  !=", font=('Consolas', 9)).pack(anchor='w')
        ttk.Label(ops_frame, text="Functions:", font=('Consolas', 9, 'bold')).pack(anchor='w', pady=(5, 0))
        ttk.Label(ops_frame, text="  min(a, b)  - Returns the smaller of two values", font=('Consolas', 9)).pack(anchor='w')
        ttk.Label(ops_frame, text="  max(a, b)  - Returns the larger of two values", font=('Consolas', 9)).pack(anchor='w')
        ttk.Label(ops_frame, text="  iif(condition, true_val, false_val)  - If condition true, return true_val, else false_val", font=('Consolas', 9)).pack(anchor='w')
        
        ttk.Label(ops_frame, text="Examples:", font=('Consolas', 9, 'bold'), foreground='blue').pack(anchor='w', pady=(5, 0))
        ttk.Label(ops_frame, text="  min((cur + 7dmed) / 2, cur)  - Break even, but never more than current price", font=('Consolas', 9, 'italic'), foreground='blue').pack(anchor='w')
        ttk.Label(ops_frame, text="  iif(7davg < cur, 7davg * 0.9, cur * 0.85)  - Use 7d avg if lower, else use current", font=('Consolas', 9, 'italic'), foreground='blue').pack(anchor='w')
        
        # Formula list
        list_frame = ttk.LabelFrame(parent, text=" Your Formulas ", padding="10")
        list_frame.pack(fill='both', expand=True, pady=(0, 10))
        
        # Group management toolbar
        group_toolbar = ttk.Frame(list_frame)
        group_toolbar.pack(fill='x', pady=(0, 5))
        
        ttk.Label(group_toolbar, text="Groups:").pack(side='left')
        ttk.Button(group_toolbar, text="➕ New Group", command=self.new_formula_group).pack(side='left', padx=(5, 0))
        ttk.Button(group_toolbar, text="✏️ Rename", command=self.rename_formula_group).pack(side='left', padx=(5, 0))
        ttk.Button(group_toolbar, text="🗑️ Delete Group", command=self.delete_formula_group).pack(side='left', padx=(5, 0))
        
        ttk.Separator(group_toolbar, orient='vertical').pack(side='left', fill='y', padx=10)
        
        ttk.Label(group_toolbar, text="Filter:").pack(side='left')
        self.formula_list_group_var = tk.StringVar(value='All Groups')
        self.formula_list_group_combo = ttk.Combobox(group_toolbar, textvariable=self.formula_list_group_var, 
                                                      state='readonly', width=15)
        self.formula_list_group_combo['values'] = ['All Groups'] + self.formula_groups
        self.formula_list_group_combo.pack(side='left', padx=(5, 0))
        self.formula_list_group_combo.bind('<<ComboboxSelected>>', lambda e: self.refresh_formula_list())
        
        # Formula toolbar
        toolbar = ttk.Frame(list_frame)
        toolbar.pack(fill='x', pady=(5, 5))
        
        ttk.Button(toolbar, text="➕ New Formula", command=self.new_formula).pack(side='left')
        ttk.Button(toolbar, text="✏️ Edit Selected", command=self.edit_formula).pack(side='left', padx=(5, 0))
        ttk.Button(toolbar, text="🗑️ Delete Selected", command=self.delete_formula).pack(side='left', padx=(5, 0))
        ttk.Button(toolbar, text="📋 Duplicate", command=self.duplicate_formula).pack(side='left', padx=(5, 0))
        ttk.Button(toolbar, text="🧪 Test Selected", command=self.test_formula).pack(side='left', padx=(5, 0))
        
        # Formula listbox
        listbox_frame = ttk.Frame(list_frame)
        listbox_frame.pack(fill='both', expand=True)
        
        self.formula_listbox = tk.Listbox(listbox_frame, height=6, font=('Segoe UI', 10))
        scrollbar = ttk.Scrollbar(listbox_frame, orient="vertical", command=self.formula_listbox.yview)
        self.formula_listbox.configure(yscrollcommand=scrollbar.set)
        
        self.formula_listbox.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        self.formula_listbox.bind('<<ListboxSelect>>', self.on_formula_select)
        
        # Formula details
        details_frame = ttk.LabelFrame(parent, text=" Formula Details ", padding="10")
        details_frame.pack(fill='x', pady=(0, 10))
        
        self.formula_details_var = tk.StringVar(value="Select a formula to view details")
        ttk.Label(details_frame, textvariable=self.formula_details_var, font=('Consolas', 9), wraplength=800, justify='left').pack(anchor='w')
        
        # Refresh formula list
        self.refresh_formula_list()
    
    def create_predictions_tab(self, parent):
        """Create the predictions tab content"""
        # =====================
        # METAL SELECTION
        # =====================
        select_frame = ttk.LabelFrame(parent, text=" Metal Selection ", padding="10")
        select_frame.pack(fill='x', pady=(0, 10))
        
        select_grid = ttk.Frame(select_frame)
        select_grid.pack(fill='x')
        
        # Primary metal (the one we're predicting)
        ttk.Label(select_grid, text="Predict price for:").grid(row=0, column=0, sticky='e', padx=(0, 5), pady=5)
        self.pred_primary_var = tk.StringVar(value='Silver')
        pred_primary_combo = ttk.Combobox(select_grid, textvariable=self.pred_primary_var, state='readonly', width=12)
        pred_primary_combo['values'] = list(METALS.keys())
        pred_primary_combo.grid(row=0, column=1, sticky='w', pady=5)
        pred_primary_combo.bind('<<ComboboxSelected>>', self.on_pred_primary_change)
        
        # Secondary metal/index (for ratio comparison)
        ttk.Label(select_grid, text="Compare ratio against:").grid(row=0, column=2, sticky='e', padx=(20, 5), pady=5)
        self.pred_secondary_var = tk.StringVar(value='S&P 500')  # Default: best in-range pairing for Silver
        self.pred_secondary_combo = ttk.Combobox(select_grid, textvariable=self.pred_secondary_var, state='readonly', width=12)
        self.pred_secondary_combo['values'] = list(PREDICTION_SECONDARIES.keys())
        self.pred_secondary_combo.grid(row=0, column=3, sticky='w', pady=5)
        
        # Fetch button
        self.pred_fetch_btn = ttk.Button(select_grid, text="📊 Fetch Prediction Data", command=self.fetch_prediction_data_thread)
        self.pred_fetch_btn.grid(row=0, column=4, padx=(20, 0), pady=5)
        
        # Save prediction button
        self.pred_save_btn = ttk.Button(select_grid, text="💾 Save Prediction", command=self.save_current_prediction, state='disabled')
        self.pred_save_btn.grid(row=0, column=5, padx=(5, 0), pady=5)

        # Back Test button with months selector
        self.backtest_months_var = tk.StringVar(value='12')
        backtest_months_combo = ttk.Combobox(select_grid, textvariable=self.backtest_months_var,
                                              state='readonly', width=4)
        backtest_months_combo['values'] = [str(m) for m in range(6, 61)]
        backtest_months_combo.grid(row=0, column=6, padx=(10, 0), pady=5)
        ttk.Label(select_grid, text="mo", font=('Segoe UI', 8)).grid(row=0, column=7, sticky='w', padx=(1, 0), pady=5)
        self.pred_backtest_btn = ttk.Button(select_grid, text="📉 Back Test", command=self.run_backtest_thread)
        self.pred_backtest_btn.grid(row=0, column=8, padx=(2, 0), pady=5)
        
        self.pred_status_var = tk.StringVar(value="Select metals and click 'Fetch Prediction Data'")
        ttk.Label(select_frame, textvariable=self.pred_status_var, foreground="gray", font=('Segoe UI', 9)).pack(anchor='w', pady=(5, 0))
        ttk.Label(select_frame, text="Tip: For Silver, S&P 500 has best in-range rate (~66%); use the band, not up/down.", foreground="gray", font=('Segoe UI', 8)).pack(anchor='w', pady=(2, 0))
        
        # =====================
        # PREDICTION RESULTS (lead with range — backtest: range is best use, direction/level weak)
        # =====================
        results_frame = ttk.LabelFrame(parent, text=" 7-Day Outlook ", padding="10")
        results_frame.pack(fill='x', pady=(0, 10))
        
        # ---- 7-day likely band (primary output; backtest ~64% in-range) ----
        band_frame = ttk.Frame(results_frame)
        band_frame.pack(fill='x', pady=(0, 5))
        ttk.Label(band_frame, text="Likely band (1 week):", font=('Segoe UI', 11, 'bold')).pack(side='left')
        self.pred_range_low_var = tk.StringVar(value="--")
        self.pred_range_high_var = tk.StringVar(value="--")
        ttk.Label(band_frame, textvariable=self.pred_range_low_var, font=('Segoe UI', 12, 'bold'), foreground='#CC0000').pack(side='left', padx=(10, 5))
        ttk.Label(band_frame, text=" to ", font=('Segoe UI', 10)).pack(side='left')
        ttk.Label(band_frame, textvariable=self.pred_range_high_var, font=('Segoe UI', 12, 'bold'), foreground='#008000').pack(side='left', padx=(0, 8))
        ttk.Label(band_frame, text="per gram", font=('Segoe UI', 9), foreground='gray').pack(side='left')
        ttk.Label(band_frame, text="  (backtest: price inside band ~64% of the time)", font=('Segoe UI', 8), foreground='gray').pack(side='left', padx=(8, 0))
        
        # Reference level (point estimate — backtest ~5% avg error; use band for planning)
        pred_display = ttk.Frame(results_frame)
        pred_display.pack(fill='x', pady=(2, 2))
        ttk.Label(pred_display, text="Reference level (center):", font=('Segoe UI', 9)).pack(side='left')
        self.pred_price_var = tk.StringVar(value="--")
        ttk.Label(pred_display, textvariable=self.pred_price_var, font=('Segoe UI', 12, 'bold'), foreground='#0066CC').pack(side='left', padx=(8, 5))
        ttk.Label(pred_display, text="per gram", font=('Segoe UI', 8), foreground='gray').pack(side='left')
        ttk.Label(pred_display, text="  (point forecast ~5% avg error)", font=('Segoe UI', 8), foreground='gray').pack(side='left', padx=(5, 0))
        
        # Implied change (not a reliable direction signal — backtest ~50%)
        change_frame = ttk.Frame(results_frame)
        change_frame.pack(fill='x', pady=(0, 8))
        ttk.Label(change_frame, text="Implied change:", font=('Segoe UI', 9)).pack(side='left')
        self.pred_change_var = tk.StringVar(value="--")
        self.pred_change_label = ttk.Label(change_frame, textvariable=self.pred_change_var, font=('Segoe UI', 10, 'bold'))
        self.pred_change_label.pack(side='left', padx=(8, 0))
        ttk.Label(change_frame, text="  (do not use as up/down signal — backtest ~50% direction accuracy)", font=('Segoe UI', 8), foreground='gray').pack(side='left', padx=(5, 0))
        
        # Confidence meter
        conf_frame = ttk.Frame(results_frame)
        conf_frame.pack(fill='x', pady=(0, 5))
        
        ttk.Label(conf_frame, text="Confidence:").pack(side='left')
        self.pred_confidence_var = tk.StringVar(value="--")
        ttk.Label(conf_frame, textvariable=self.pred_confidence_var, font=('Segoe UI', 11, 'bold')).pack(side='left', padx=(10, 0))
        
        self.confidence_bar = ttk.Progressbar(conf_frame, length=200, mode='determinate', value=0)
        self.confidence_bar.pack(side='left', padx=(15, 0))
        
        # Prediction breakdown - use Text widget with fixed height
        breakdown_frame = ttk.LabelFrame(results_frame, text=" Prediction Breakdown ", padding="5")
        breakdown_frame.pack(fill='x', pady=(10, 0))
        
        self.pred_breakdown_text = tk.Text(breakdown_frame, font=('Consolas', 9), height=8, 
                                           wrap='word', state='disabled', bg='#f5f5f5', relief='flat')
        self.pred_breakdown_text.pack(fill='x', expand=False)
        self._set_breakdown_text("Fetch data to see prediction breakdown")
        
        # =====================
        # TECHNICAL INDICATORS
        # =====================
        indicators_frame = ttk.LabelFrame(parent, text=" Technical Indicators ", padding="10")
        indicators_frame.pack(fill='x', pady=(0, 10))
        
        ind_grid = ttk.Frame(indicators_frame)
        ind_grid.pack(fill='x')
        
        # Row 1: Metal Ratio
        ttk.Label(ind_grid, text="Metal Ratio:", font=('Segoe UI', 9, 'bold')).grid(row=0, column=0, sticky='e', padx=(0, 10), pady=5)
        self.pred_ratio_var = tk.StringVar(value="--")
        ttk.Label(ind_grid, textvariable=self.pred_ratio_var, font=('Segoe UI', 10)).grid(row=0, column=1, sticky='w', pady=5)
        
        ttk.Label(ind_grid, text="Ratio Trend:", font=('Segoe UI', 9, 'bold')).grid(row=0, column=2, sticky='e', padx=(30, 10), pady=5)
        self.pred_ratio_trend_var = tk.StringVar(value="--")
        ttk.Label(ind_grid, textvariable=self.pred_ratio_trend_var, font=('Segoe UI', 10)).grid(row=0, column=3, sticky='w', pady=5)
        
        # Row 2: RSI
        ttk.Label(ind_grid, text="RSI (14-day):", font=('Segoe UI', 9, 'bold')).grid(row=1, column=0, sticky='e', padx=(0, 10), pady=5)
        self.pred_rsi_var = tk.StringVar(value="--")
        ttk.Label(ind_grid, textvariable=self.pred_rsi_var, font=('Segoe UI', 10)).grid(row=1, column=1, sticky='w', pady=5)
        
        ttk.Label(ind_grid, text="RSI Signal:", font=('Segoe UI', 9, 'bold')).grid(row=1, column=2, sticky='e', padx=(30, 10), pady=5)
        self.pred_rsi_signal_var = tk.StringVar(value="--")
        self.pred_rsi_signal_label = ttk.Label(ind_grid, textvariable=self.pred_rsi_signal_var, font=('Segoe UI', 10, 'bold'))
        self.pred_rsi_signal_label.grid(row=1, column=3, sticky='w', pady=5)
        
        # Row 3: ATR
        ttk.Label(ind_grid, text="ATR (14-day):", font=('Segoe UI', 9, 'bold')).grid(row=2, column=0, sticky='e', padx=(0, 10), pady=5)
        self.pred_atr_var = tk.StringVar(value="--")
        ttk.Label(ind_grid, textvariable=self.pred_atr_var, font=('Segoe UI', 10)).grid(row=2, column=1, sticky='w', pady=5)
        
        ttk.Label(ind_grid, text="Volatility:", font=('Segoe UI', 9, 'bold')).grid(row=2, column=2, sticky='e', padx=(30, 10), pady=5)
        self.pred_volatility_var = tk.StringVar(value="--")
        ttk.Label(ind_grid, textvariable=self.pred_volatility_var, font=('Segoe UI', 10)).grid(row=2, column=3, sticky='w', pady=5)
        
        # Row 4: Momentum
        ttk.Label(ind_grid, text="7d Momentum:", font=('Segoe UI', 9, 'bold')).grid(row=3, column=0, sticky='e', padx=(0, 10), pady=5)
        self.pred_momentum_7d_var = tk.StringVar(value="--")
        ttk.Label(ind_grid, textvariable=self.pred_momentum_7d_var, font=('Segoe UI', 10)).grid(row=3, column=1, sticky='w', pady=5)
        
        ttk.Label(ind_grid, text="14d Momentum:", font=('Segoe UI', 9, 'bold')).grid(row=3, column=2, sticky='e', padx=(30, 10), pady=5)
        self.pred_momentum_14d_var = tk.StringVar(value="--")
        ttk.Label(ind_grid, textvariable=self.pred_momentum_14d_var, font=('Segoe UI', 10)).grid(row=3, column=3, sticky='w', pady=5)
        
        # Row 5: Beta and Correlation
        ttk.Label(ind_grid, text="Dynamic Beta:", font=('Segoe UI', 9, 'bold')).grid(row=4, column=0, sticky='e', padx=(0, 10), pady=5)
        self.pred_beta_var = tk.StringVar(value="--")
        ttk.Label(ind_grid, textvariable=self.pred_beta_var, font=('Segoe UI', 10)).grid(row=4, column=1, sticky='w', pady=5)
        
        ttk.Label(ind_grid, text="Correlation:", font=('Segoe UI', 9, 'bold')).grid(row=4, column=2, sticky='e', padx=(30, 10), pady=5)
        self.pred_correlation_var = tk.StringVar(value="--")
        ttk.Label(ind_grid, textvariable=self.pred_correlation_var, font=('Segoe UI', 10)).grid(row=4, column=3, sticky='w', pady=5)

        # Market condition note
        note_frame = ttk.Frame(indicators_frame)
        note_frame.pack(fill='x', pady=(10, 0))
        ttk.Separator(note_frame, orient='horizontal').pack(fill='x', pady=(0, 5))
        note_text = (
            "Market Condition Notes:\n"
            "  \u2022 Silver/Platinum pair is best suited for bull or bear markets\n"
            "  \u2022 Silver/S&P 500 pair is best suited for sideways markets"
        )
        ttk.Label(note_frame, text=note_text, font=('Segoe UI', 8, 'italic'),
                  foreground='gray', justify='left').pack(anchor='w')

        # Current price reference (range band is shown at top of 7-Day Outlook)
        range_frame = ttk.LabelFrame(parent, text=" Reference ", padding="10")
        range_frame.pack(fill='x', pady=(0, 10))
        range_grid = ttk.Frame(range_frame)
        range_grid.pack(fill='x')
        ttk.Label(range_grid, text="Current price:", font=('Segoe UI', 9)).grid(row=0, column=0, sticky='e', padx=(0, 10), pady=5)
        self.pred_current_var = tk.StringVar(value="--")
        ttk.Label(range_grid, textvariable=self.pred_current_var, font=('Segoe UI', 10)).grid(row=0, column=1, sticky='w', pady=5)
        
        # =====================
        # PREDICTION HISTORY & GRADING
        # =====================
        history_frame = ttk.LabelFrame(parent, text=" Prediction History & Accuracy ", padding="10")
        history_frame.pack(fill='both', expand=True, pady=(0, 10))
        
        # Toolbar
        history_toolbar = ttk.Frame(history_frame)
        history_toolbar.pack(fill='x', pady=(0, 5))
        
        ttk.Button(history_toolbar, text="📈 Grade Predictions", command=self.grade_predictions_thread).pack(side='left')
        ttk.Button(history_toolbar, text="🗑️ Delete Selected", command=self.delete_selected_prediction).pack(side='left', padx=(5, 0))
        ttk.Button(history_toolbar, text="🗑️ Clear All", command=self.clear_prediction_history).pack(side='left', padx=(5, 0))
        
        self.pred_history_status_var = tk.StringVar(value="")
        ttk.Label(history_toolbar, textvariable=self.pred_history_status_var, foreground="gray", font=('Segoe UI', 8)).pack(side='left', padx=(10, 0))
        
        # Accuracy summary
        accuracy_frame = ttk.Frame(history_frame)
        accuracy_frame.pack(fill='x', pady=(5, 10))
        
        ttk.Label(accuracy_frame, text="Model Accuracy:", font=('Segoe UI', 10, 'bold')).pack(side='left')
        self.pred_accuracy_var = tk.StringVar(value="No graded predictions yet")
        ttk.Label(accuracy_frame, textvariable=self.pred_accuracy_var, font=('Segoe UI', 10)).pack(side='left', padx=(10, 0))
        
        # History listbox with scrollbar - use fixed height frame
        list_frame = ttk.Frame(history_frame, height=150)
        list_frame.pack(fill='both', expand=True)
        list_frame.pack_propagate(False)  # Prevent frame from shrinking to fit contents
        
        self.pred_history_listbox = tk.Listbox(list_frame, font=('Consolas', 9), 
                                                selectmode=tk.SINGLE, exportselection=False)
        history_scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.pred_history_listbox.yview)
        self.pred_history_listbox.configure(yscrollcommand=history_scrollbar.set)
        
        self.pred_history_listbox.pack(side='left', fill='both', expand=True)
        history_scrollbar.pack(side='right', fill='y')
        
        # Refresh history display
        self.refresh_prediction_history_display()
        
        # =====================
        # DISCLAIMER (backtest-informed)
        # =====================
        ttk.Label(parent, text="⚠️ Use the band for planning, not the direction or exact level. Backtests: direction ~50% (coin flip); "
                              "point forecast ~5% avg error; price falls inside the band ~64% of the time. Not financial advice.",
                 foreground="gray", font=('Segoe UI', 8), wraplength=800).pack(anchor='w', pady=(10, 0))

    def create_inventory_tab(self, parent):
        """Create the inventory tab content"""
        # =====================
        # ADD ITEM SECTION
        # =====================
        add_frame = ttk.LabelFrame(parent, text=" Add New Item ", padding="10")
        add_frame.pack(fill='x', pady=(0, 10))
        
        # Input grid
        input_grid = ttk.Frame(add_frame)
        input_grid.pack(fill='x')
        
        # Row 1
        ttk.Label(input_grid, text="Item ID:").grid(row=0, column=0, sticky='e', padx=(0, 5), pady=3)
        self.inv_id_entry = ttk.Entry(input_grid, width=15)
        self.inv_id_entry.grid(row=0, column=1, sticky='w', pady=3)
        
        ttk.Label(input_grid, text="Metal:").grid(row=0, column=2, sticky='e', padx=(15, 5), pady=3)
        self.inv_metal_var = tk.StringVar(value=self.current_metal)
        inv_metal_combo = ttk.Combobox(input_grid, textvariable=self.inv_metal_var, state='readonly', width=10)
        inv_metal_combo['values'] = list(METALS.keys())
        inv_metal_combo.grid(row=0, column=3, sticky='w', pady=3)
        
        ttk.Label(input_grid, text="Description:").grid(row=0, column=4, sticky='e', padx=(15, 5), pady=3)
        self.inv_desc_entry = ttk.Entry(input_grid, width=20)
        self.inv_desc_entry.grid(row=0, column=5, sticky='w', pady=3)
        
        # Row 2
        ttk.Label(input_grid, text="Weight:").grid(row=1, column=0, sticky='e', padx=(0, 5), pady=3)
        self.inv_weight_entry = ttk.Entry(input_grid, width=15)
        self.inv_weight_entry.grid(row=1, column=1, sticky='w', pady=3)
        
        ttk.Label(input_grid, text="Unit:").grid(row=1, column=2, sticky='e', padx=(15, 5), pady=3)
        self.inv_weight_unit_var = tk.StringVar(value="grams")
        inv_weight_unit_combo = ttk.Combobox(input_grid, textvariable=self.inv_weight_unit_var, state='readonly', width=10)
        inv_weight_unit_combo['values'] = ['grams', 'oz', 'lb']
        inv_weight_unit_combo.grid(row=1, column=3, sticky='w', pady=3)
        
        ttk.Label(input_grid, text="Purity (%):").grid(row=1, column=4, sticky='e', padx=(15, 5), pady=3)
        self.inv_purity_entry = ttk.Entry(input_grid, width=10)
        self.inv_purity_entry.insert(0, "92.5")
        self.inv_purity_entry.grid(row=1, column=5, sticky='w', pady=3)
        
        # Row 3
        ttk.Label(input_grid, text="Purchase Price ($):").grid(row=2, column=0, sticky='e', padx=(0, 5), pady=3)
        self.inv_price_entry = ttk.Entry(input_grid, width=15)
        self.inv_price_entry.grid(row=2, column=1, sticky='w', pady=3)
        
        ttk.Label(input_grid, text="Profit Goal (%):").grid(row=2, column=2, sticky='e', padx=(15, 5), pady=3)
        self.inv_goal_entry = ttk.Entry(input_grid, width=10)
        self.inv_goal_entry.insert(0, "100")
        self.inv_goal_entry.grid(row=2, column=3, sticky='w', pady=3)
        
        # Add button
        ttk.Button(add_frame, text="➕ Add to Inventory", command=self.add_inventory_item).pack(pady=(10, 0))
        
        # =====================
        # INVENTORY LIST
        # =====================
        list_frame = ttk.LabelFrame(parent, text=" Inventory Items ", padding="10")
        list_frame.pack(fill='both', expand=True, pady=(0, 10))
        
        # Toolbar
        toolbar = ttk.Frame(list_frame)
        toolbar.pack(fill='x', pady=(0, 5))
        
        # Fetch prices button for inventory
        self.inv_fetch_btn = ttk.Button(toolbar, text="💰 Fetch All Metal Prices", command=self.fetch_inventory_prices_thread)
        self.inv_fetch_btn.pack(side='left')
        
        self.inv_status_label = ttk.Label(toolbar, text="", foreground="gray", font=('Segoe UI', 8))
        self.inv_status_label.pack(side='left', padx=(5, 10))
        
        ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=5)
        
        ttk.Button(toolbar, text="🔄 Refresh Display", command=self.refresh_inventory_display).pack(side='left')
        ttk.Button(toolbar, text="✏️ Edit", command=self.edit_selected_item).pack(side='left', padx=(5, 0))
        ttk.Button(toolbar, text="🗑️ Delete", command=self.delete_selected_item).pack(side='left', padx=(5, 0))
        ttk.Button(toolbar, text="📁 Export CSV", command=self.export_inventory_csv).pack(side='left', padx=(5, 0))
        
        # Sort dropdown
        sort_frame = ttk.Frame(toolbar)
        sort_frame.pack(side='left', padx=(15, 0))
        ttk.Label(sort_frame, text="Sort by:").pack(side='left')
        self.sort_var = tk.StringVar(value="date_desc")
        sort_combo = ttk.Combobox(sort_frame, textvariable=self.sort_var, state='readonly', width=18)
        sort_combo['values'] = (
            "date_desc", "date_asc",
            "profit_pct_desc", "profit_pct_asc",
            "goal_pct_desc", "goal_pct_asc",
            "value_desc", "value_asc",
            "metal_asc", "metal_desc",
            "id_asc", "id_desc"
        )
        sort_combo.pack(side='left', padx=(5, 0))
        sort_combo.bind('<<ComboboxSelected>>', lambda e: self.refresh_inventory_display())
        
        # Filter by metal
        filter_frame = ttk.Frame(toolbar)
        filter_frame.pack(side='left', padx=(15, 0))
        ttk.Label(filter_frame, text="Filter:").pack(side='left')
        self.filter_var = tk.StringVar(value="All Metals")
        filter_combo = ttk.Combobox(filter_frame, textvariable=self.filter_var, state='readonly', width=12)
        filter_combo['values'] = ['All Metals'] + list(METALS.keys())
        filter_combo.pack(side='left', padx=(5, 0))
        filter_combo.bind('<<ComboboxSelected>>', lambda e: self.refresh_inventory_display())
        
        # Summary label
        self.inv_summary_var = tk.StringVar(value="")
        ttk.Label(toolbar, textvariable=self.inv_summary_var, font=('Segoe UI', 9, 'bold')).pack(side='right')
        
        # Scrollable frame for inventory items
        canvas_frame = ttk.Frame(list_frame)
        canvas_frame.pack(fill='both', expand=True)
        
        self.inv_canvas = tk.Canvas(canvas_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.inv_canvas.yview)
        self.inv_scrollable_frame = ttk.Frame(self.inv_canvas)
        
        self.inv_scrollable_frame.bind(
            "<Configure>",
            lambda e: self.inv_canvas.configure(scrollregion=self.inv_canvas.bbox("all"))
        )
        
        self.inv_canvas.create_window((0, 0), window=self.inv_scrollable_frame, anchor="nw")
        self.inv_canvas.configure(yscrollcommand=scrollbar.set)
        
        self.inv_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Bind mousewheel
        self.inv_canvas.bind_all("<MouseWheel>", lambda e: self.inv_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        
        # Track selected item
        self.selected_item_id = None
        
        # Initial display
        self.refresh_inventory_display()
        
    def create_settings_tab(self, parent):
        """Create the settings tab"""
        # =====================
        # DEFAULTS
        # =====================
        defaults_frame = ttk.LabelFrame(parent, text=" Default Settings ", padding="10")
        defaults_frame.pack(fill='x', pady=(0, 10))
        
        grid = ttk.Frame(defaults_frame)
        grid.pack(fill='x')
        
        # Default metal
        ttk.Label(grid, text="Default Metal:").grid(row=0, column=0, sticky='e', padx=(0, 10), pady=5)
        self.default_metal_var = tk.StringVar(value=self.settings.get('default_metal', 'Silver'))
        default_metal_combo = ttk.Combobox(grid, textvariable=self.default_metal_var, state='readonly', width=15)
        default_metal_combo['values'] = list(METALS.keys())
        default_metal_combo.grid(row=0, column=1, sticky='w', pady=5)
        
        # Default unit
        ttk.Label(grid, text="Default Unit:").grid(row=1, column=0, sticky='e', padx=(0, 10), pady=5)
        self.default_unit_var = tk.StringVar(value=self.settings.get('default_unit', 'gram'))
        default_unit_combo = ttk.Combobox(grid, textvariable=self.default_unit_var, state='readonly', width=15)
        default_unit_combo['values'] = list(UNITS.keys())
        default_unit_combo.grid(row=1, column=1, sticky='w', pady=5)
        
        # =====================
        # SALES TAX
        # =====================
        tax_frame = ttk.LabelFrame(parent, text=" Sales Tax ", padding="10")
        tax_frame.pack(fill='x', pady=(0, 10))
        
        ttk.Label(tax_frame, text="Note: Many states exempt precious metals from sales tax. Check your local laws.", 
                 foreground="gray", font=('Segoe UI', 8)).pack(anchor='w', pady=(0, 10))
        
        tax_grid = ttk.Frame(tax_frame)
        tax_grid.pack(fill='x')
        
        ttk.Label(tax_grid, text="State:").grid(row=0, column=0, sticky='e', padx=(0, 10), pady=5)
        tax_state_combo = ttk.Combobox(tax_grid, textvariable=self.tax_state_var, state='readonly', width=25)
        tax_state_combo['values'] = list(STATE_TAX_RATES.keys())
        tax_state_combo.grid(row=0, column=1, sticky='w', pady=5)
        tax_state_combo.bind('<<ComboboxSelected>>', self.on_tax_state_change)
        
        ttk.Label(tax_grid, text="Custom Rate (%):").grid(row=1, column=0, sticky='e', padx=(0, 10), pady=5)
        self.custom_tax_entry = ttk.Entry(tax_grid, textvariable=self.custom_tax_var, width=10)
        self.custom_tax_entry.grid(row=1, column=1, sticky='w', pady=5)
        
        # Enable/disable custom entry based on current selection
        if self.tax_state_var.get() == 'Custom...':
            self.custom_tax_entry.config(state='normal')
        else:
            self.custom_tax_entry.config(state='disabled')
        
        # Current tax rate display
        self.current_tax_var = tk.StringVar(value="Current tax rate: 0%")
        ttk.Label(tax_grid, textvariable=self.current_tax_var, font=('Segoe UI', 10, 'bold')).grid(row=2, column=0, columnspan=2, sticky='w', pady=(10, 0))
        
        self.update_tax_display()
        
        # =====================
        # SAVE BUTTON
        # =====================
        ttk.Button(parent, text="💾 Save Settings", command=self.save_all_settings).pack(pady=20)
        
        # =====================
        # DATA MANAGEMENT
        # =====================
        data_frame = ttk.LabelFrame(parent, text=" Data Management ", padding="10")
        data_frame.pack(fill='x', pady=(0, 10))
        
        ttk.Label(data_frame, text=f"Data location: {self.get_app_data_path()}", foreground="gray", font=('Segoe UI', 8)).pack(anchor='w', pady=(0, 10))
        
        btn_frame = ttk.Frame(data_frame)
        btn_frame.pack(fill='x')
        
        ttk.Button(btn_frame, text="📂 Open Data Folder", command=self.open_data_folder).pack(side='left')
        ttk.Button(btn_frame, text="🔄 Reset Formulas to Default", command=self.reset_formulas).pack(side='left', padx=(10, 0))
    
    # =========================================================================
    # EVENT HANDLERS
    # =========================================================================
    
    def on_metal_change(self, event=None):
        """Handle metal selection change"""
        self.current_metal = self.metal_var.get()
        # Clear metrics when metal changes
        self.metrics = {}
        for var in self.metric_vars.values():
            var.set("--")
        self.refresh_calculated_prices_display()
        self.update_purity_options()
        self.timestamp_label.config(text=f"Selected {self.current_metal} - Click 'Fetch Live Prices' to update")
    
    def update_purity_options(self):
        """Update purity dropdown based on selected metal"""
        grades = PURITY_GRADES.get(self.current_metal, PURITY_GRADES['Silver'])
        self.purity_combo['values'] = [g[0] for g in grades]
        # Set to first option (typically the purest)
        if grades:
            self.purity_var.set(grades[0][0])
        # Hide custom entry
        self.custom_purity_entry.grid_forget()
        self.custom_purity_label.grid_forget()
    
    def on_unit_change(self, event=None):
        """Handle unit selection change"""
        self.current_unit = self.unit_var.get()
        self.refresh_metrics_display()
        self.refresh_calculated_prices_display()
    
    def on_formula_group_change(self, event=None):
        """Handle formula group selection change"""
        self.selected_formula_group = self.formula_group_var.get()
        # Save preference
        self.settings['selected_formula_group'] = self.selected_formula_group
        self.save_settings()
        self.refresh_calculated_prices_display()
    
    def update_formula_group_dropdown(self):
        """Update the formula group dropdown values"""
        groups = ['All Groups'] + self.formula_groups
        if hasattr(self, 'formula_group_combo'):
            self.formula_group_combo['values'] = groups
            if self.formula_group_var.get() not in groups:
                self.formula_group_var.set('All Groups')
        # Also update formula builder dropdown if it exists
        if hasattr(self, 'formula_list_group_combo'):
            self.formula_list_group_combo['values'] = groups
    
    def on_purity_change(self, event=None):
        """Handle purity selection change"""
        purity = self.purity_var.get()
        if purity == 'Custom...':
            self.custom_purity_entry.grid(row=0, column=2, sticky='w', padx=(5, 0), pady=5)
            self.custom_purity_label.grid(row=0, column=3, sticky='w', pady=5)
            self.custom_purity_entry.focus_set()
        else:
            self.custom_purity_entry.grid_forget()
            self.custom_purity_label.grid_forget()
    
    def on_tax_state_change(self, event=None):
        """Handle tax state selection change"""
        state = self.tax_state_var.get()
        if state == 'Custom...':
            self.custom_tax_entry.config(state='normal')
        else:
            self.custom_tax_entry.config(state='disabled')
        self.update_tax_display()
    
    def on_formula_select(self, event=None):
        """Handle formula selection in listbox"""
        formula = self.get_selected_formula()
        if formula:
            # Build details string
            details = f"Name: {formula['name']}\n"
            details += f"Group: {formula.get('group', 'Default')}\n"
            details += f"Color: {formula.get('color', '#000000')}\n"
            details += f"Apply Tax: {'Yes' if formula.get('apply_tax', True) else 'No'}\n"
            if formula.get('description'):
                details += f"Description: {formula['description']}\n"
            details += f"\nExpression:\n{formula.get('expression', 'No expression defined')}"
            
            self.formula_details_var.set(details)
        else:
            self.formula_details_var.set("Select a formula to view details")
    
    def update_tax_display(self):
        """Update the current tax rate display"""
        rate = self.get_current_tax_rate()
        self.current_tax_var.set(f"Current tax rate: {rate}%")
        
        # Update tax info in calculator
        if rate > 0:
            multiplier = 1 - (rate / 100)
            self.tax_info_var.set(f"Tax adjustment: ×{multiplier:.4f} ({rate}% sales tax accounted for)")
        else:
            self.tax_info_var.set("No sales tax applied")
    
    def get_current_tax_rate(self):
        """Get the current tax rate"""
        state = self.tax_state_var.get()
        if state == 'Custom...':
            try:
                return float(self.custom_tax_var.get())
            except ValueError:
                return 0.0
        return STATE_TAX_RATES.get(state, 0.0)
    
    # =========================================================================
    # PRICE FETCHING
    # =========================================================================
    
    def fetch_prices_thread(self):
        """Start fetching prices in a separate thread"""
        self.fetch_btn.config(state='disabled')
        self.status_label.config(text="Connecting...")
        self.progress.pack(pady=(5, 0))
        self.progress.start(10)
        
        thread = threading.Thread(target=self.fetch_prices, daemon=True)
        thread.start()
    
    def fetch_prices(self):
        """Fetch prices for current metal with timeout and retry logic"""
        try:
            metal_config = METALS[self.current_metal]
            
            # Step 1: Fetch current spot price from gold-api.com (with timeout)
            self.update_status("Fetching current spot price...")
            current_price_oz = self.get_current_spot_price(metal_config['symbol'])
            
            if current_price_oz is None:
                # Fallback to Yahoo Finance with retry
                self.update_status("Primary API failed, trying backup...")
                current_price_oz = self.get_yf_current_price_with_retry(metal_config['yf_ticker'])
            
            if current_price_oz is None:
                self.fetch_error("Could not fetch current spot price.\n\nBoth price APIs failed to respond.\nPlease check your internet connection and try again.")
                return
            
            # Step 2: Fetch historical data from Yahoo Finance with retry
            self.update_status("Fetching historical data...")
            hist, error = self.fetch_yf_history_with_retry(
                metal_config['yf_ticker'],
                period="1y",
                timeout=30,
                max_retries=2
            )
            
            if error or hist is None or len(hist) < 7:
                error_msg = error if error else "No historical data returned"
                self.fetch_error(f"Could not fetch historical data.\n\n{error_msg}\n\nYahoo Finance may be temporarily unavailable.\nPlease try again in a moment.")
                return
            
            # Calculate all metrics (stored per gram as base unit)
            all_prices = [float(p) / TROY_OUNCE_TO_GRAMS for p in hist['Close']]
            
            # Current price
            self.metrics['current_price'] = current_price_oz / TROY_OUNCE_TO_GRAMS
            
            # 7-day metrics
            if len(all_prices) >= 7:
                last_7 = all_prices[-7:]
                self.metrics['7_day_avg'] = sum(last_7) / len(last_7)
                self.metrics['7_day_median'] = sorted(last_7)[len(last_7)//2]
                self.metrics['7_day_high'] = max(last_7)
                self.metrics['7_day_low'] = min(last_7)
            
            # 14-day metrics
            if len(all_prices) >= 14:
                last_14 = all_prices[-14:]
                self.metrics['14_day_avg'] = sum(last_14) / len(last_14)
                self.metrics['14_day_median'] = sorted(last_14)[len(last_14)//2]
            
            # 28-day metrics
            if len(all_prices) >= 28:
                last_28 = all_prices[-28:]
                self.metrics['28_day_avg'] = sum(last_28) / len(last_28)
                self.metrics['28_day_median'] = sorted(last_28)[len(last_28)//2]
            
            # 1-year average
            self.metrics['1_year_avg'] = sum(all_prices) / len(all_prices)
            
            # Update UI on main thread
            self.root.after(0, self.display_results)
            
        except Exception as e:
            self.fetch_error(f"Error fetching data:\n{str(e)}\n\nPlease try again.")
    
    def get_yf_current_price_with_retry(self, ticker, timeout=15, max_retries=2):
        """Get current price from Yahoo Finance with timeout and retry"""
        import concurrent.futures
        import time
        
        for attempt in range(max_retries):
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    def fetch():
                        stock = yf.Ticker(ticker)
                        data = stock.history(period="1d")
                        if not data.empty:
                            return float(data['Close'].iloc[-1])
                        return None
                    
                    future = executor.submit(fetch)
                    result = future.result(timeout=timeout)
                    if result is not None:
                        return result
                        
            except concurrent.futures.TimeoutError:
                print(f"YF current price timeout (attempt {attempt + 1}/{max_retries})")
            except Exception as e:
                print(f"YF current price error: {e}")
            
            if attempt < max_retries - 1:
                time.sleep(1)
        
        return None
    
    def get_current_spot_price(self, symbol):
        """Fetch current spot price from gold-api.com"""
        try:
            response = requests.get(f"{GOLD_API_BASE}/{symbol}", timeout=15)
            if response.status_code == 200:
                data = response.json()
                if "price" in data:
                    return float(data["price"])
        except Exception as e:
            print(f"gold-api.com error: {e}")
        return None
    
    def get_yf_current_price(self, ticker):
        """Fallback: get current price from Yahoo Finance"""
        try:
            stock = yf.Ticker(ticker)
            data = stock.history(period="1d")
            if not data.empty:
                return float(data['Close'].iloc[-1])
        except Exception as e:
            print(f"Yahoo Finance error: {e}")
        return None
    
    # =========================================================================
    # PREDICTION METHODS
    # =========================================================================
    
    def fetch_yf_history_with_retry(self, ticker_symbol, period="3mo", timeout=30, max_retries=2, start=None):
        """
        Fetch Yahoo Finance history with timeout and retry logic.

        Args:
            ticker_symbol: Yahoo Finance ticker (e.g., 'GC=F', 'SI=F')
            period: History period (e.g., '3mo', '1y') - used when start is None
            timeout: Timeout in seconds per attempt
            max_retries: Number of retry attempts
            start: Optional start date string ('YYYY-MM-DD'). If provided, period is ignored.

        Returns:
            tuple: (history_dataframe, error_message)
            - On success: (DataFrame, None)
            - On failure: (None, "error description")
        """
        import concurrent.futures

        last_error = None

        for attempt in range(max_retries):
            try:
                # Use ThreadPoolExecutor for timeout control
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    def fetch_data():
                        ticker = yf.Ticker(ticker_symbol)
                        if start:
                            return ticker.history(start=start)
                        return ticker.history(period=period)
                    
                    future = executor.submit(fetch_data)
                    
                    try:
                        hist = future.result(timeout=timeout)
                        
                        if hist is not None and not hist.empty:
                            return hist, None
                        else:
                            last_error = f"No data returned for {ticker_symbol}"
                            
                    except concurrent.futures.TimeoutError:
                        last_error = f"Timeout fetching {ticker_symbol} (attempt {attempt + 1}/{max_retries})"
                        
            except Exception as e:
                last_error = f"Error fetching {ticker_symbol}: {str(e)}"
            
            # Wait before retry (if not last attempt)
            if attempt < max_retries - 1:
                import time
                time.sleep(1)
        
        return None, last_error
    
    def on_pred_primary_change(self, event=None):
        """Auto-suggest secondary when primary changes"""
        primary = self.pred_primary_var.get()
        if primary in SUGGESTED_PAIRINGS:
            suggested = SUGGESTED_PAIRINGS[primary]
            self.pred_secondary_var.set(suggested)
    
    def fetch_prediction_data_thread(self):
        """Start fetching prediction data in a separate thread"""
        self.pred_fetch_btn.config(state='disabled')
        self.pred_status_var.set("Fetching data...")
        
        thread = threading.Thread(target=self.fetch_prediction_data, daemon=True)
        thread.start()
    
    def fetch_prediction_data(self):
        """Fetch price data for both metals/indices for prediction plus DXY"""
        errors = []
        
        try:
            primary_metal = self.pred_primary_var.get()
            secondary_name = self.pred_secondary_var.get()
            
            if primary_metal == secondary_name:
                self.root.after(0, lambda: messagebox.showwarning("Same Selection", "Please select two different items for ratio comparison."))
                self.root.after(0, lambda: self.pred_fetch_btn.config(state='normal'))
                self.root.after(0, lambda: self.pred_status_var.set("Select different items"))
                return
            
            # ===== Fetch primary metal =====
            self.root.after(0, lambda: self.pred_status_var.set(f"Fetching {primary_metal} data..."))
            
            primary_config = METALS[primary_metal]
            primary_hist, primary_err = self.fetch_yf_history_with_retry(
                primary_config['yf_ticker'], 
                period="3mo",
                timeout=30,
                max_retries=2
            )
            
            if primary_err:
                errors.append(f"{primary_metal}: {primary_err}")
                raise Exception(f"Could not fetch {primary_metal} data.\n\n{primary_err}")
            
            # ===== Fetch secondary =====
            self.root.after(0, lambda: self.pred_status_var.set(f"Fetching {secondary_name} data..."))
            
            secondary_config = PREDICTION_SECONDARIES[secondary_name]
            secondary_hist, secondary_err = self.fetch_yf_history_with_retry(
                secondary_config['yf_ticker'],
                period="3mo",
                timeout=30,
                max_retries=2
            )
            
            if secondary_err:
                errors.append(f"{secondary_name}: {secondary_err}")
                raise Exception(f"Could not fetch {secondary_name} data.\n\n{secondary_err}")
            
            # ===== Fetch DXY =====
            self.root.after(0, lambda: self.pred_status_var.set("Fetching DXY (US Dollar Index)..."))
            
            dxy_hist, dxy_err = self.fetch_yf_history_with_retry(
                DXY_TICKER,
                period="3mo",
                timeout=30,
                max_retries=2
            )
            
            if dxy_err:
                errors.append(f"DXY: {dxy_err}")
                raise Exception(f"Could not fetch DXY (US Dollar Index) data.\n\n{dxy_err}")
            
            # ===== Store primary metal data (convert to $/gram) =====
            self.prediction_data[primary_metal] = {
                'history': primary_hist,
                'closes': [float(p) / TROY_OUNCE_TO_GRAMS for p in primary_hist['Close']],
                'highs': [float(p) / TROY_OUNCE_TO_GRAMS for p in primary_hist['High']],
                'lows': [float(p) / TROY_OUNCE_TO_GRAMS for p in primary_hist['Low']],
            }
            
            # ===== Store secondary data =====
            if secondary_config['type'] == 'metal':
                self.prediction_data[secondary_name] = {
                    'history': secondary_hist,
                    'closes': [float(p) / TROY_OUNCE_TO_GRAMS for p in secondary_hist['Close']],
                    'highs': [float(p) / TROY_OUNCE_TO_GRAMS for p in secondary_hist['High']],
                    'lows': [float(p) / TROY_OUNCE_TO_GRAMS for p in secondary_hist['Low']],
                }
            else:
                self.prediction_data[secondary_name] = {
                    'history': secondary_hist,
                    'closes': [float(p) for p in secondary_hist['Close']],
                    'highs': [float(p) for p in secondary_hist['High']],
                    'lows': [float(p) for p in secondary_hist['Low']],
                }
            
            # ===== Store DXY data =====
            self.prediction_data['DXY'] = {
                'history': dxy_hist,
                'closes': [float(p) for p in dxy_hist['Close']],
            }
            
            # ===== S&P 500 for regime detection (20d MA) - reuse if secondary is S&P 500 =====
            if secondary_name == 'S&P 500':
                self.prediction_data['SP500_REGIME'] = {'closes': self.prediction_data['S&P 500']['closes']}
            else:
                self.root.after(0, lambda: self.pred_status_var.set("Fetching S&P 500 (regime)..."))
                sp_hist, sp_err = self.fetch_yf_history_with_retry(
                    SP500_TICKER_REGIME, period="3mo", timeout=30, max_retries=2
                )
                if not sp_err and sp_hist is not None:
                    self.prediction_data['SP500_REGIME'] = {
                        'closes': [float(p) for p in sp_hist['Close']],
                    }
                else:
                    self.prediction_data['SP500_REGIME'] = None  # regime unavailable

            # ===== Fetch VIX for crash detection =====
            self.root.after(0, lambda: self.pred_status_var.set("Fetching VIX (crash detection)..."))
            vix_hist, vix_err = self.fetch_yf_history_with_retry(
                VIX_TICKER, period="3mo", timeout=30, max_retries=2
            )
            if not vix_err and vix_hist is not None:
                self.prediction_data['VIX'] = {
                    'closes': [float(p) for p in vix_hist['Close']],
                }
            else:
                self.prediction_data['VIX'] = None

            # ===== Fetch Gold for GSR calculation (if not already primary/secondary) =====
            if primary_metal != 'Gold' and secondary_name != 'Gold':
                self.root.after(0, lambda: self.pred_status_var.set("Fetching Gold (GSR)..."))
                gold_hist, gold_err = self.fetch_yf_history_with_retry(
                    METALS['Gold']['yf_ticker'], period="3mo", timeout=30, max_retries=2
                )
                if not gold_err and gold_hist is not None:
                    self.prediction_data['Gold_GSR'] = {
                        'closes': [float(p) / TROY_OUNCE_TO_GRAMS for p in gold_hist['Close']],
                    }
                else:
                    self.prediction_data['Gold_GSR'] = None

            # ===== Fetch Silver for GSR calculation (if not already primary/secondary) =====
            if primary_metal != 'Silver' and secondary_name != 'Silver':
                self.root.after(0, lambda: self.pred_status_var.set("Fetching Silver (GSR)..."))
                silver_hist, silver_err = self.fetch_yf_history_with_retry(
                    METALS['Silver']['yf_ticker'], period="3mo", timeout=30, max_retries=2
                )
                if not silver_err and silver_hist is not None:
                    self.prediction_data['Silver_GSR'] = {
                        'closes': [float(p) / TROY_OUNCE_TO_GRAMS for p in silver_hist['Close']],
                    }
                else:
                    self.prediction_data['Silver_GSR'] = None
            
            # ===== Calculate all indicators and prediction =====
            self.root.after(0, lambda: self.pred_status_var.set("Calculating indicators..."))
            self.root.after(0, self.calculate_and_display_prediction)
            
        except Exception as e:
            def show_error():
                self.pred_fetch_btn.config(state='normal')
                self.pred_status_var.set("Fetch failed - click to retry")
                
                error_msg = str(e)
                if "Timeout" in error_msg:
                    error_msg += "\n\nYahoo Finance may be slow or temporarily unavailable.\nPlease try again in a moment."
                elif "No data" in error_msg:
                    error_msg += "\n\nThe market may be closed or data unavailable.\nPlease try again later."
                
                messagebox.showerror("Fetch Error", error_msg)
            self.root.after(0, show_error)
    
    def calculate_rsi(self, closes, period=14):
        """Calculate Relative Strength Index using Wilder's smoothed EMA"""
        if len(closes) < period + 1:
            return None
        
        # Calculate daily changes
        changes = []
        for i in range(1, len(closes)):
            changes.append(closes[i] - closes[i-1])
        
        if len(changes) < period:
            return None
        
        # Separate gains and losses
        gains = [max(c, 0) for c in changes]
        losses = [max(-c, 0) for c in changes]
        
        # Initialize with SMA for first 'period' values (seed the EMA)
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        # Apply Wilder's smoothing (EMA) for remaining values
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
        if avg_loss == 0:
            return 100  # No losses = RSI of 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def calculate_atr(self, highs, lows, closes, period=14):
        """Calculate Average True Range using Wilder's smoothed EMA"""
        if len(closes) < period + 1:
            return None
        
        true_ranges = []
        for i in range(1, len(closes)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i-1])
            low_close = abs(lows[i] - closes[i-1])
            tr = max(high_low, high_close, low_close)
            true_ranges.append(tr)
        
        if len(true_ranges) < period:
            return None
        
        # Initialize with SMA for first 'period' values (seed the EMA)
        atr = sum(true_ranges[:period]) / period
        
        # Apply Wilder's smoothing (EMA) for remaining values
        for i in range(period, len(true_ranges)):
            atr = (atr * (period - 1) + true_ranges[i]) / period
        
        return atr
    
    def calculate_momentum(self, closes, period=7):
        """Calculate momentum using log returns, displayed as percentage"""
        if len(closes) < period + 1:
            return None
        
        current = closes[-1]
        past = closes[-period-1]
        
        if past <= 0 or current <= 0:
            return None
        
        # Use log return for internal calculation
        log_return = math.log(current / past)
        
        # Convert to percentage for display: (e^log_return - 1) * 100
        momentum_pct = (math.exp(log_return) - 1) * 100
        return momentum_pct
    
    def _detect_crash_triggers(self, primary_metal):
        """
        Crash Detection System with 5 triggers. Returns (trigger_count, trigger_details).
        Triggers:
          1. VIX > 25
          2. Gold/Silver Ratio (GSR) > 85
          3. ATR% > 5%
          4. 3+ consecutive days with >2% daily moves
          5. DXY +1% AND metal -2% (5-day divergence)
        """
        triggers = []
        trigger_count = 0

        # Get primary data
        primary = self.prediction_data.get(primary_metal, {})
        primary_closes = primary.get('closes', [])

        # Trigger 1: VIX > 25
        vix_data = self.prediction_data.get('VIX')
        if vix_data and vix_data.get('closes'):
            vix_cur = vix_data['closes'][-1]
            if vix_cur > CRASH_VIX_THRESHOLD:
                trigger_count += 1
                triggers.append(f"VIX={vix_cur:.1f} > {CRASH_VIX_THRESHOLD}")
            else:
                triggers.append(f"VIX={vix_cur:.1f} OK")
        else:
            triggers.append("VIX: no data")

        # Trigger 2: GSR > 85
        gold_closes = None
        silver_closes = None
        # Try to get gold/silver data from various sources
        if 'Gold' in self.prediction_data:
            gold_closes = self.prediction_data['Gold'].get('closes', [])
        elif 'Gold_GSR' in self.prediction_data and self.prediction_data['Gold_GSR']:
            gold_closes = self.prediction_data['Gold_GSR'].get('closes', [])
        if 'Silver' in self.prediction_data:
            silver_closes = self.prediction_data['Silver'].get('closes', [])
        elif 'Silver_GSR' in self.prediction_data and self.prediction_data['Silver_GSR']:
            silver_closes = self.prediction_data['Silver_GSR'].get('closes', [])

        if gold_closes and silver_closes and silver_closes[-1] > 0:
            gsr = gold_closes[-1] / silver_closes[-1]
            if gsr > CRASH_GSR_THRESHOLD:
                trigger_count += 1
                triggers.append(f"GSR={gsr:.1f} > {CRASH_GSR_THRESHOLD}")
            else:
                triggers.append(f"GSR={gsr:.1f} OK")
        else:
            triggers.append("GSR: no data")

        # Trigger 3: ATR% > 5%
        primary_highs = primary.get('highs', [])
        primary_lows = primary.get('lows', [])
        atr_val = self.calculate_atr(primary_highs, primary_lows, primary_closes)
        if atr_val and len(primary_closes) > 0 and primary_closes[-1] > 0:
            atr_pct = (atr_val / primary_closes[-1]) * 100
            if atr_pct > CRASH_ATR_PCT_THRESHOLD:
                trigger_count += 1
                triggers.append(f"ATR%={atr_pct:.1f}% > {CRASH_ATR_PCT_THRESHOLD}%")
            else:
                triggers.append(f"ATR%={atr_pct:.1f}% OK")
        else:
            triggers.append("ATR%: no data")

        # Trigger 4: 3+ consecutive days with >2% daily moves
        if len(primary_closes) >= CRASH_CONSECUTIVE_DAYS + 1:
            consecutive = 0
            max_consecutive = 0
            for i in range(-CRASH_CONSECUTIVE_DAYS - 5, 0):
                if i - 1 >= -len(primary_closes) and primary_closes[i - 1] > 0:
                    daily_move = abs(primary_closes[i] / primary_closes[i - 1] - 1)
                    if daily_move > CRASH_CONSECUTIVE_MOVE:
                        consecutive += 1
                        max_consecutive = max(max_consecutive, consecutive)
                    else:
                        consecutive = 0
            if max_consecutive >= CRASH_CONSECUTIVE_DAYS:
                trigger_count += 1
                triggers.append(f"Consecutive={max_consecutive}d > {CRASH_CONSECUTIVE_DAYS}d")
            else:
                triggers.append(f"Consecutive={max_consecutive}d OK")
        else:
            triggers.append("Consecutive: no data")

        # Trigger 5: DXY +1% AND metal -2% (5-day divergence)
        dxy_data = self.prediction_data.get('DXY')
        if dxy_data and dxy_data.get('closes') and len(dxy_data['closes']) >= 6 and len(primary_closes) >= 6:
            dxy_closes = dxy_data['closes']
            dxy_5d_change = (dxy_closes[-1] / dxy_closes[-6]) - 1
            metal_5d_change = (primary_closes[-1] / primary_closes[-6]) - 1
            if dxy_5d_change >= CRASH_DXY_RISE and metal_5d_change <= CRASH_METAL_DROP:
                trigger_count += 1
                triggers.append(f"DXY={dxy_5d_change*100:+.1f}%/Metal={metal_5d_change*100:+.1f}% DIVERGE")
            else:
                triggers.append(f"DXY={dxy_5d_change*100:+.1f}%/Metal={metal_5d_change*100:+.1f}% OK")
        else:
            triggers.append("DXY/Metal divergence: no data")

        return trigger_count, triggers

    def _get_regime(self, primary_metal):
        """
        Classify market regime with 5 regimes.
        CRASH: 3/5 crash triggers active. Mean reversion to 20d MA, 30% reversion towards 50d MA.
        RECOVERY: 10 day buffer after crash. Mean reversion to 20d MA, 20% reversion towards 20d MA.
        SIDEWAYS: Primary RSI 45-55, 7d/14d SMA momentum, beta 1.0x.
        BULL: S&P 500 > 20d MA, 7d/14d SMA momentum, beta 1.0x.
        BEAR: S&P 500 < 20d MA, 7d/14d SMA momentum, beta 0.7x.
        Returns (regime_str, sp500_cur, sp500_ma, extra_info) where extra_info is a dict.
        """
        sp_data = self.prediction_data.get('SP500_REGIME') if self.prediction_data else None
        if not sp_data or not sp_data.get('closes'):
            return None, None, None, {}
        closes = sp_data['closes']
        if len(closes) < REGIME_MA_DAYS:
            return None, None, None, {}
        sp500_cur = closes[-1]
        sp500_ma = sum(closes[-REGIME_MA_DAYS:]) / REGIME_MA_DAYS

        extra_info = {}

        # Check for CRASH first (highest priority)
        crash_triggers, crash_details = self._detect_crash_triggers(primary_metal)
        extra_info['crash_triggers'] = crash_triggers
        extra_info['crash_details'] = crash_details

        if crash_triggers >= CRASH_TRIGGERS_NEEDED:
            return 'CRASH', sp500_cur, sp500_ma, extra_info

        # Check for RECOVERY (if we were recently in crash)
        # Use a simple heuristic: if crash triggers were recently high but now below threshold,
        # and VIX is still elevated (> 20), treat as recovery
        if not hasattr(self, '_last_crash_timestamp'):
            self._last_crash_timestamp = None
        if not hasattr(self, '_recovery_start'):
            self._recovery_start = None

        # Track crash state for recovery buffer
        if crash_triggers >= CRASH_TRIGGERS_NEEDED:
            self._last_crash_timestamp = datetime.now()

        if self._last_crash_timestamp:
            days_since_crash = (datetime.now() - self._last_crash_timestamp).days
            if days_since_crash <= RECOVERY_BUFFER_DAYS:
                if crash_triggers < CRASH_TRIGGERS_NEEDED:
                    extra_info['recovery_days_remaining'] = RECOVERY_BUFFER_DAYS - days_since_crash
                    return 'RECOVERY', sp500_cur, sp500_ma, extra_info

        # Check primary RSI for SIDEWAYS
        primary = self.prediction_data.get(primary_metal, {})
        primary_closes = primary.get('closes', [])
        rsi = self.calculate_rsi(primary_closes) if len(primary_closes) >= 15 else None

        if rsi is not None and 45 <= rsi <= 55:
            return 'SIDEWAYS', sp500_cur, sp500_ma, extra_info

        # BULL vs BEAR based on S&P 500 vs 20d MA
        if sp500_cur > sp500_ma:
            return 'BULL', sp500_cur, sp500_ma, extra_info
        return 'BEAR', sp500_cur, sp500_ma, extra_info

    def _correlation_over_period(self, primary_closes, secondary_closes, period):
        """Return Pearson correlation of log returns over the given period (for fast/slow correlation)."""
        n = min(len(primary_closes), len(secondary_closes), period)
        if n < 5:
            return 0.0
        primary_returns = []
        secondary_returns = []
        for i in range(-n + 1, 0):
            if primary_closes[i-1] > 0 and secondary_closes[i-1] > 0 and primary_closes[i] > 0 and secondary_closes[i] > 0:
                primary_returns.append(math.log(primary_closes[i] / primary_closes[i-1]))
                secondary_returns.append(math.log(secondary_closes[i] / secondary_closes[i-1]))
        if len(primary_returns) < 5:
            return 0.0
        p_mean = sum(primary_returns) / len(primary_returns)
        s_mean = sum(secondary_returns) / len(secondary_returns)
        cov = sum((p - p_mean) * (s - s_mean) for p, s in zip(primary_returns, secondary_returns)) / len(primary_returns)
        var_p = sum((p - p_mean) ** 2 for p in primary_returns) / len(primary_returns)
        var_s = sum((s - s_mean) ** 2 for s in secondary_returns) / len(secondary_returns)
        if var_p <= 0 or var_s <= 0:
            return 0.0
        return cov / (math.sqrt(var_p) * math.sqrt(var_s))

    def calculate_beta(self, primary_closes, secondary_closes, period=60):
        """
        Calculate dynamic beta between two assets based on their log returns.
        
        Beta = Covariance(primary, secondary) / Variance(secondary)
        
        Uses log returns for better statistical properties.
        """
        # Use the most recent 'period' days, or all available data
        n = min(len(primary_closes), len(secondary_closes), period)
        
        if n < 14:  # Need at least 14 days for meaningful calculation
            return 1.0, 0.0  # Default fallback
        
        # Calculate daily LOG returns for both assets
        primary_returns = []
        secondary_returns = []
        
        for i in range(-n + 1, 0):
            if primary_closes[i-1] > 0 and secondary_closes[i-1] > 0 and \
               primary_closes[i] > 0 and secondary_closes[i] > 0:
                p_return = math.log(primary_closes[i] / primary_closes[i-1])
                s_return = math.log(secondary_closes[i] / secondary_closes[i-1])
                primary_returns.append(p_return)
                secondary_returns.append(s_return)
        
        if len(primary_returns) < 10:
            return 1.0, 0.0
        
        # Calculate means
        p_mean = sum(primary_returns) / len(primary_returns)
        s_mean = sum(secondary_returns) / len(secondary_returns)
        
        # Calculate covariance and variance
        covariance = 0
        s_variance = 0
        p_variance = 0
        
        for i in range(len(primary_returns)):
            p_diff = primary_returns[i] - p_mean
            s_diff = secondary_returns[i] - s_mean
            covariance += p_diff * s_diff
            s_variance += s_diff * s_diff
            p_variance += p_diff * p_diff
        
        covariance /= len(primary_returns)
        s_variance /= len(secondary_returns)
        p_variance /= len(primary_returns)
        
        # Calculate beta
        if s_variance == 0:
            beta = 1.0
        else:
            beta = covariance / s_variance
        
        # Calculate correlation (for confidence)
        if p_variance > 0 and s_variance > 0:
            correlation = covariance / (math.sqrt(p_variance) * math.sqrt(s_variance))
        else:
            correlation = 0
        
        # Clamp beta to reasonable range (0.1 to 5.0)
        beta = max(0.1, min(5.0, beta))
        
        return beta, correlation
    
    def _calculate_macd_histogram(self, closes):
        """Calculate MACD histogram (MACD line - Signal line) using 12/26/9 EMA."""
        if len(closes) < 35:
            return None
        # EMA helper
        def ema(data, period):
            multiplier = 2 / (period + 1)
            result = [sum(data[:period]) / period]
            for i in range(period, len(data)):
                result.append((data[i] - result[-1]) * multiplier + result[-1])
            return result

        ema12 = ema(closes, 12)
        ema26 = ema(closes, 26)
        # Align lengths (ema26 starts later)
        offset = 26 - 12
        macd_line = [ema12[i + offset] - ema26[i] for i in range(len(ema26))]
        if len(macd_line) < 9:
            return None
        signal_line = ema(macd_line, 9)
        # Histogram is last value of macd_line - last value of signal_line
        histogram = macd_line[-1] - signal_line[-1]
        return histogram

    def calculate_prediction(self, primary_metal, secondary_name):
        """Calculate predicted price using v4 regime-aware logic with 5 regimes."""
        if primary_metal not in self.prediction_data or secondary_name not in self.prediction_data:
            return None

        primary = self.prediction_data[primary_metal]
        secondary = self.prediction_data[secondary_name]

        primary_closes = primary['closes']
        secondary_closes = secondary['closes']

        if len(primary_closes) < 30 or len(secondary_closes) < 30:
            return None

        # Current prices
        primary_cur = primary_closes[-1]
        secondary_cur = secondary_closes[-1]

        # Regime detection (5 regimes: CRASH, RECOVERY, SIDEWAYS, BULL, BEAR)
        regime, sp500_cur, sp500_ma, regime_extra = self._get_regime(primary_metal)

        # Dual correlation: fast (10d) vs slow (60d) for regime-change detection
        corr_slow = self._correlation_over_period(primary_closes, secondary_closes, 60)
        corr_fast = self._correlation_over_period(primary_closes, secondary_closes, CORRELATION_FAST_DAYS)
        regime_change = abs(corr_fast - corr_slow) > CORRELATION_REGIME_DIVERGENCE

        # ATR and volatility
        atr_val = None
        volatility_pct = None
        if primary_cur > 0:
            atr_val = self.calculate_atr(primary.get('highs', []), primary.get('lows', []), primary_closes)
            volatility_pct = (atr_val / primary_cur) * 100 if atr_val else 0

        # === MOMENTUM CALCULATION (regime-dependent) ===
        if regime == 'CRASH':
            # Mean reversion to 20d MA momentum calculation
            if len(primary_closes) >= REGIME_MA_DAYS:
                ma_20d = sum(primary_closes[-REGIME_MA_DAYS:]) / REGIME_MA_DAYS
                # Reversion: 30% towards 50d MA
                if len(primary_closes) >= CRASH_REVERSION_MA:
                    ma_50d = sum(primary_closes[-CRASH_REVERSION_MA:]) / CRASH_REVERSION_MA
                    reversion_target = primary_cur + CRASH_REVERSION_FACTOR * (ma_50d - primary_cur)
                    secondary_momentum = (reversion_target / primary_cur) - 1
                else:
                    secondary_momentum = (ma_20d / primary_cur) - 1
            else:
                secondary_momentum = 0
        elif regime == 'RECOVERY':
            # Mean reversion to 20d MA momentum calculation
            if len(primary_closes) >= RECOVERY_REVERSION_MA:
                ma_20d = sum(primary_closes[-RECOVERY_REVERSION_MA:]) / RECOVERY_REVERSION_MA
                reversion_target = primary_cur + RECOVERY_REVERSION_FACTOR * (ma_20d - primary_cur)
                secondary_momentum = (reversion_target / primary_cur) - 1
            else:
                secondary_momentum = 0
        else:
            # SIDEWAYS, BULL, BEAR: 7d/14d SMA momentum calculation
            secondary_7davg = sum(secondary_closes[-7:]) / 7
            secondary_14davg = sum(secondary_closes[-14:]) / 14
            if secondary_14davg <= 0 or secondary_7davg <= 0:
                return None
            secondary_momentum_log = math.log(secondary_7davg / secondary_14davg)
            secondary_momentum = math.exp(secondary_momentum_log) - 1

        # === DYNAMIC BETA with regime adjustment ===
        beta, correlation = self.calculate_beta(primary_closes, secondary_closes)
        beta_for_move = beta

        if regime == 'CRASH' or regime == 'RECOVERY':
            # Crash/Recovery use mean reversion, beta not applied to momentum
            beta_for_move = 1.0
        elif regime == 'SIDEWAYS':
            beta_for_move = beta * 1.0  # full beta
        elif regime == 'BULL':
            beta_for_move = beta * 1.0  # full beta
        elif regime == 'BEAR':
            beta_for_move = beta * BEAR_BETA_SHRINK  # 0.7x

        # Apply regime change shrink on top
        if regime_change and regime not in ('CRASH', 'RECOVERY'):
            beta_for_move = beta_for_move * REGIME_BETA_SHRINK

        # Expected move
        primary_expected_move = secondary_momentum * beta_for_move

        # === DYNAMIC CLAMP (regime-dependent) ===
        if regime == 'CRASH':
            # Dynamic σ-based clamp (3σ max)
            if atr_val and primary_cur > 0:
                # Use daily returns std dev * sqrt(7) for weekly σ
                if len(primary_closes) >= 21:
                    daily_returns = []
                    for i in range(-20, 0):
                        if primary_closes[i - 1] > 0:
                            daily_returns.append(primary_closes[i] / primary_closes[i - 1] - 1)
                    if daily_returns:
                        mean_ret = sum(daily_returns) / len(daily_returns)
                        variance = sum((r - mean_ret) ** 2 for r in daily_returns) / len(daily_returns)
                        daily_sigma = math.sqrt(variance)
                        weekly_sigma = daily_sigma * SQRT_7
                        clamp = min(weekly_sigma * CLAMP_CRASH_SIGMA, 0.50)  # cap at 50% max
                    else:
                        clamp = CLAMP_CRISIS
                else:
                    clamp = CLAMP_CRISIS
            else:
                clamp = CLAMP_CRISIS
        elif regime == 'RECOVERY':
            clamp = CLAMP_RECOVERY
        elif regime_change:
            clamp = CLAMP_CRISIS
        elif volatility_pct is not None and volatility_pct >= VOLATILITY_CRISIS_PCT:
            clamp = CLAMP_CRISIS
        elif volatility_pct is not None and volatility_pct >= VOLATILITY_ELEVATED_PCT:
            clamp = CLAMP_ELEVATED
        else:
            clamp = CLAMP_NORMAL

        primary_expected_move = max(-clamp, min(clamp, primary_expected_move))

        # === RATIO AND MEAN REVERSION PRESSURE ===
        current_ratio = secondary_cur / primary_cur if primary_cur > 0 else 0
        if len(primary_closes) >= 28 and len(secondary_closes) >= 28:
            ratio_history = []
            for i in range(-28, 0):
                if primary_closes[i] > 0:
                    ratio_history.append(secondary_closes[i] / primary_closes[i])
            avg_ratio = sum(ratio_history) / len(ratio_history) if ratio_history else current_ratio
        else:
            avg_ratio = current_ratio

        ratio_deviation = (current_ratio - avg_ratio) / avg_ratio if avg_ratio > 0 else 0

        # Base multiplier: |ρ| × 0.15
        if correlation < 0:
            pressure_multiplier = 0  # Negative correlation pressure = 0
        else:
            pressure_multiplier = abs(correlation) * RATIO_BASE_MULTIPLIER_FACTOR

        # SIDEWAYS: 2.0x boost
        if regime == 'SIDEWAYS':
            pressure_multiplier *= RATIO_SIDEWAYS_BOOST

        ratio_pressure = ratio_deviation * pressure_multiplier

        # Bear disable condition: primary 14d momentum < 0
        primary_14d_momentum = None
        if len(primary_closes) >= 15 and primary_closes[-15] > 0:
            primary_14d_momentum = (primary_closes[-1] / primary_closes[-15]) - 1
        if regime == 'BEAR' and primary_14d_momentum is not None and primary_14d_momentum < 0:
            ratio_pressure = 0.0

        # Bull disable condition: MACD histogram < 0
        if regime == 'BULL':
            macd_hist = self._calculate_macd_histogram(secondary_closes)
            if macd_hist is not None and macd_hist < 0:
                ratio_pressure = 0.0

        # No ratio pressure in crash/recovery (mean reversion handles it)
        if regime in ('CRASH', 'RECOVERY'):
            ratio_pressure = 0.0

        # === FINAL PREDICTION ===
        predicted_price = primary_cur * (1 + primary_expected_move + ratio_pressure)

        return {
            'predicted_price': predicted_price,
            'current_price': primary_cur,
            'secondary_momentum': secondary_momentum * 100,
            'primary_expected_move': primary_expected_move * 100,
            'current_ratio': current_ratio,
            'avg_ratio': avg_ratio,
            'ratio_deviation': ratio_deviation * 100,
            'ratio_pressure': ratio_pressure * 100,
            'pressure_multiplier': pressure_multiplier,
            'beta': beta,
            'correlation': correlation,
            'regime': regime,
            'regime_change': regime_change,
            'regime_extra': regime_extra,
            'clamp_used': clamp,
            'correlation_fast': corr_fast,
            'correlation_slow': corr_slow,
            'volatility_pct': volatility_pct,
        }
    
    def calculate_confidence(self, primary_metal, secondary_name, prediction_result):
        """Calculate confidence percentage based on 8 weighted factors (v4)."""
        if not prediction_result:
            return 0, []

        primary = self.prediction_data.get(primary_metal, {})
        secondary = self.prediction_data.get(secondary_name, {})
        dxy_data = self.prediction_data.get('DXY', None)

        signals = []
        confidence_points = 0

        # v4 weights: Correlation 40%, DXY 7%(4% copper), Regime Fit 10%, RSI 10%,
        #             Volatility 5%, Ratio 10%, RSI Divergence 8%, Correlation Agreement 10%
        is_copper = (primary_metal == 'Copper')
        W_CORRELATION = CONF_W_CORRELATION          # 40
        W_DXY = CONF_W_DXY_COPPER if is_copper else CONF_W_DXY  # 4 or 7
        W_REGIME_FIT = CONF_W_REGIME_FIT            # 10
        W_RSI = CONF_W_RSI                          # 10
        W_VOLATILITY = CONF_W_VOLATILITY            # 5
        W_RATIO = CONF_W_RATIO                      # 10
        W_RSI_DIVERGENCE = CONF_W_RSI_DIVERGENCE    # 8
        W_CORR_AGREEMENT = CONF_W_CORR_AGREEMENT    # 10
        max_points = W_CORRELATION + W_DXY + W_REGIME_FIT + W_RSI + W_VOLATILITY + W_RATIO + W_RSI_DIVERGENCE + W_CORR_AGREEMENT

        primary_closes = primary.get('closes', [])
        secondary_closes = secondary.get('closes', [])
        regime = prediction_result.get('regime')
        regime_change = prediction_result.get('regime_change', False)
        ratio_deviation_abs = abs(prediction_result.get('ratio_deviation', 0)) / 100

        # =====================
        # FACTOR 1: Correlation (60d) - 40%
        # =====================
        correlation = prediction_result.get('correlation', 0)
        abs_corr = abs(correlation)
        if abs_corr >= 0.7:
            confidence_points += W_CORRELATION
            signals.append(("Correlation", f"✓ Strong ({correlation:.2f}) - reliable beta (+{W_CORRELATION}pts)", True))
        elif abs_corr >= 0.5:
            scaled_pts = int(W_CORRELATION * (abs_corr - 0.3) / 0.4)
            confidence_points += scaled_pts
            signals.append(("Correlation", f"△ Moderate ({correlation:.2f}) (+{scaled_pts}pts)", False))
        elif abs_corr >= 0.3:
            quarter_pts = W_CORRELATION // 4
            confidence_points += quarter_pts
            signals.append(("Correlation", f"✗ Weak ({correlation:.2f}) (+{quarter_pts}pts)", False))
        else:
            signals.append(("Correlation", f"✗ Very weak ({correlation:.2f}) - beta unreliable (+0pts)", False))

        # =====================
        # FACTOR 2: DXY Health - 7% (4% copper)
        # =====================
        if dxy_data is not None and 'closes' in dxy_data:
            dxy_closes = dxy_data['closes']
            if len(primary_closes) >= 14 and len(dxy_closes) >= 14:
                dxy_corr = self._calculate_simple_correlation(
                    primary_closes[-14:], dxy_closes[-min(14, len(dxy_closes)):]
                )
                if dxy_corr <= -0.5:
                    confidence_points += W_DXY
                    signals.append(("DXY Health", f"✓ Healthy inverse ({dxy_corr:.2f}) (+{W_DXY}pts)", True))
                elif dxy_corr < 0:
                    scaled_pts = int(W_DXY * abs(dxy_corr) / 0.5)
                    confidence_points += scaled_pts
                    signals.append(("DXY Health", f"△ Mild inverse ({dxy_corr:.2f}) (+{scaled_pts}pts)", False))
                else:
                    signals.append(("DXY Health", f"✗ Moving with USD ({dxy_corr:.2f}) (+0pts)", False))
            else:
                signals.append(("DXY Health", "? Insufficient DXY data", False))
        else:
            signals.append(("DXY Health", "? DXY data unavailable", False))

        # =====================
        # FACTOR 3: Regime Fit - 10%
        # =====================
        regime_fit = False
        if regime == 'BULL' and secondary_name == 'Gold':
            regime_fit = True
            regime_desc = "Bull + Gold anchor"
        elif regime == 'BEAR' and secondary_name == 'S&P 500':
            regime_fit = True
            regime_desc = "Bear + S&P 500 anchor"
        elif regime == 'SIDEWAYS' and ratio_deviation_abs < 0.10:
            regime_fit = True
            regime_desc = "Sideways + stable ratio"
        elif regime == 'CRASH':
            regime_fit = True  # crash regime is always a "fit" since it overrides
            regime_desc = "Crash - mean reversion active"
        elif regime == 'RECOVERY':
            regime_fit = True
            regime_desc = "Recovery - buffer active"
        else:
            regime_desc = f"Regime {regime or '?'} / {secondary_name}"
        if regime_fit:
            confidence_points += W_REGIME_FIT
            signals.append(("Regime Fit", f"✓ {regime_desc} (+{W_REGIME_FIT}pts)", True))
        else:
            signals.append(("Regime Fit", f"△ {regime_desc} (+0pts)", False))

        # =====================
        # FACTOR 4: RSI Range - 10%
        # =====================
        rsi = self.calculate_rsi(primary_closes)
        if rsi is not None:
            if 30 <= rsi <= 70:
                confidence_points += W_RSI
                signals.append(("RSI Range", f"✓ RSI ({rsi:.1f}) neutral (+{W_RSI}pts)", True))
            elif 20 <= rsi < 30 or 70 < rsi <= 80:
                half_pts = W_RSI // 2
                confidence_points += half_pts
                signals.append(("RSI Range", f"△ RSI ({rsi:.1f}) near extreme (+{half_pts}pts)", False))
            else:
                signals.append(("RSI Range", f"✗ RSI ({rsi:.1f}) extreme (+0pts)", False))

        # =====================
        # FACTOR 5: Volatility - 5%
        # =====================
        atr = self.calculate_atr(primary.get('highs', []), primary.get('lows', []), primary_closes)
        if atr is not None and len(primary_closes) > 0:
            current_price = primary_closes[-1]
            volatility_pct = (atr / current_price) * 100 if current_price > 0 else 0
            if volatility_pct < 2:
                confidence_points += W_VOLATILITY
                signals.append(("Volatility", f"✓ Low ({volatility_pct:.1f}%) (+{W_VOLATILITY}pts)", True))
            elif volatility_pct < 4:
                half_pts = W_VOLATILITY // 2
                confidence_points += half_pts
                signals.append(("Volatility", f"△ Moderate ({volatility_pct:.1f}%) (+{half_pts}pts)", False))
            else:
                signals.append(("Volatility", f"✗ High ({volatility_pct:.1f}%) (+0pts)", False))

        # =====================
        # FACTOR 6: Ratio Stability - 10%
        # =====================
        if ratio_deviation_abs < 0.05:
            confidence_points += W_RATIO
            signals.append(("Ratio Stability", f"✓ Near average ({ratio_deviation_abs*100:.1f}% dev) (+{W_RATIO}pts)", True))
        elif ratio_deviation_abs < 0.15:
            half_pts = W_RATIO // 2
            confidence_points += half_pts
            signals.append(("Ratio Stability", f"△ Extended ({ratio_deviation_abs*100:.1f}% dev) (+{half_pts}pts)", False))
        else:
            signals.append(("Ratio Stability", f"✗ Far from avg ({ratio_deviation_abs*100:.1f}% dev) (+0pts)", False))

        # =====================
        # FACTOR 7: RSI Divergence - 8%
        # Price making new highs/lows but RSI isn't confirming
        # =====================
        rsi_divergence_pts = 0
        if rsi is not None and len(primary_closes) >= 14:
            # Check if price trend matches RSI trend (last 14 days)
            price_trend = (primary_closes[-1] / primary_closes[-14]) - 1

            # Calculate RSI from 14 days ago for comparison
            if len(primary_closes) >= 28:
                rsi_old = self.calculate_rsi(primary_closes[:-14])
                if rsi_old is not None:
                    rsi_trend = rsi - rsi_old
                    # Divergence: price up but RSI down, or price down but RSI up
                    if (price_trend > 0.02 and rsi_trend < -5) or (price_trend < -0.02 and rsi_trend > 5):
                        # Divergence detected - this is informative but lowers confidence
                        signals.append(("RSI Divergence", f"✗ Divergence detected (price {price_trend*100:+.1f}%, RSI {rsi_trend:+.1f}) (+0pts)", False))
                    else:
                        # No divergence - price and RSI agree
                        rsi_divergence_pts = W_RSI_DIVERGENCE
                        confidence_points += rsi_divergence_pts
                        signals.append(("RSI Divergence", f"✓ Price/RSI aligned (+{W_RSI_DIVERGENCE}pts)", True))
                else:
                    signals.append(("RSI Divergence", "? Insufficient RSI history", False))
            else:
                signals.append(("RSI Divergence", "? Insufficient data for RSI divergence", False))
        else:
            signals.append(("RSI Divergence", "? RSI unavailable", False))

        # =====================
        # FACTOR 8: Correlation Agreement - 10%
        # Fast (10d) and slow (60d) correlations should agree in sign and magnitude
        # =====================
        corr_fast = prediction_result.get('correlation_fast', 0)
        corr_slow = prediction_result.get('correlation_slow', 0)
        corr_diff = abs(corr_fast - corr_slow)
        if corr_diff < 0.15 and (corr_fast * corr_slow > 0):
            # Strong agreement: same sign and close magnitude
            confidence_points += W_CORR_AGREEMENT
            signals.append(("Corr Agreement", f"✓ Fast/slow aligned ({corr_fast:.2f}/{corr_slow:.2f}, diff={corr_diff:.2f}) (+{W_CORR_AGREEMENT}pts)", True))
        elif corr_diff < 0.30 and (corr_fast * corr_slow > 0):
            # Moderate agreement
            half_pts = W_CORR_AGREEMENT // 2
            confidence_points += half_pts
            signals.append(("Corr Agreement", f"△ Partial alignment ({corr_fast:.2f}/{corr_slow:.2f}, diff={corr_diff:.2f}) (+{half_pts}pts)", False))
        else:
            signals.append(("Corr Agreement", f"✗ Fast/slow diverging ({corr_fast:.2f}/{corr_slow:.2f}, diff={corr_diff:.2f}) (+0pts)", False))

        confidence_pct = (confidence_points / max_points) * 100 if max_points > 0 else 0
        # Cap confidence when regime change detected
        if regime_change:
            confidence_pct = min(confidence_pct, CONFIDENCE_CAP_REGIME_CHANGE)
            signals.append(("Regime Change", f"⚠ Confidence capped at {CONFIDENCE_CAP_REGIME_CHANGE}% (fast/slow correlation divergence)", False))

        return confidence_pct, signals
    
    def _calculate_simple_correlation(self, series1, series2):
        """Calculate Pearson correlation between two price series"""
        n = min(len(series1), len(series2))
        if n < 5:
            return 0
        
        s1 = series1[-n:]
        s2 = series2[-n:]
        
        mean1 = sum(s1) / n
        mean2 = sum(s2) / n
        
        cov = sum((s1[i] - mean1) * (s2[i] - mean2) for i in range(n)) / n
        var1 = sum((x - mean1) ** 2 for x in s1) / n
        var2 = sum((x - mean2) ** 2 for x in s2) / n
        
        if var1 <= 0 or var2 <= 0:
            return 0
        
        return cov / (math.sqrt(var1) * math.sqrt(var2))
    
    def _set_breakdown_text(self, text):
        """Set the breakdown text widget content"""
        if hasattr(self, 'pred_breakdown_text'):
            self.pred_breakdown_text.config(state='normal')
            self.pred_breakdown_text.delete('1.0', tk.END)
            self.pred_breakdown_text.insert('1.0', text)
            self.pred_breakdown_text.config(state='disabled')
    
    def calculate_and_display_prediction(self):
        """Calculate all indicators and update the prediction display"""
        try:
            primary_metal = self.pred_primary_var.get()
            secondary_metal = self.pred_secondary_var.get()
            
            primary = self.prediction_data.get(primary_metal, {})
            secondary = self.prediction_data.get(secondary_metal, {})
            
            primary_closes = primary.get('closes', [])
            secondary_closes = secondary.get('closes', [])
            primary_highs = primary.get('highs', [])
            primary_lows = primary.get('lows', [])
            
            if not primary_closes or not secondary_closes:
                self.pred_status_var.set("No data available")
                self.pred_fetch_btn.config(state='normal')
                return
            
            # Current prices
            primary_cur = primary_closes[-1]
            secondary_cur = secondary_closes[-1]
            
            # Update current price display
            self.pred_current_var.set(f"${primary_cur:.4f}/g")
            
            # Calculate Metal Ratio
            if primary_cur > 0:
                current_ratio = secondary_cur / primary_cur
                self.pred_ratio_var.set(f"{current_ratio:.2f} ({secondary_metal}/{primary_metal})")
                
                # Ratio trend (7d avg vs 28d avg)
                if len(primary_closes) >= 28 and len(secondary_closes) >= 28:
                    ratio_7d = sum([secondary_closes[i] / primary_closes[i] for i in range(-7, 0) if primary_closes[i] > 0]) / 7
                    ratio_28d = sum([secondary_closes[i] / primary_closes[i] for i in range(-28, 0) if primary_closes[i] > 0]) / 28
                    
                    ratio_change = ((ratio_7d - ratio_28d) / ratio_28d) * 100 if ratio_28d > 0 else 0
                    trend_dir = "↑" if ratio_change > 0 else "↓"
                    self.pred_ratio_trend_var.set(f"{trend_dir} {abs(ratio_change):.1f}% (7d vs 28d)")
                else:
                    self.pred_ratio_trend_var.set("Insufficient data")
            
            # Calculate RSI
            rsi = self.calculate_rsi(primary_closes)
            if rsi is not None:
                self.pred_rsi_var.set(f"{rsi:.1f}")
                
                if rsi >= 70:
                    self.pred_rsi_signal_var.set("OVERBOUGHT")
                    self.pred_rsi_signal_label.config(foreground='#CC0000')
                elif rsi <= 30:
                    self.pred_rsi_signal_var.set("OVERSOLD")
                    self.pred_rsi_signal_label.config(foreground='#008000')
                else:
                    self.pred_rsi_signal_var.set("NEUTRAL")
                    self.pred_rsi_signal_label.config(foreground='#666666')
            else:
                self.pred_rsi_var.set("N/A")
                self.pred_rsi_signal_var.set("--")
            
            # Calculate ATR
            atr = self.calculate_atr(primary_highs, primary_lows, primary_closes)
            if atr is not None:
                self.pred_atr_var.set(f"${atr:.4f}/g")
                
                volatility_pct = (atr / primary_cur) * 100 if primary_cur > 0 else 0
                if volatility_pct < 2:
                    self.pred_volatility_var.set(f"Low ({volatility_pct:.1f}%)")
                elif volatility_pct < 4:
                    self.pred_volatility_var.set(f"Moderate ({volatility_pct:.1f}%)")
                else:
                    self.pred_volatility_var.set(f"High ({volatility_pct:.1f}%)")
            else:
                self.pred_atr_var.set("N/A")
                self.pred_volatility_var.set("--")
            
            # Calculate Momentum
            momentum_7d = self.calculate_momentum(primary_closes, 7)
            momentum_14d = self.calculate_momentum(primary_closes, 14)
            
            if momentum_7d is not None:
                color = "green" if momentum_7d > 0 else "red"
                self.pred_momentum_7d_var.set(f"{momentum_7d:+.2f}%")
            else:
                self.pred_momentum_7d_var.set("N/A")
            
            if momentum_14d is not None:
                self.pred_momentum_14d_var.set(f"{momentum_14d:+.2f}%")
            else:
                self.pred_momentum_14d_var.set("N/A")
            
            # Calculate Prediction
            prediction = self.calculate_prediction(primary_metal, secondary_metal)
            
            if prediction:
                pred_price = prediction['predicted_price']
                self.pred_price_var.set(f"${pred_price:.4f}")
                
                # Predicted change
                change = pred_price - primary_cur
                change_pct = (change / primary_cur) * 100 if primary_cur > 0 else 0
                
                if change >= 0:
                    self.pred_change_var.set(f"+${change:.4f} (+{change_pct:.2f}%)")
                    self.pred_change_label.config(foreground='#008000')
                else:
                    self.pred_change_var.set(f"-${abs(change):.4f} ({change_pct:.2f}%)")
                    self.pred_change_label.config(foreground='#CC0000')
                
                # Price range (using ATR scaled by √7 for weekly projection)
                low_est = None
                high_est = None
                if atr is not None:
                    low_est = pred_price - (atr * SQRT_7)
                    high_est = pred_price + (atr * SQRT_7)
                    self.pred_range_low_var.set(f"${low_est:.4f}/g")
                    self.pred_range_high_var.set(f"${high_est:.4f}/g")
                else:
                    self.pred_range_low_var.set("N/A")
                    self.pred_range_high_var.set("N/A")
                
                # Display Beta and Correlation
                beta = prediction.get('beta', 1.0)
                correlation = prediction.get('correlation', 0)
                self.pred_beta_var.set(f"{beta:.2f}x")
                
                if abs(correlation) >= 0.7:
                    corr_text = f"{correlation:.2f} (strong)"
                elif abs(correlation) >= 0.4:
                    corr_text = f"{correlation:.2f} (moderate)"
                else:
                    corr_text = f"{correlation:.2f} (weak)"
                self.pred_correlation_var.set(corr_text)
                
                # Calculate confidence
                confidence, signals = self.calculate_confidence(primary_metal, secondary_metal, prediction)
                self.pred_confidence_var.set(f"{confidence:.0f}%")
                self.confidence_bar['value'] = confidence
                
                # Update breakdown
                correlation = prediction.get('correlation', 0)
                corr_strength = "strong" if abs(correlation) > 0.7 else "moderate" if abs(correlation) > 0.4 else "weak"
                pressure_mult = prediction.get('pressure_multiplier', 0)
                regime = prediction.get('regime') or '?'
                clamp_used = prediction.get('clamp_used', CLAMP_NORMAL)
                regime_change = prediction.get('regime_change', False)
                clamp_pct = int(clamp_used * 100)
                regime_extra = prediction.get('regime_extra', {})
                crash_details = regime_extra.get('crash_details', [])
                crash_triggers = regime_extra.get('crash_triggers', 0)

                # Format clamp display
                if regime == 'CRASH':
                    clamp_desc = f"dynamic σ-based ({clamp_pct}%)"
                else:
                    clamp_desc = f"±{clamp_pct}%"

                breakdown_lines = [
                    f"Prediction Formula Breakdown (v4):",
                    f"  Regime: {regime}" + ("  ⚠ Regime change (fast/slow correlation divergence)" if regime_change else ""),
                ]

                # Add crash detection details if available
                if crash_details:
                    breakdown_lines.append(f"  Crash Triggers: {crash_triggers}/5 (need {CRASH_TRIGGERS_NEEDED})")
                    for detail in crash_details:
                        breakdown_lines.append(f"     • {detail}")

                if regime == 'RECOVERY':
                    remaining = regime_extra.get('recovery_days_remaining', '?')
                    breakdown_lines.append(f"  Recovery buffer: {remaining} days remaining")

                # Momentum description varies by regime
                if regime in ('CRASH', 'RECOVERY'):
                    breakdown_lines.append(f"  1. Mean Reversion Momentum: {prediction['secondary_momentum']:+.2f}%")
                    if regime == 'CRASH':
                        breakdown_lines.append(f"     → 30% reversion towards 50d MA")
                    else:
                        breakdown_lines.append(f"     → 20% reversion towards 20d MA")
                else:
                    breakdown_lines.append(f"  1. {secondary_metal} Momentum (7d vs 14d SMA): {prediction['secondary_momentum']:+.2f}%")

                breakdown_lines.extend([
                    f"  2. Dynamic Beta (60-day, log returns): {prediction['beta']:.2f}x",
                    f"     → Correlation 60d: {prediction.get('correlation_slow', correlation):.2f}  10d: {prediction.get('correlation_fast', 0):.2f}",
                    f"     → Expected {primary_metal} move: {prediction['primary_expected_move']:+.2f}% (clamped {clamp_desc})",
                    f"  3. {secondary_metal}/{primary_metal} Ratio: {prediction['current_ratio']:.2f} (28d avg: {prediction['avg_ratio']:.2f})",
                    f"     → Ratio Deviation: {prediction['ratio_deviation']:+.2f}%",
                    f"  4. Adaptive Ratio Pressure: {prediction['ratio_pressure']:+.2f}%",
                    f"     → Pressure multiplier: {pressure_mult:.3f}",
                    f"",
                    f"Price Range: ATR × √7 = {atr:.4f} × {SQRT_7:.2f} = ±${atr * SQRT_7:.4f}" if atr else f"Price Range: N/A",
                    f"",
                    f"Confidence (v4: 8-factor, Correlation 40%, cap when regime change):"
                ])
                for signal_name, signal_desc, signal_positive in signals:
                    breakdown_lines.append(f"  • {signal_desc}")
                
                self._set_breakdown_text("\n".join(breakdown_lines))
                
                # Store current prediction for saving (includes ALL metrics for algorithm improvement)
                # Calculate RSI signal
                if rsi is not None:
                    if rsi >= 70:
                        rsi_signal = "OVERBOUGHT"
                    elif rsi <= 30:
                        rsi_signal = "OVERSOLD"
                    else:
                        rsi_signal = "NEUTRAL"
                else:
                    rsi_signal = None
                
                # Calculate volatility percentage
                volatility_pct = (atr / primary_cur) * 100 if atr and primary_cur > 0 else None
                
                # Get ratio trend from display (calculate it here for storage)
                ratio_trend_pct = None
                if len(primary_closes) >= 28 and len(secondary_closes) >= 28:
                    ratio_7d = sum([secondary_closes[i] / primary_closes[i] for i in range(-7, 0) if primary_closes[i] > 0]) / 7
                    ratio_28d = sum([secondary_closes[i] / primary_closes[i] for i in range(-28, 0) if primary_closes[i] > 0]) / 28
                    ratio_trend_pct = ((ratio_7d - ratio_28d) / ratio_28d) * 100 if ratio_28d > 0 else 0
                
                self.current_prediction_result = {
                    # Basic identification
                    'primary_metal': primary_metal,
                    'secondary_metal': secondary_metal,
                    
                    # Core price data
                    'current_price': primary_cur,
                    'secondary_price': secondary_cur,
                    'predicted_price': pred_price,
                    'predicted_change_pct': change_pct,
                    'confidence': confidence,
                    'range_low': low_est if atr else None,
                    'range_high': high_est if atr else None,
                    
                    # Beta & Correlation metrics
                    'beta': prediction.get('beta', 1.0),
                    'correlation': prediction.get('correlation', 0),
                    
                    # RSI metrics
                    'rsi': rsi,
                    'rsi_signal': rsi_signal,
                    
                    # Volatility metrics
                    'atr': atr,
                    'volatility_pct': volatility_pct,
                    
                    # Momentum metrics
                    'momentum_7d': momentum_7d,
                    'momentum_14d': momentum_14d,
                    'secondary_momentum': prediction.get('secondary_momentum'),
                    'primary_expected_move': prediction.get('primary_expected_move'),
                    
                    # Ratio metrics
                    'current_ratio': prediction.get('current_ratio'),
                    'avg_ratio_28d': prediction.get('avg_ratio'),
                    'ratio_deviation_pct': prediction.get('ratio_deviation'),
                    'ratio_trend_pct': ratio_trend_pct,
                    
                    # Pressure metrics
                    'ratio_pressure': prediction.get('ratio_pressure'),
                    'pressure_multiplier': prediction.get('pressure_multiplier'),
                    
                    # v4 regime and clamp
                    'regime': prediction.get('regime'),
                    'regime_change': prediction.get('regime_change'),
                    'regime_extra': prediction.get('regime_extra', {}),
                    'clamp_used': prediction.get('clamp_used'),
                    'correlation_fast': prediction.get('correlation_fast'),
                    'correlation_slow': prediction.get('correlation_slow'),
                    
                    # Confidence breakdown (store individual signals)
                    'confidence_signals': [(s[0], s[1], s[2]) for s in signals]
                }
                
                # Enable save button
                self.pred_save_btn.config(state='normal')
            else:
                self.pred_price_var.set("N/A")
                self.pred_change_var.set("--")
                self.pred_confidence_var.set("--")
                self.pred_beta_var.set("--")
                self.pred_correlation_var.set("--")
                self._set_breakdown_text("Could not calculate prediction - insufficient data")
                self.current_prediction_result = None
                self.pred_save_btn.config(state='disabled')
            
            # Update status
            self.pred_status_var.set(f"Data fetched: {datetime.now().strftime('%H:%M:%S')}")
            self.pred_fetch_btn.config(state='normal')
            
        except Exception as e:
            self.pred_status_var.set(f"Error: {str(e)}")
            self.pred_fetch_btn.config(state='normal')
            print(f"Prediction error: {e}")
    
    def save_current_prediction(self):
        """Save the current prediction to history"""
        if not hasattr(self, 'current_prediction_result') or not self.current_prediction_result:
            messagebox.showwarning("No Prediction", "Please fetch prediction data first.")
            return
        
        pred = self.current_prediction_result
        
        # Create prediction record with unique ID
        # Includes ALL metrics for algorithm improvement and analysis
        record = {
            # Identification
            'id': f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(self.prediction_history)}",
            'timestamp': datetime.now().isoformat(),
            'target_date': (datetime.now() + timedelta(days=7)).isoformat(),
            'primary_metal': pred['primary_metal'],
            'secondary_metal': pred['secondary_metal'],
            
            # Core price data
            'current_price': pred['current_price'],
            'secondary_price': pred.get('secondary_price'),
            'predicted_price': pred['predicted_price'],
            'predicted_change_pct': pred['predicted_change_pct'],
            'confidence': pred['confidence'],
            'range_low': pred['range_low'],
            'range_high': pred['range_high'],
            
            # Beta & Correlation metrics
            'beta': pred['beta'],
            'correlation': pred['correlation'],
            
            # RSI metrics
            'rsi': pred['rsi'],
            'rsi_signal': pred.get('rsi_signal'),
            
            # Volatility metrics
            'atr': pred['atr'],
            'volatility_pct': pred.get('volatility_pct'),
            
            # Momentum metrics
            'momentum_7d': pred.get('momentum_7d'),
            'momentum_14d': pred.get('momentum_14d'),
            'secondary_momentum': pred.get('secondary_momentum'),
            'primary_expected_move': pred.get('primary_expected_move'),
            
            # Ratio metrics
            'current_ratio': pred.get('current_ratio'),
            'avg_ratio_28d': pred.get('avg_ratio_28d'),
            'ratio_deviation_pct': pred.get('ratio_deviation_pct'),
            'ratio_trend_pct': pred.get('ratio_trend_pct'),
            
            # Pressure metrics
            'ratio_pressure': pred.get('ratio_pressure'),
            'pressure_multiplier': pred.get('pressure_multiplier'),
            
            # Confidence breakdown
            'confidence_signals': pred.get('confidence_signals', []),
            
            # Grading fields (filled in later when prediction matures)
            'actual_price': None,
            'actual_change_pct': None,
            'direction_correct': None,
            'error_pct': None,
            'in_range': None,  # Was actual price within predicted range?
            'graded': False
        }
        
        # Append to list
        self.prediction_history.append(record)
        
        # Save to file
        self.save_prediction_history()
        
        # Disable save button
        self.pred_save_btn.config(state='disabled')
        
        # Store info for messagebox
        metal = pred['primary_metal']
        secondary = pred['secondary_metal']
        price = pred['predicted_price']
        target = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
        count = len(self.prediction_history)
        
        # Show message first
        messagebox.showinfo("Prediction Saved", 
                          f"Prediction saved!\n\n"
                          f"Metals: {metal} vs {secondary}\n"
                          f"Predicted: ${price:.4f}/g\n"
                          f"Target Date: {target}\n\n"
                          f"Total predictions: {count}\n"
                          f"The prediction will be graded after the target date.")
        
        # Force refresh after message is dismissed
        self.root.after(50, self._force_refresh_history)

    def run_backtest_thread(self):
        """Start the backtest in a separate thread"""
        self.pred_backtest_btn.config(state='disabled')
        months = self.backtest_months_var.get()
        self.pred_status_var.set(f"Starting back test ({months} months of data)...")
        thread = threading.Thread(target=self.run_backtest, daemon=True)
        thread.start()

    def run_backtest(self):
        """
        Run a backtest using the prediction algorithm over the user-selected
        number of months (6-60).

        For each trading day in that period (excluding the last 7 days),
        simulates a prediction using only data available up to that date,
        then compares with the actual price 7 days later. Results are
        exported to CSV with grades and error metrics.
        """
        import time as _time

        try:
            primary_metal = self.pred_primary_var.get()
            secondary_name = self.pred_secondary_var.get()
            backtest_months = int(self.backtest_months_var.get())

            if primary_metal == secondary_name:
                self.root.after(0, lambda: messagebox.showwarning(
                    "Same Selection", "Please select two different items for ratio comparison."))
                self.root.after(0, lambda: self.pred_backtest_btn.config(state='normal'))
                self.root.after(0, lambda: self.pred_status_var.set("Back test cancelled"))
                return

            # === Fetch historical data ===
            # Need backtest_months + ~3 months extra for algorithm lookback (60d correlation, etc.)
            total_months_needed = backtest_months + 3
            fetch_start_date = (datetime.now() - timedelta(days=total_months_needed * 31)).strftime('%Y-%m-%d')
            fetch_period_label = f"{backtest_months}mo"

            def update_status(msg):
                self.root.after(0, lambda: self.pred_status_var.set(msg))

            update_status(f"Back test: Fetching {primary_metal} ({fetch_period_label})...")
            primary_config = METALS[primary_metal]
            primary_hist, primary_err = self.fetch_yf_history_with_retry(
                primary_config['yf_ticker'], start=fetch_start_date, timeout=60, max_retries=3)
            if primary_err:
                raise Exception(f"Could not fetch {primary_metal}: {primary_err}")

            update_status(f"Back test: Fetching {secondary_name} ({fetch_period_label})...")
            secondary_config = PREDICTION_SECONDARIES[secondary_name]
            secondary_hist, secondary_err = self.fetch_yf_history_with_retry(
                secondary_config['yf_ticker'], start=fetch_start_date, timeout=60, max_retries=3)
            if secondary_err:
                raise Exception(f"Could not fetch {secondary_name}: {secondary_err}")

            update_status(f"Back test: Fetching DXY ({fetch_period_label})...")
            dxy_hist, dxy_err = self.fetch_yf_history_with_retry(
                DXY_TICKER, start=fetch_start_date, timeout=60, max_retries=3)
            if dxy_err:
                raise Exception(f"Could not fetch DXY: {dxy_err}")

            update_status(f"Back test: Fetching S&P 500 ({fetch_period_label})...")
            if secondary_name == 'S&P 500':
                sp500_hist = secondary_hist
            else:
                sp500_hist, sp_err = self.fetch_yf_history_with_retry(
                    SP500_TICKER_REGIME, start=fetch_start_date, timeout=60, max_retries=3)
                if sp_err:
                    sp500_hist = None

            update_status(f"Back test: Fetching VIX ({fetch_period_label})...")
            vix_hist, vix_err = self.fetch_yf_history_with_retry(
                VIX_TICKER, start=fetch_start_date, timeout=60, max_retries=3)
            if vix_err:
                vix_hist = None

            # Fetch Gold/Silver for GSR if needed
            gold_gsr_closes = None
            silver_gsr_closes = None
            if primary_metal != 'Gold' and secondary_name != 'Gold':
                update_status("Back test: Fetching Gold (GSR)...")
                gold_hist, _ = self.fetch_yf_history_with_retry(
                    METALS['Gold']['yf_ticker'], start=fetch_start_date, timeout=60, max_retries=3)
                if gold_hist is not None and not gold_hist.empty:
                    gold_gsr_closes = [float(p) / TROY_OUNCE_TO_GRAMS for p in gold_hist['Close']]
            if primary_metal != 'Silver' and secondary_name != 'Silver':
                update_status("Back test: Fetching Silver (GSR)...")
                silver_hist, _ = self.fetch_yf_history_with_retry(
                    METALS['Silver']['yf_ticker'], start=fetch_start_date, timeout=60, max_retries=3)
                if silver_hist is not None and not silver_hist.empty:
                    silver_gsr_closes = [float(p) / TROY_OUNCE_TO_GRAMS for p in silver_hist['Close']]

            # === Convert all data to lists ===
            primary_closes_all = [float(p) / TROY_OUNCE_TO_GRAMS for p in primary_hist['Close']]
            primary_highs_all = [float(p) / TROY_OUNCE_TO_GRAMS for p in primary_hist['High']]
            primary_lows_all = [float(p) / TROY_OUNCE_TO_GRAMS for p in primary_hist['Low']]
            primary_dates = list(primary_hist.index)

            if secondary_config['type'] == 'metal':
                secondary_closes_all = [float(p) / TROY_OUNCE_TO_GRAMS for p in secondary_hist['Close']]
                secondary_highs_all = [float(p) / TROY_OUNCE_TO_GRAMS for p in secondary_hist['High']]
                secondary_lows_all = [float(p) / TROY_OUNCE_TO_GRAMS for p in secondary_hist['Low']]
            else:
                secondary_closes_all = [float(p) for p in secondary_hist['Close']]
                secondary_highs_all = [float(p) for p in secondary_hist['High']]
                secondary_lows_all = [float(p) for p in secondary_hist['Low']]

            dxy_closes_all = [float(p) for p in dxy_hist['Close']]

            sp500_closes_all = None
            if sp500_hist is not None and not sp500_hist.empty:
                sp500_closes_all = [float(p) for p in sp500_hist['Close']]

            vix_closes_all = None
            if vix_hist is not None and not vix_hist.empty:
                vix_closes_all = [float(p) for p in vix_hist['Close']]

            # Gold/Silver for GSR - use from primary/secondary if available
            if primary_metal == 'Gold':
                gold_gsr_closes = primary_closes_all
            elif secondary_name == 'Gold':
                gold_gsr_closes = secondary_closes_all
            if primary_metal == 'Silver':
                silver_gsr_closes = primary_closes_all
            elif secondary_name == 'Silver':
                silver_gsr_closes = secondary_closes_all

            # === Determine backtest range ===
            # We need at least 90 days of lookback for the algorithm, and 7 days forward for the result
            total_days = len(primary_closes_all)
            min_lookback = 90  # need ~90 days for 60d correlation + 28d ratio + buffer
            backtest_days = int(backtest_months * 30.44)  # approximate trading days in selected months
            backtest_start = max(min_lookback, total_days - backtest_days)
            backtest_end = total_days - 7  # need 7 days forward for actual price

            if backtest_start >= backtest_end:
                raise Exception("Insufficient data for backtesting. Need at least 97 trading days.")

            results = []
            num_days = backtest_end - backtest_start
            update_status(f"Back test: Running {num_days} predictions...")

            # Save original prediction_data and crash state
            original_prediction_data = self.prediction_data.copy() if hasattr(self, 'prediction_data') else {}
            original_crash_ts = getattr(self, '_last_crash_timestamp', None)
            original_recovery = getattr(self, '_recovery_start', None)

            try:
                for day_idx in range(backtest_start, backtest_end):
                    # Progress update every 20 days
                    if (day_idx - backtest_start) % 20 == 0:
                        progress = day_idx - backtest_start
                        update_status(f"Back test: Day {progress}/{num_days}...")

                    # Slice data up to this day (simulating what was available)
                    p_closes = primary_closes_all[:day_idx + 1]
                    p_highs = primary_highs_all[:day_idx + 1]
                    p_lows = primary_lows_all[:day_idx + 1]
                    s_closes = secondary_closes_all[:day_idx + 1]
                    s_highs = secondary_highs_all[:day_idx + 1]
                    s_lows = secondary_lows_all[:day_idx + 1]
                    d_closes = dxy_closes_all[:min(day_idx + 1, len(dxy_closes_all))]
                    sp_closes = sp500_closes_all[:min(day_idx + 1, len(sp500_closes_all))] if sp500_closes_all else None
                    v_closes = vix_closes_all[:min(day_idx + 1, len(vix_closes_all))] if vix_closes_all else None

                    # Set up prediction_data for this simulated day
                    self.prediction_data = {}
                    self.prediction_data[primary_metal] = {
                        'closes': p_closes, 'highs': p_highs, 'lows': p_lows
                    }
                    self.prediction_data[secondary_name] = {
                        'closes': s_closes, 'highs': s_highs, 'lows': s_lows
                    }
                    self.prediction_data['DXY'] = {'closes': d_closes}
                    if sp_closes:
                        self.prediction_data['SP500_REGIME'] = {'closes': sp_closes}
                    else:
                        self.prediction_data['SP500_REGIME'] = None
                    if v_closes:
                        self.prediction_data['VIX'] = {'closes': v_closes}
                    else:
                        self.prediction_data['VIX'] = None

                    # GSR data
                    if gold_gsr_closes:
                        gsr_gold_slice = gold_gsr_closes[:min(day_idx + 1, len(gold_gsr_closes))]
                        if primary_metal == 'Gold':
                            pass  # already in prediction_data
                        elif secondary_name == 'Gold':
                            pass  # already in prediction_data
                        else:
                            self.prediction_data['Gold_GSR'] = {'closes': gsr_gold_slice}
                    if silver_gsr_closes:
                        gsr_silver_slice = silver_gsr_closes[:min(day_idx + 1, len(silver_gsr_closes))]
                        if primary_metal == 'Silver':
                            pass
                        elif secondary_name == 'Silver':
                            pass
                        else:
                            self.prediction_data['Silver_GSR'] = {'closes': gsr_silver_slice}

                    # Reset crash tracking state for clean simulation
                    self._last_crash_timestamp = None
                    self._recovery_start = None

                    # Run prediction
                    prediction = self.calculate_prediction(primary_metal, secondary_name)
                    if prediction is None:
                        continue

                    # Calculate confidence
                    confidence, signals = self.calculate_confidence(primary_metal, secondary_name, prediction)

                    # Calculate ATR and range
                    atr_val = self.calculate_atr(p_highs, p_lows, p_closes)
                    pred_price = prediction['predicted_price']
                    current_price = p_closes[-1]
                    range_low = pred_price - (atr_val * SQRT_7) if atr_val else None
                    range_high = pred_price + (atr_val * SQRT_7) if atr_val else None

                    # RSI
                    rsi = self.calculate_rsi(p_closes)

                    # Predicted change
                    predicted_change_pct = ((pred_price - current_price) / current_price) * 100 if current_price > 0 else 0

                    # === Actual price 7 days later ===
                    actual_price = primary_closes_all[day_idx + 7]
                    actual_change_pct = ((actual_price - current_price) / current_price) * 100 if current_price > 0 else 0

                    # Error and grading
                    error_pct = ((actual_price - pred_price) / pred_price) * 100 if pred_price > 0 else 0
                    abs_error_pct = abs(error_pct)
                    direction_correct = (actual_change_pct >= 0 and predicted_change_pct >= 0) or \
                                        (actual_change_pct < 0 and predicted_change_pct < 0)
                    in_range = (range_low <= actual_price <= range_high) if (range_low is not None and range_high is not None) else None

                    # Grade using the same grading scale
                    if abs_error_pct < 1:
                        grade = "A+"
                    elif abs_error_pct < 2:
                        grade = "A"
                    elif abs_error_pct < 3:
                        grade = "B+"
                    elif abs_error_pct < 4:
                        grade = "B"
                    elif abs_error_pct < 5:
                        grade = "C+"
                    elif abs_error_pct < 7:
                        grade = "C"
                    elif abs_error_pct < 10:
                        grade = "D"
                    else:
                        grade = "F"

                    # Get the date for this prediction
                    pred_date = primary_dates[day_idx]
                    pred_date_str = pred_date.strftime('%Y-%m-%d') if hasattr(pred_date, 'strftime') else str(pred_date)[:10]
                    target_date = primary_dates[day_idx + 7]
                    target_date_str = target_date.strftime('%Y-%m-%d') if hasattr(target_date, 'strftime') else str(target_date)[:10]

                    volatility_pct = (atr_val / current_price) * 100 if atr_val and current_price > 0 else None

                    results.append({
                        'prediction_date': pred_date_str,
                        'target_date': target_date_str,
                        'primary_metal': primary_metal,
                        'secondary_asset': secondary_name,
                        'current_price': round(current_price, 6),
                        'predicted_price': round(pred_price, 6),
                        'actual_price': round(actual_price, 6),
                        'predicted_change_pct': round(predicted_change_pct, 4),
                        'actual_change_pct': round(actual_change_pct, 4),
                        'error_pct': round(error_pct, 4),
                        'abs_error_pct': round(abs_error_pct, 4),
                        'price_difference': round(actual_price - pred_price, 6),
                        'direction_correct': direction_correct,
                        'grade': grade,
                        'in_range': in_range,
                        'range_low': round(range_low, 6) if range_low is not None else '',
                        'range_high': round(range_high, 6) if range_high is not None else '',
                        'confidence': round(confidence, 2),
                        'regime': prediction.get('regime', ''),
                        'regime_change': prediction.get('regime_change', False),
                        'beta': round(prediction.get('beta', 0), 4),
                        'correlation': round(prediction.get('correlation', 0), 4),
                        'rsi': round(rsi, 2) if rsi is not None else '',
                        'atr': round(atr_val, 6) if atr_val is not None else '',
                        'volatility_pct': round(volatility_pct, 4) if volatility_pct is not None else '',
                        'secondary_momentum': round(prediction.get('secondary_momentum', 0), 4),
                        'primary_expected_move': round(prediction.get('primary_expected_move', 0), 4),
                        'ratio_deviation_pct': round(prediction.get('ratio_deviation', 0), 4),
                        'ratio_pressure': round(prediction.get('ratio_pressure', 0), 4),
                    })
            finally:
                # Restore original state
                self.prediction_data = original_prediction_data
                self._last_crash_timestamp = original_crash_ts
                self._recovery_start = original_recovery

            if not results:
                raise Exception("No predictions could be generated. Insufficient data.")

            # === Calculate summary stats ===
            total = len(results)
            direction_correct_count = sum(1 for r in results if r['direction_correct'])
            avg_error = sum(r['abs_error_pct'] for r in results) / total
            in_range_results = [r for r in results if r['in_range'] is not None]
            in_range_count = sum(1 for r in in_range_results if r['in_range'])
            in_range_pct = (in_range_count / len(in_range_results) * 100) if in_range_results else 0

            grade_counts = {}
            for r in results:
                grade_counts[r['grade']] = grade_counts.get(r['grade'], 0) + 1

            # === Prompt for save location ===
            def ask_save():
                default_name = f"backtest_{primary_metal}_{secondary_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                filepath = filedialog.asksaveasfilename(
                    defaultextension=".csv",
                    filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
                    initialfile=default_name,
                    title="Export Back Test Results"
                )
                if filepath:
                    self._export_backtest_csv(filepath, results)

                    # Show summary
                    grade_summary = ", ".join(f"{g}: {c}" for g, c in sorted(grade_counts.items()))
                    messagebox.showinfo("Back Test Complete",
                        f"Back test complete!\n\n"
                        f"Period: {results[0]['prediction_date']} to {results[-1]['prediction_date']}\n"
                        f"Total predictions: {total}\n\n"
                        f"Direction accuracy: {direction_correct_count}/{total} ({direction_correct_count/total*100:.1f}%)\n"
                        f"Average error: {avg_error:.2f}%\n"
                        f"In-range: {in_range_count}/{len(in_range_results)} ({in_range_pct:.1f}%)\n\n"
                        f"Grades: {grade_summary}\n\n"
                        f"Results exported to:\n{filepath}")
                else:
                    self.pred_status_var.set("Back test complete (export cancelled)")

                self.pred_backtest_btn.config(state='normal')
                self.pred_status_var.set(f"Back test complete: {total} predictions, avg error {avg_error:.2f}%")

            self.root.after(0, ask_save)

        except Exception as e:
            def show_error():
                self.pred_backtest_btn.config(state='normal')
                self.pred_status_var.set("Back test failed")
                messagebox.showerror("Back Test Error", f"Error during back test:\n\n{str(e)}")
            self.root.after(0, show_error)

    def _export_backtest_csv(self, filepath, results):
        """Export backtest results to a CSV file."""
        if not results:
            return

        fieldnames = [
            'prediction_date', 'target_date', 'primary_metal', 'secondary_asset',
            'current_price', 'predicted_price', 'actual_price',
            'predicted_change_pct', 'actual_change_pct',
            'error_pct', 'abs_error_pct', 'price_difference',
            'direction_correct', 'grade', 'in_range',
            'range_low', 'range_high', 'confidence',
            'regime', 'regime_change',
            'beta', 'correlation', 'rsi', 'atr', 'volatility_pct',
            'secondary_momentum', 'primary_expected_move',
            'ratio_deviation_pct', 'ratio_pressure',
        ]

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

    def _force_refresh_history(self):
        """Force a complete refresh of the prediction history display"""
        if not hasattr(self, 'pred_history_listbox'):
            return
        
        # Reload from file to ensure we have latest data
        self.load_prediction_history()
        
        # Clear listbox
        self.pred_history_listbox.delete(0, tk.END)
        
        if not self.prediction_history:
            self.pred_history_listbox.insert(tk.END, "No predictions saved yet.")
            return
        
        # Sort by timestamp (newest first)
        sorted_history = sorted(self.prediction_history, key=lambda x: x['timestamp'], reverse=True)
        
        for record in sorted_history:
            timestamp = datetime.fromisoformat(record['timestamp']).strftime('%Y-%m-%d %H:%M')
            primary = record['primary_metal']
            secondary = record.get('secondary_metal', '?')
            predicted = record['predicted_price']
            confidence = record['confidence']
            
            if record['graded']:
                actual = record['actual_price']
                error = record['error_pct']
                direction = "✓" if record['direction_correct'] else "✗"
                grade = self.get_prediction_grade(record)
                line = f"[{timestamp}] {primary} vs {secondary}: ${predicted:.4f} → ${actual:.4f} | {direction} Dir | {error:+.2f}% err | Grade: {grade}"
            else:
                target_date = datetime.fromisoformat(record['target_date']).strftime('%Y-%m-%d')
                line = f"[{timestamp}] {primary} vs {secondary}: ${predicted:.4f} (Conf: {confidence:.0f}%) | Target: {target_date} | ⏳ Pending"
            
            self.pred_history_listbox.insert(tk.END, line)
        
        # Update status
        if hasattr(self, 'pred_history_status_var'):
            self.pred_history_status_var.set(f"Total: {len(self.prediction_history)} predictions")
        
        # Update accuracy
        self.update_accuracy_display()
    
    def refresh_prediction_history_display(self):
        """Refresh the prediction history listbox"""
        self._force_refresh_history()
    
    def get_prediction_grade(self, record):
        """Get a letter grade for a prediction based on error"""
        if not record['graded']:
            return "?"
        
        error = abs(record['error_pct'])
        
        if error < 1:
            return "A+"
        elif error < 2:
            return "A"
        elif error < 3:
            return "B+"
        elif error < 4:
            return "B"
        elif error < 5:
            return "C+"
        elif error < 7:
            return "C"
        elif error < 10:
            return "D"
        else:
            return "F"
    
    def update_accuracy_display(self):
        """Calculate and display accuracy metrics"""
        graded = [r for r in self.prediction_history if r['graded']]
        
        if not graded:
            self.pred_accuracy_var.set("No graded predictions yet")
            return
        
        # Calculate metrics
        total = len(graded)
        direction_correct = sum(1 for r in graded if r['direction_correct'])
        direction_pct = (direction_correct / total) * 100 if total > 0 else 0
        
        avg_error = sum(abs(r['error_pct']) for r in graded) / total
        
        # Calculate average grade
        grades = [self.get_prediction_grade(r) for r in graded]
        grade_values = {'A+': 4.3, 'A': 4.0, 'B+': 3.3, 'B': 3.0, 'C+': 2.3, 'C': 2.0, 'D': 1.0, 'F': 0}
        avg_grade_val = sum(grade_values.get(g, 0) for g in grades) / len(grades)
        
        # Convert back to letter
        if avg_grade_val >= 4.15:
            avg_grade = "A+"
        elif avg_grade_val >= 3.65:
            avg_grade = "A"
        elif avg_grade_val >= 3.15:
            avg_grade = "B+"
        elif avg_grade_val >= 2.65:
            avg_grade = "B"
        elif avg_grade_val >= 2.15:
            avg_grade = "C+"
        elif avg_grade_val >= 1.5:
            avg_grade = "C"
        elif avg_grade_val >= 0.5:
            avg_grade = "D"
        else:
            avg_grade = "F"
        
        # Confidence correlation (do high confidence predictions do better?)
        if len(graded) >= 3:
            high_conf = [r for r in graded if r['confidence'] >= 60]
            low_conf = [r for r in graded if r['confidence'] < 60]
            
            if high_conf and low_conf:
                high_conf_err = sum(abs(r['error_pct']) for r in high_conf) / len(high_conf)
                low_conf_err = sum(abs(r['error_pct']) for r in low_conf) / len(low_conf)
                conf_note = f" | High conf: {high_conf_err:.1f}% err, Low conf: {low_conf_err:.1f}% err"
            else:
                conf_note = ""
        else:
            conf_note = ""
        
        # Calculate in-range percentage
        range_graded = [r for r in graded if r.get('in_range') is not None]
        if range_graded:
            in_range_count = sum(1 for r in range_graded if r.get('in_range'))
            in_range_pct = (in_range_count / len(range_graded)) * 100
            range_note = f" | In Range: {in_range_pct:.0f}%"
        else:
            range_note = ""
        
        self.pred_accuracy_var.set(
            f"Grade: {avg_grade} | Direction: {direction_pct:.0f}% ({direction_correct}/{total}) | "
            f"Avg Error: {avg_error:.2f}%{range_note}{conf_note}"
        )
    
    def grade_predictions_thread(self):
        """Start grading predictions in a separate thread"""
        # Find ungraded predictions that have matured
        now = datetime.now()
        ungraded = [r for r in self.prediction_history 
                   if not r['graded'] and datetime.fromisoformat(r['target_date']) <= now]
        
        if not ungraded:
            messagebox.showinfo("No Predictions to Grade", 
                              "No matured predictions to grade.\n\n"
                              "Predictions are graded after their 7-day target date has passed.")
            return
        
        self.pred_history_status_var.set(f"Grading {len(ungraded)} predictions...")
        thread = threading.Thread(target=lambda: self.grade_predictions(ungraded), daemon=True)
        thread.start()
    
    def grade_predictions(self, ungraded):
        """Grade matured predictions by fetching actual prices from the target date"""
        import concurrent.futures
        import time
        
        try:
            graded_count = 0
            failed_count = 0
            
            for record in ungraded:
                metal = record['primary_metal']
                target_date = datetime.fromisoformat(record['target_date'])
                
                # Fetch price data for the target date with retry
                metal_config = METALS[metal]
                start_date = target_date - timedelta(days=3)
                end_date = target_date + timedelta(days=3)
                
                hist = None
                last_error = None
                
                for attempt in range(2):  # 2 retries
                    try:
                        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                            def fetch_grade_data():
                                ticker = yf.Ticker(metal_config['yf_ticker'])
                                return ticker.history(
                                    start=start_date.strftime('%Y-%m-%d'), 
                                    end=end_date.strftime('%Y-%m-%d')
                                )
                            
                            future = executor.submit(fetch_grade_data)
                            hist = future.result(timeout=20)
                            
                            if hist is not None and not hist.empty:
                                break
                            else:
                                last_error = "No data returned"
                                
                    except concurrent.futures.TimeoutError:
                        last_error = f"Timeout (attempt {attempt + 1})"
                    except Exception as e:
                        last_error = str(e)
                    
                    if attempt < 1:
                        time.sleep(1)
                
                if hist is None or hist.empty:
                    failed_count += 1
                    continue
                
                # Find the closest date to target_date
                target_date_only = target_date.date()
                best_price = None
                best_date_diff = None
                actual_date_used = None
                
                for idx in hist.index:
                    idx_date = idx.date() if hasattr(idx, 'date') else idx
                    date_diff = abs((idx_date - target_date_only).days)
                    
                    if best_date_diff is None or date_diff < best_date_diff:
                        best_date_diff = date_diff
                        best_price = float(hist.loc[idx, 'Close'])
                        actual_date_used = idx_date
                
                if best_price is None:
                    failed_count += 1
                    continue
                
                # Convert from $/oz to $/gram
                actual_price = best_price / TROY_OUNCE_TO_GRAMS
                
                # Calculate metrics
                predicted_price = record['predicted_price']
                current_price = record['current_price']
                
                actual_change_pct = ((actual_price - current_price) / current_price) * 100 if current_price > 0 else 0
                predicted_change_pct = record['predicted_change_pct']
                
                # Was direction correct?
                direction_correct = (actual_change_pct >= 0 and predicted_change_pct >= 0) or \
                                   (actual_change_pct < 0 and predicted_change_pct < 0)
                
                # Error percentage (how far off was the prediction?)
                error_pct = ((actual_price - predicted_price) / predicted_price) * 100 if predicted_price > 0 else 0
                
                # Was actual price within predicted range?
                range_low = record.get('range_low')
                range_high = record.get('range_high')
                if range_low is not None and range_high is not None:
                    in_range = range_low <= actual_price <= range_high
                else:
                    in_range = None
                
                # Update record
                record['actual_price'] = actual_price
                record['actual_date_used'] = str(actual_date_used) if actual_date_used else None
                record['actual_change_pct'] = actual_change_pct
                record['direction_correct'] = direction_correct
                record['error_pct'] = error_pct
                record['in_range'] = in_range
                record['graded'] = True
                record['graded_timestamp'] = datetime.now().isoformat()
                
                graded_count += 1
            
            # Save and refresh
            self.save_prediction_history()
            
            def update_ui():
                self.refresh_prediction_history_display()
                if failed_count > 0:
                    self.pred_history_status_var.set(f"Graded {graded_count}, {failed_count} failed (API issues)")
                else:
                    self.pred_history_status_var.set(f"Graded {graded_count} predictions")
            
            self.root.after(0, update_ui)
            
        except Exception as e:
            def show_error():
                self.pred_history_status_var.set("Error grading")
                messagebox.showerror("Grading Error", f"Error grading predictions:\n{e}\n\nPlease try again.")
            self.root.after(0, show_error)
    
    def clear_prediction_history(self):
        """Clear all prediction history"""
        if not self.prediction_history:
            messagebox.showinfo("Empty History", "No prediction history to clear.")
            return
        
        if messagebox.askyesno("Confirm Clear", 
                              f"Clear all {len(self.prediction_history)} prediction records?\n\n"
                              "This cannot be undone."):
            self.prediction_history = []
            self.save_prediction_history()
            self.refresh_prediction_history_display()
            self.pred_accuracy_var.set("No graded predictions yet")
            messagebox.showinfo("Cleared", "Prediction history cleared.")
    
    def delete_selected_prediction(self):
        """Delete the selected prediction from history"""
        if not hasattr(self, 'pred_history_listbox'):
            return
        
        selection = self.pred_history_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a prediction to delete.")
            return
        
        if not self.prediction_history:
            return
        
        # Get the index in the sorted list
        selected_idx = selection[0]
        
        # Sort by timestamp (newest first) - same order as display
        sorted_history = sorted(self.prediction_history, key=lambda x: x['timestamp'], reverse=True)
        
        if selected_idx >= len(sorted_history):
            return
        
        # Get the record to delete
        record_to_delete = sorted_history[selected_idx]
        
        # Show confirmation with details
        timestamp = datetime.fromisoformat(record_to_delete['timestamp']).strftime('%Y-%m-%d %H:%M')
        metal = record_to_delete['primary_metal']
        secondary = record_to_delete.get('secondary_metal', '?')
        predicted = record_to_delete['predicted_price']
        
        if messagebox.askyesno("Confirm Delete", 
                              f"Delete this prediction?\n\n"
                              f"Date: {timestamp}\n"
                              f"Metals: {metal} vs {secondary}\n"
                              f"Predicted: ${predicted:.4f}/g"):
            # Find and remove from the actual list
            self.prediction_history = [r for r in self.prediction_history 
                                       if r['id'] != record_to_delete['id']]
            self.save_prediction_history()
            self.refresh_prediction_history_display()
            self.pred_history_status_var.set("Prediction deleted")

    def update_status(self, message):
        """Update status label (thread-safe)"""
        self.root.after(0, lambda: self.status_label.config(text=message))
    
    def fetch_error(self, message):
        """Handle fetch error (thread-safe)"""
        def update():
            self.progress.stop()
            self.progress.pack_forget()
            self.status_label.config(text="Error")
            self.fetch_btn.config(state='normal')
            messagebox.showerror("Connection Error", message)
        self.root.after(0, update)
    
    def display_results(self):
        """Display the fetched results"""
        self.progress.stop()
        self.progress.pack_forget()
        self.status_label.config(text="")
        self.fetch_btn.config(state='normal')
        
        # Update metrics display
        self.refresh_metrics_display()
        
        # Update calculated prices
        self.refresh_calculated_prices_display()
        
        # Update timestamp
        self.timestamp_label.config(text=f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {self.current_metal}")
        
        # Refresh inventory display
        self.refresh_inventory_display()
        
        # Focus on weight entry
        self.weight_entry.focus_set()
    
    def refresh_metrics_display(self):
        """Refresh the metrics display with current unit"""
        unit_factor = UNITS[self.current_unit]['factor']
        unit_label = UNITS[self.current_unit]['label']
        
        for metric, var in self.metric_vars.items():
            if metric in self.metrics:
                value = self.metrics[metric] * unit_factor
                var.set(f"${value:.4f} {unit_label}")
            else:
                var.set("--")
    
    def refresh_calculated_prices_display(self):
        """Refresh the calculated prices based on formulas"""
        # Clear existing
        for widget in self.calc_prices_frame.winfo_children():
            widget.destroy()
        for widget in self.quick_calc_frame.winfo_children():
            widget.destroy()
        
        self.calc_price_vars = {}
        self.quick_calc_vars = {}
        
        unit_factor = UNITS[self.current_unit]['factor']
        unit_label = UNITS[self.current_unit]['label']
        tax_rate = self.get_current_tax_rate()
        
        # Filter formulas by selected group
        selected_group = self.formula_group_var.get() if hasattr(self, 'formula_group_var') else 'All Groups'
        if selected_group == 'All Groups':
            filtered_formulas = self.custom_formulas
        else:
            filtered_formulas = [f for f in self.custom_formulas if f.get('group', 'Default') == selected_group]
        
        if not filtered_formulas:
            ttk.Label(self.calc_prices_frame, text="No formulas in this group", 
                     foreground="gray", font=('Segoe UI', 9, 'italic')).pack(pady=10)
            return
        
        for i, formula in enumerate(filtered_formulas):
            # Calculate price
            price = self.calculate_formula_price(formula)
            
            # Display in metrics section
            row_frame = ttk.Frame(self.calc_prices_frame)
            row_frame.pack(fill='x', pady=2)
            
            ttk.Label(row_frame, text=f"{formula['name']}:", font=('Segoe UI', 9, 'bold')).pack(side='left')
            
            self.calc_price_vars[formula['name']] = tk.StringVar()
            if price is not None:
                display_price = price * unit_factor
                self.calc_price_vars[formula['name']].set(f"${display_price:.4f} {unit_label}")
            else:
                self.calc_price_vars[formula['name']].set("--")
            
            try:
                color = formula.get('color', '#000000')
                label = ttk.Label(row_frame, textvariable=self.calc_price_vars[formula['name']], 
                                 font=('Segoe UI', 11, 'bold'), foreground=color)
            except:
                label = ttk.Label(row_frame, textvariable=self.calc_price_vars[formula['name']], 
                                 font=('Segoe UI', 11, 'bold'))
            label.pack(side='left', padx=(10, 0))
            
            # Also add to quick calc results
            ttk.Label(self.quick_calc_frame, text=f"{formula['name']}:", font=('Segoe UI', 9)).grid(row=i, column=0, sticky='e', padx=(0, 5), pady=2)
            self.quick_calc_vars[formula['name']] = tk.StringVar(value="--")
            try:
                quick_label = ttk.Label(self.quick_calc_frame, textvariable=self.quick_calc_vars[formula['name']], 
                                       font=('Segoe UI', 12, 'bold'), foreground=formula.get('color', '#000000'))
            except:
                quick_label = ttk.Label(self.quick_calc_frame, textvariable=self.quick_calc_vars[formula['name']], 
                                       font=('Segoe UI', 12, 'bold'))
            quick_label.grid(row=i, column=1, sticky='w', pady=2)
    
    def calculate_formula_price(self, formula):
        """Calculate price based on formula expression"""
        if not self.metrics:
            return None
        
        expression = formula.get('expression', '')
        if not expression:
            # Legacy support for old weight-based formulas
            return self.calculate_legacy_formula(formula)
        
        try:
            # Build context with metric values using abbreviations
            context = {}
            for metric, abbrev in METRIC_ABBREVS.items():
                if metric in self.metrics:
                    context[abbrev] = self.metrics[metric]
                else:
                    # If metric not available, we can't calculate
                    return None
            
            # Safely evaluate the expression
            # Only allow basic math operations and our variables
            allowed_names = set(METRIC_ABBREVS.values())
            
            # Parse and validate expression
            price = self.safe_eval(expression, context)
            
            if price is None or price < 0:
                return None
            
            # Apply tax adjustment if enabled
            if formula.get('apply_tax', True):
                tax_rate = self.get_current_tax_rate()
                if tax_rate > 0:
                    price = price * (1 - tax_rate / 100)
            
            return price
            
        except Exception as e:
            print(f"Formula evaluation error: {e}")
            return None
    
    def calculate_legacy_formula(self, formula):
        """Calculate using old weight-based formula (for backwards compatibility)"""
        weights = formula.get('weights', {})
        if not weights:
            return None
        
        total_weight = sum(weights.values())
        if total_weight == 0:
            return None
        
        weighted_sum = 0
        for metric, weight in weights.items():
            if metric in self.metrics:
                weighted_sum += self.metrics[metric] * weight
            else:
                return None
        
        price = weighted_sum / total_weight
        
        # Apply tax
        if formula.get('apply_tax', True):
            tax_rate = self.get_current_tax_rate()
            if tax_rate > 0:
                price = price * (1 - tax_rate / 100)
        
        # Apply safety margin
        margin = formula.get('safety_margin', 0)
        if margin > 0:
            price = price * (1 - margin / 100)
        
        return price
    
    def safe_eval(self, expression, context):
        """Safely evaluate a mathematical expression with conditionals"""
        # Variables starting with numbers aren't valid Python identifiers
        # So we need to transform them (e.g., 7davg -> _7davg) for evaluation
        
        # Create mapping of user-facing names to Python-safe names
        safe_context = {}
        name_mapping = {}  # original -> safe
        for name, value in context.items():
            if name[0].isdigit():
                safe_name = f"_{name}"  # Prefix with underscore
            else:
                safe_name = name
            safe_context[safe_name] = value
            name_mapping[name] = safe_name
        
        # Transform the expression to use safe names
        # Sort by length (longest first) to avoid partial replacements
        safe_expression = expression
        for original, safe in sorted(name_mapping.items(), key=lambda x: len(x[0]), reverse=True):
            # Use word boundary matching to avoid partial replacements
            safe_expression = re.sub(r'(?<![a-zA-Z0-9_])' + re.escape(original) + r'(?![a-zA-Z0-9_])', 
                                    safe, safe_expression)
        
        # Build regex pattern for validation - include function names and comparison operators
        allowed_functions = ['min', 'max', 'iif']
        var_pattern = '|'.join(sorted(list(safe_context.keys()) + allowed_functions, key=len, reverse=True))
        # Pattern includes comparison operators
        pattern = f'({var_pattern})|([\\d.]+)|([+\\-*/()<>=!,]+)|\\s+'
        
        # Tokenize
        tokens = re.findall(pattern, safe_expression)
        
        # Flatten and filter empty strings
        flat_tokens = []
        for match in tokens:
            for group in match:
                if group and group.strip():
                    flat_tokens.append(group.strip())
        
        # Validate each token
        allowed_names = set(safe_context.keys()) | set(allowed_functions)
        allowed_operators = set(['+-*/()<>=!,', '+', '-', '*', '/', '(', ')', '<', '>', '<=', '>=', '==', '!=', ','])
        
        for token in flat_tokens:
            # Check if it's a number
            try:
                float(token)
                continue  # Valid number
            except ValueError:
                pass
            
            # Check if it's a known variable or function
            if token in allowed_names:
                continue
            
            # Check if it's an operator (including comparison)
            if all(c in '+-*/()<>=!,' for c in token):
                continue
            
            # Invalid token - show user-friendly variable names in error
            user_vars = ', '.join(sorted(context.keys()))
            raise ValueError(f"Invalid token: '{token}'. Valid variables are: {user_vars}")
        
        # Create safe evaluation environment with allowed functions
        def safe_iif(condition, true_val, false_val):
            """Immediate If function: iif(condition, true_value, false_value)"""
            return true_val if condition else false_val
        
        eval_dict = {
            "__builtins__": {},
            "min": min,
            "max": max,
            "iif": safe_iif,
        }
        eval_dict.update(safe_context)
        
        result = eval(safe_expression, eval_dict, {})
        return float(result)
    
    # =========================================================================
    # QUICK CALCULATOR
    # =========================================================================
    
    def get_purity_decimal(self):
        """Get purity as a decimal"""
        purity_str = self.purity_var.get()
        
        if purity_str == 'Custom...':
            try:
                return float(self.custom_purity_var.get()) / 100
            except ValueError:
                return 1.0
        
        # Look up in metal-specific grades
        grades = PURITY_GRADES.get(self.current_metal, [])
        for name, value in grades:
            if name == purity_str:
                if value > 0:
                    return value / 100
                break
        
        # Fallback: try to parse percentage from string
        try:
            # Extract number from string like "92.5% (Sterling)"
            match = re.search(r'([\d.]+)%', purity_str)
            if match:
                return float(match.group(1)) / 100
        except:
            pass
        
        return 1.0  # Default to 100%
    
    def calculate_quick(self):
        """Calculate values for quick calculator"""
        if 'current_price' not in self.metrics:
            messagebox.showwarning("No Price Data", "Please fetch live prices first.")
            return
        
        try:
            weight_str = self.weight_entry.get().strip()
            if not weight_str:
                messagebox.showwarning("Input Required", "Please enter a weight.")
                return
            
            weight = float(weight_str)
            shipping = float(self.shipping_entry.get().strip() or 0)
            
            if weight <= 0:
                messagebox.showwarning("Invalid Input", "Weight must be positive.")
                return
            
            # Convert weight to grams
            weight_unit = self.weight_unit_var.get()
            if weight_unit == 'oz':
                weight_grams = weight * TROY_OUNCE_TO_GRAMS
            elif weight_unit == 'lb':
                weight_grams = weight * POUND_TO_GRAMS
            else:
                weight_grams = weight
            
            # Calculate pure metal content
            purity = self.get_purity_decimal()
            metal_content = weight_grams * purity
            
            # Market value (current price × content)
            market_value = metal_content * self.metrics['current_price']
            
            # Update display
            self.metal_content_var.set(f"{metal_content:.2f} grams of pure {self.current_metal}")
            self.market_value_var.set(f"${market_value:.2f}")
            
            # Calculate formula prices (only for formulas currently displayed)
            for formula in self.custom_formulas:
                # Only update if this formula is in the quick calc vars (i.e., it's being displayed)
                if formula['name'] in self.quick_calc_vars:
                    price_per_gram = self.calculate_formula_price(formula)
                    if price_per_gram is not None:
                        total_price = (metal_content * price_per_gram) - shipping
                        self.quick_calc_vars[formula['name']].set(f"${total_price:.2f}")
                    else:
                        self.quick_calc_vars[formula['name']].set("--")
            
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter valid numbers.")
    
    # =========================================================================
    # FORMULA MANAGEMENT
    # =========================================================================
    
    def refresh_formula_list(self):
        """Refresh the formula listbox"""
        self.formula_listbox.delete(0, tk.END)
        
        # Get filter group
        filter_group = self.formula_list_group_var.get() if hasattr(self, 'formula_list_group_var') else 'All Groups'
        
        for i, formula in enumerate(self.custom_formulas):
            # Filter by group if not showing all
            formula_group = formula.get('group', 'Default')
            if filter_group != 'All Groups' and formula_group != filter_group:
                continue
                
            tax = "w/tax" if formula.get('apply_tax', True) else "no tax"
            expr = formula.get('expression', 'legacy weights')
            # Truncate expression if too long
            if len(expr) > 30:
                expr = expr[:27] + "..."
            self.formula_listbox.insert(tk.END, f"[{formula_group}] {formula['name']} ({tax}) - {expr}")
    
    def new_formula(self):
        """Create a new formula"""
        self.open_formula_editor(None)
    
    def edit_formula(self):
        """Edit selected formula"""
        idx = self.get_selected_formula_index()
        if idx is None:
            messagebox.showwarning("No Selection", "Please select a formula to edit.")
            return
        self.open_formula_editor(idx)
    
    def delete_formula(self):
        """Delete selected formula"""
        idx = self.get_selected_formula_index()
        if idx is None:
            messagebox.showwarning("No Selection", "Please select a formula to delete.")
            return
        
        if len(self.custom_formulas) <= 1:
            messagebox.showwarning("Cannot Delete", "You must have at least one formula.")
            return
        
        if messagebox.askyesno("Confirm Delete", "Delete this formula?"):
            del self.custom_formulas[idx]
            self.save_formulas()
            self.refresh_formula_list()
            self.refresh_calculated_prices_display()
    
    def duplicate_formula(self):
        """Duplicate selected formula"""
        selection = self.formula_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a formula to duplicate.")
            return
        
        # Get the actual formula (accounting for filtering)
        original = self.get_selected_formula()
        if not original:
            return
            
        duplicate = {
            'name': f"{original['name']} (Copy)",
            'color': original.get('color', '#000000'),
            'expression': original.get('expression', ''),
            'apply_tax': original.get('apply_tax', True),
            'description': original.get('description', ''),
            'group': original.get('group', 'Default')
        }
        self.custom_formulas.append(duplicate)
        self.save_formulas()
        self.refresh_formula_list()
        self.refresh_calculated_prices_display()
    
    def get_selected_formula(self):
        """Get the currently selected formula (accounting for filtering)"""
        selection = self.formula_listbox.curselection()
        if not selection:
            return None
        
        # Rebuild the filtered list to find the actual index
        filter_group = self.formula_list_group_var.get() if hasattr(self, 'formula_list_group_var') else 'All Groups'
        filtered_indices = []
        for i, formula in enumerate(self.custom_formulas):
            formula_group = formula.get('group', 'Default')
            if filter_group == 'All Groups' or formula_group == filter_group:
                filtered_indices.append(i)
        
        if selection[0] < len(filtered_indices):
            return self.custom_formulas[filtered_indices[selection[0]]]
        return None
    
    def get_selected_formula_index(self):
        """Get the actual index of the selected formula in custom_formulas"""
        selection = self.formula_listbox.curselection()
        if not selection:
            return None
        
        filter_group = self.formula_list_group_var.get() if hasattr(self, 'formula_list_group_var') else 'All Groups'
        filtered_indices = []
        for i, formula in enumerate(self.custom_formulas):
            formula_group = formula.get('group', 'Default')
            if filter_group == 'All Groups' or formula_group == filter_group:
                filtered_indices.append(i)
        
        if selection[0] < len(filtered_indices):
            return filtered_indices[selection[0]]
        return None
    
    def test_formula(self):
        """Test the selected formula with current metrics"""
        formula = self.get_selected_formula()
        if not formula:
            messagebox.showwarning("No Selection", "Please select a formula to test.")
            return
        
        if not self.metrics:
            messagebox.showwarning("No Price Data", "Please fetch live prices first to test formulas.")
            return
        
        # Show test dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Test Formula: {formula['name']}")
        dialog.geometry("500x400")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 250
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 200
        dialog.geometry(f"+{x}+{y}")
        
        main_frame = ttk.Frame(dialog, padding="20")
        main_frame.pack(fill='both', expand=True)
        
        ttk.Label(main_frame, text=f"Testing: {formula['name']}", font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        ttk.Label(main_frame, text=f"Expression: {formula.get('expression', 'N/A')}", font=('Consolas', 9)).pack(anchor='w', pady=(5, 10))
        
        # Current values
        ttk.Label(main_frame, text="Current Metric Values (per gram):", font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(10, 5))
        
        values_frame = ttk.Frame(main_frame)
        values_frame.pack(fill='x')
        
        row = 0
        col = 0
        for metric, abbrev in METRIC_ABBREVS.items():
            value = self.metrics.get(metric, 0)
            text = f"{abbrev} = ${value:.4f}"
            ttk.Label(values_frame, text=text, font=('Consolas', 9)).grid(row=row, column=col, sticky='w', padx=10, pady=1)
            col += 1
            if col >= 2:
                col = 0
                row += 1
        
        ttk.Separator(main_frame, orient='horizontal').pack(fill='x', pady=15)
        
        # Result
        ttk.Label(main_frame, text="Calculation Result:", font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        
        result = self.calculate_formula_price(formula)
        
        if result is not None:
            unit_factor = UNITS[self.current_unit]['factor']
            unit_label = UNITS[self.current_unit]['label']
            result_display = result * unit_factor
            
            result_text = f"${result_display:.4f} {unit_label}"
            ttk.Label(main_frame, text=result_text, font=('Segoe UI', 16, 'bold'), foreground=formula.get('color', '#000000')).pack(anchor='w', pady=5)
            
            if formula.get('apply_tax', True):
                tax_rate = self.get_current_tax_rate()
                ttk.Label(main_frame, text=f"(Tax adjustment of {tax_rate}% applied)", foreground='gray').pack(anchor='w')
        else:
            ttk.Label(main_frame, text="Could not calculate - check expression for errors", foreground='red', font=('Segoe UI', 10)).pack(anchor='w', pady=5)
        
        ttk.Button(main_frame, text="Close", command=dialog.destroy).pack(pady=(20, 0))
    
    def new_formula_group(self):
        """Create a new formula group"""
        name = simpledialog.askstring("New Group", "Enter group name:", parent=self.root)
        if name:
            name = name.strip()
            if name and name not in self.formula_groups and name != 'All Groups':
                self.formula_groups.append(name)
                self.settings['formula_groups'] = self.formula_groups
                self.save_settings()
                self.update_formula_group_dropdown()
                self.refresh_formula_list()
                messagebox.showinfo("Success", f"Group '{name}' created.")
            elif name in self.formula_groups:
                messagebox.showwarning("Duplicate", f"Group '{name}' already exists.")
    
    def rename_formula_group(self):
        """Rename an existing formula group"""
        # Ask which group to rename
        groups_to_rename = [g for g in self.formula_groups if g != 'Default']
        if not groups_to_rename:
            messagebox.showinfo("No Groups", "No custom groups to rename. (Default group cannot be renamed)")
            return
        
        # Simple dialog to select group
        dialog = tk.Toplevel(self.root)
        dialog.title("Rename Group")
        dialog.geometry("300x200")
        dialog.transient(self.root)
        dialog.grab_set()
        
        ttk.Label(dialog, text="Select group to rename:").pack(pady=(20, 5))
        group_var = tk.StringVar(value=groups_to_rename[0])
        combo = ttk.Combobox(dialog, textvariable=group_var, values=groups_to_rename, state='readonly', width=20)
        combo.pack(pady=5)
        
        ttk.Label(dialog, text="New name:").pack(pady=(10, 5))
        name_entry = ttk.Entry(dialog, width=25)
        name_entry.pack(pady=5)
        
        def do_rename():
            old_name = group_var.get()
            new_name = name_entry.get().strip()
            if not new_name:
                messagebox.showwarning("Empty Name", "Please enter a new name.")
                return
            if new_name in self.formula_groups:
                messagebox.showwarning("Duplicate", f"Group '{new_name}' already exists.")
                return
            if new_name == 'All Groups':
                messagebox.showwarning("Reserved Name", "'All Groups' is reserved.")
                return
            # Update group list
            idx = self.formula_groups.index(old_name)
            self.formula_groups[idx] = new_name
            # Update all formulas with this group
            for formula in self.custom_formulas:
                if formula.get('group') == old_name:
                    formula['group'] = new_name
            self.settings['formula_groups'] = self.formula_groups
            self.save_settings()
            self.save_formulas()
            self.update_formula_group_dropdown()
            self.refresh_formula_list()
            self.refresh_calculated_prices_display()
            dialog.destroy()
            messagebox.showinfo("Success", f"Group renamed to '{new_name}'.")
        
        # Button frame
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=15)
        
        ttk.Button(btn_frame, text="Save", command=do_rename, width=10).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy, width=10).pack(side='left', padx=5)
    
    def delete_formula_group(self):
        """Delete a formula group (moves formulas to Default)"""
        groups_to_delete = [g for g in self.formula_groups if g != 'Default']
        if not groups_to_delete:
            messagebox.showinfo("No Groups", "No custom groups to delete. (Default group cannot be deleted)")
            return
        
        # Simple dialog to select group
        dialog = tk.Toplevel(self.root)
        dialog.title("Delete Group")
        dialog.geometry("350x150")
        dialog.transient(self.root)
        dialog.grab_set()
        
        ttk.Label(dialog, text="Select group to delete:").pack(pady=(20, 5))
        group_var = tk.StringVar(value=groups_to_delete[0])
        combo = ttk.Combobox(dialog, textvariable=group_var, values=groups_to_delete, state='readonly', width=20)
        combo.pack(pady=5)
        
        ttk.Label(dialog, text="(Formulas will be moved to Default group)", foreground='gray').pack(pady=5)
        
        def do_delete():
            group_name = group_var.get()
            if messagebox.askyesno("Confirm Delete", f"Delete group '{group_name}'?\n\nFormulas will be moved to Default group."):
                # Move formulas to Default
                for formula in self.custom_formulas:
                    if formula.get('group') == group_name:
                        formula['group'] = 'Default'
                # Remove group
                self.formula_groups.remove(group_name)
                self.settings['formula_groups'] = self.formula_groups
                self.save_settings()
                self.save_formulas()
                self.update_formula_group_dropdown()
                self.refresh_formula_list()
                self.refresh_calculated_prices_display()
                dialog.destroy()
                messagebox.showinfo("Success", f"Group '{group_name}' deleted.")
        
        ttk.Button(dialog, text="Delete", command=do_delete).pack(pady=10)

    def open_formula_editor(self, index):
        """Open the formula editor dialog"""
        is_new = index is None
        formula = {} if is_new else self.custom_formulas[index].copy()
        
        # Create dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("New Formula" if is_new else "Edit Formula")
        dialog.geometry("620x680")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Center on parent
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 310
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 340
        dialog.geometry(f"+{x}+{y}")
        
        main_frame = ttk.Frame(dialog, padding="20")
        main_frame.pack(fill='both', expand=True)
        
        # Name
        name_frame = ttk.Frame(main_frame)
        name_frame.pack(fill='x', pady=(0, 10))
        ttk.Label(name_frame, text="Formula Name:").pack(side='left')
        name_entry = ttk.Entry(name_frame, width=30)
        name_entry.pack(side='left', padx=(10, 0))
        name_entry.insert(0, formula.get('name', ''))
        
        # Color
        color_frame = ttk.Frame(main_frame)
        color_frame.pack(fill='x', pady=(0, 10))
        ttk.Label(color_frame, text="Display Color:").pack(side='left')
        color_var = tk.StringVar(value=formula.get('color', '#008000'))
        color_combo = ttk.Combobox(color_frame, textvariable=color_var, width=20)
        color_combo['values'] = ['#008000 (Green)', '#CC7000 (Orange)', '#CC0000 (Red)', '#0000CC (Blue)', '#800080 (Purple)', '#000000 (Black)']
        color_combo.pack(side='left', padx=(10, 0))
        
        # Group
        group_frame = ttk.Frame(main_frame)
        group_frame.pack(fill='x', pady=(0, 10))
        ttk.Label(group_frame, text="Group:").pack(side='left')
        group_var = tk.StringVar(value=formula.get('group', 'Default'))
        group_combo = ttk.Combobox(group_frame, textvariable=group_var, width=20)
        group_combo['values'] = self.formula_groups
        group_combo.pack(side='left', padx=(10, 0))
        ttk.Label(group_frame, text="(Use groups to organize formulas by buying venue)", 
                 font=('Segoe UI', 8), foreground='gray').pack(side='left', padx=(10, 0))
        
        # Description
        desc_frame = ttk.Frame(main_frame)
        desc_frame.pack(fill='x', pady=(0, 10))
        ttk.Label(desc_frame, text="Description:").pack(side='left')
        desc_entry = ttk.Entry(desc_frame, width=50)
        desc_entry.pack(side='left', padx=(10, 0))
        desc_entry.insert(0, formula.get('description', ''))
        
        # Apply tax checkbox
        tax_var = tk.BooleanVar(value=formula.get('apply_tax', True))
        ttk.Checkbutton(main_frame, text="Apply sales tax adjustment to result", variable=tax_var).pack(anchor='w', pady=(0, 10))
        
        # Variable reference
        ref_frame = ttk.LabelFrame(main_frame, text=" Available Variables & Functions ", padding="5")
        ref_frame.pack(fill='x', pady=(0, 10))
        
        ref_text = "  ".join([f"{abbrev}={METRIC_LABELS[metric]}" for metric, abbrev in METRIC_ABBREVS.items()])
        ttk.Label(ref_frame, text=ref_text, font=('Consolas', 8), wraplength=550).pack(anchor='w')
        ttk.Label(ref_frame, text="Functions: min(a,b)  max(a,b)  iif(condition, true_val, false_val)", font=('Consolas', 8), foreground='gray').pack(anchor='w')
        ttk.Label(ref_frame, text="Compare: < > <= >= == !=    Math: + - * / ( )", font=('Consolas', 8), foreground='gray').pack(anchor='w')
        
        # Expression entry
        expr_frame = ttk.LabelFrame(main_frame, text=" Formula Expression ", padding="10")
        expr_frame.pack(fill='x', pady=(0, 10))
        
        ttk.Label(expr_frame, text="Enter your formula using variables and math operators (+, -, *, /, parentheses):", 
                 font=('Segoe UI', 9)).pack(anchor='w')
        
        expr_entry = ttk.Entry(expr_frame, width=70, font=('Consolas', 11))
        expr_entry.pack(fill='x', pady=(5, 0))
        expr_entry.insert(0, formula.get('expression', ''))
        
        # Quick insert buttons
        insert_frame = ttk.Frame(expr_frame)
        insert_frame.pack(fill='x', pady=(5, 0))
        ttk.Label(insert_frame, text="Insert:", font=('Segoe UI', 8)).pack(side='left')
        
        def insert_var(var):
            expr_entry.insert(tk.INSERT, var)
            expr_entry.focus_set()
        
        for abbrev in list(METRIC_ABBREVS.values())[:5]:  # Show first 5 variables
            btn = ttk.Button(insert_frame, text=abbrev, width=6, command=lambda v=abbrev: insert_var(v))
            btn.pack(side='left', padx=2)
        
        # More variables dropdown
        more_vars = list(METRIC_ABBREVS.values())[5:]
        if more_vars:
            more_var = tk.StringVar(value="more...")
            more_combo = ttk.Combobox(insert_frame, textvariable=more_var, values=more_vars, width=8, state='readonly')
            more_combo.pack(side='left', padx=2)
            more_combo.bind('<<ComboboxSelected>>', lambda e: (insert_var(more_var.get()), more_var.set("more...")))
        
        # Function insert buttons
        insert_frame2 = ttk.Frame(expr_frame)
        insert_frame2.pack(fill='x', pady=(2, 0))
        ttk.Label(insert_frame2, text="Functions:", font=('Segoe UI', 8)).pack(side='left')
        
        ttk.Button(insert_frame2, text="min(,)", width=7, command=lambda: insert_var("min(, )")).pack(side='left', padx=2)
        ttk.Button(insert_frame2, text="max(,)", width=7, command=lambda: insert_var("max(, )")).pack(side='left', padx=2)
        ttk.Button(insert_frame2, text="iif(,,)", width=7, command=lambda: insert_var("iif(, , )")).pack(side='left', padx=2)
        
        ttk.Label(insert_frame2, text="  Compare:", font=('Segoe UI', 8)).pack(side='left', padx=(10, 0))
        for op in ['<', '>', '<=', '>=']:
            ttk.Button(insert_frame2, text=op, width=3, command=lambda v=op: insert_var(f" {v} ")).pack(side='left', padx=1)
        
        # Validation/Preview
        preview_frame = ttk.LabelFrame(main_frame, text=" Live Preview ", padding="10")
        preview_frame.pack(fill='x', pady=(0, 10))
        
        preview_var = tk.StringVar(value="Enter an expression above to see preview")
        preview_label = ttk.Label(preview_frame, textvariable=preview_var, font=('Consolas', 10), wraplength=550)
        preview_label.pack(anchor='w')
        
        def update_preview(*args):
            expression = expr_entry.get().strip()
            if not expression:
                preview_var.set("Enter an expression above to see preview")
                return
            
            # Check syntax
            try:
                # Create dummy context for validation
                dummy_context = {abbrev: 1.0 for abbrev in METRIC_ABBREVS.values()}
                result = self.safe_eval(expression, dummy_context)
                
                if self.metrics:
                    # Calculate with real values
                    real_context = {}
                    for metric, abbrev in METRIC_ABBREVS.items():
                        real_context[abbrev] = self.metrics.get(metric, 0)
                    
                    real_result = self.safe_eval(expression, real_context)
                    
                    if tax_var.get():
                        tax_rate = self.get_current_tax_rate()
                        if tax_rate > 0:
                            real_result = real_result * (1 - tax_rate / 100)
                    
                    preview_var.set(f"✓ Valid expression\nWith current prices: ${real_result:.4f}/gram")
                else:
                    preview_var.set(f"✓ Valid expression (fetch prices to see calculated value)")
                    
            except Exception as e:
                preview_var.set(f"✗ Error: {str(e)}")
        
        expr_entry.bind('<KeyRelease>', update_preview)
        tax_var.trace('w', update_preview)
        update_preview()
        
        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(pady=(10, 0))
        
        def save_formula():
            name = name_entry.get().strip()
            if not name:
                messagebox.showwarning("Name Required", "Please enter a formula name.")
                return
            
            expression = expr_entry.get().strip()
            if not expression:
                messagebox.showwarning("Expression Required", "Please enter a formula expression.")
                return
            
            # Validate expression
            try:
                dummy_context = {abbrev: 1.0 for abbrev in METRIC_ABBREVS.values()}
                self.safe_eval(expression, dummy_context)
            except Exception as e:
                messagebox.showerror("Invalid Expression", f"The expression has an error:\n{e}")
                return
            
            # Get color (strip description)
            color = color_var.get().split()[0] if color_var.get() else '#000000'
            
            # Get group (ensure it exists, default to Default)
            group = group_var.get().strip()
            if not group or group not in self.formula_groups:
                group = 'Default'
            
            new_formula = {
                'name': name,
                'color': color,
                'expression': expression,
                'apply_tax': tax_var.get(),
                'description': desc_entry.get().strip(),
                'group': group
            }
            
            if is_new:
                self.custom_formulas.append(new_formula)
            else:
                self.custom_formulas[index] = new_formula
            
            self.save_formulas()
            self.refresh_formula_list()
            self.refresh_calculated_prices_display()
            dialog.destroy()
        
        ttk.Button(btn_frame, text="💾 Save Formula", command=save_formula).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side='left', padx=5)
    
    # =========================================================================
    # INVENTORY MANAGEMENT
    # =========================================================================
    
    def add_inventory_item(self):
        """Add a new item to inventory"""
        try:
            item_id = self.inv_id_entry.get().strip()
            metal = self.inv_metal_var.get()
            description = self.inv_desc_entry.get().strip()
            weight = float(self.inv_weight_entry.get().strip())
            weight_unit = self.inv_weight_unit_var.get()
            purity = float(self.inv_purity_entry.get().strip())
            purchase_price = float(self.inv_price_entry.get().strip())
            profit_goal = float(self.inv_goal_entry.get().strip())
            
            if not item_id:
                messagebox.showwarning("Input Required", "Please enter an Item ID.")
                return
            
            if weight <= 0:
                messagebox.showwarning("Invalid Input", "Weight must be positive.")
                return
            
            if purchase_price < 0:
                messagebox.showwarning("Invalid Input", "Purchase price cannot be negative.")
                return
            
            # Check for duplicate ID
            for item in self.inventory:
                if item['id'] == item_id:
                    messagebox.showwarning("Duplicate ID", f"Item ID '{item_id}' already exists.")
                    return
            
            # Convert weight to grams
            if weight_unit == 'oz':
                weight_grams = weight * TROY_OUNCE_TO_GRAMS
            elif weight_unit == 'lb':
                weight_grams = weight * POUND_TO_GRAMS
            else:
                weight_grams = weight
            
            # Calculate metal content
            metal_content = weight_grams * (purity / 100)
            cost_per_gram = purchase_price / metal_content if metal_content > 0 and purchase_price > 0 else 0
            
            item = {
                'id': item_id,
                'metal': metal,
                'description': description,
                'weight': weight,
                'weight_unit': weight_unit,
                'weight_grams': weight_grams,
                'purity': purity,
                'metal_content': metal_content,
                'purchase_price': purchase_price,
                'cost_per_gram': cost_per_gram,
                'purchase_date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'profit_goal': profit_goal
            }
            
            self.inventory.append(item)
            self.save_inventory()
            
            # Clear inputs
            self.inv_id_entry.delete(0, tk.END)
            self.inv_desc_entry.delete(0, tk.END)
            self.inv_weight_entry.delete(0, tk.END)
            self.inv_price_entry.delete(0, tk.END)
            
            self.refresh_inventory_display()
            messagebox.showinfo("Success", f"Item '{item_id}' added to inventory.")
            
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter valid numbers.")
    
    def delete_selected_item(self):
        """Delete selected inventory item"""
        if self.selected_item_id is None:
            messagebox.showwarning("No Selection", "Please click on an item to select it first.")
            return
        
        if messagebox.askyesno("Confirm Delete", f"Delete item '{self.selected_item_id}'?"):
            self.inventory = [item for item in self.inventory if item['id'] != self.selected_item_id]
            self.save_inventory()
            self.selected_item_id = None
            self.refresh_inventory_display()
    
    def edit_selected_item(self):
        """Edit selected inventory item"""
        if self.selected_item_id is None:
            messagebox.showwarning("No Selection", "Please click on an item to select it first.")
            return
        
        item = None
        for i in self.inventory:
            if i['id'] == self.selected_item_id:
                item = i
                break
        
        if item is None:
            return
        
        # Create edit dialog
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit Item: {item['id']}")
        dialog.geometry("400x400")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 200
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 200
        dialog.geometry(f"+{x}+{y}")
        
        form_frame = ttk.Frame(dialog, padding="20")
        form_frame.pack(fill='both', expand=True)
        
        # Fields
        ttk.Label(form_frame, text="Item ID:").grid(row=0, column=0, sticky='e', padx=(0, 10), pady=5)
        id_entry = ttk.Entry(form_frame, width=20)
        id_entry.grid(row=0, column=1, sticky='w', pady=5)
        id_entry.insert(0, item['id'])
        
        ttk.Label(form_frame, text="Metal:").grid(row=1, column=0, sticky='e', padx=(0, 10), pady=5)
        metal_var = tk.StringVar(value=item['metal'])
        metal_combo = ttk.Combobox(form_frame, textvariable=metal_var, state='readonly', width=15)
        metal_combo['values'] = list(METALS.keys())
        metal_combo.grid(row=1, column=1, sticky='w', pady=5)
        
        ttk.Label(form_frame, text="Description:").grid(row=2, column=0, sticky='e', padx=(0, 10), pady=5)
        desc_entry = ttk.Entry(form_frame, width=30)
        desc_entry.grid(row=2, column=1, sticky='w', pady=5)
        desc_entry.insert(0, item.get('description', ''))
        
        ttk.Label(form_frame, text="Weight:").grid(row=3, column=0, sticky='e', padx=(0, 10), pady=5)
        weight_entry = ttk.Entry(form_frame, width=15)
        weight_entry.grid(row=3, column=1, sticky='w', pady=5)
        weight_entry.insert(0, str(item['weight']))
        
        ttk.Label(form_frame, text="Purity (%):").grid(row=4, column=0, sticky='e', padx=(0, 10), pady=5)
        purity_entry = ttk.Entry(form_frame, width=10)
        purity_entry.grid(row=4, column=1, sticky='w', pady=5)
        purity_entry.insert(0, str(item['purity']))
        
        ttk.Label(form_frame, text="Purchase Price ($):").grid(row=5, column=0, sticky='e', padx=(0, 10), pady=5)
        price_entry = ttk.Entry(form_frame, width=15)
        price_entry.grid(row=5, column=1, sticky='w', pady=5)
        price_entry.insert(0, str(item['purchase_price']))
        
        ttk.Label(form_frame, text="Purchase Date:").grid(row=6, column=0, sticky='e', padx=(0, 10), pady=5)
        date_entry = ttk.Entry(form_frame, width=20)
        date_entry.grid(row=6, column=1, sticky='w', pady=5)
        date_entry.insert(0, item.get('purchase_date', ''))
        
        ttk.Label(form_frame, text="Profit Goal (%):").grid(row=7, column=0, sticky='e', padx=(0, 10), pady=5)
        goal_entry = ttk.Entry(form_frame, width=10)
        goal_entry.grid(row=7, column=1, sticky='w', pady=5)
        goal_entry.insert(0, str(item.get('profit_goal', 100)))
        
        def save_changes():
            try:
                new_id = id_entry.get().strip()
                new_weight = float(weight_entry.get().strip())
                new_purity = float(purity_entry.get().strip())
                new_price = float(price_entry.get().strip())
                new_goal = float(goal_entry.get().strip())
                
                if not new_id:
                    messagebox.showwarning("Invalid Input", "Item ID cannot be empty.")
                    return
                
                # Check for duplicate ID (if changed)
                old_id = item['id']
                if new_id != old_id:
                    for inv_item in self.inventory:
                        if inv_item['id'] == new_id:
                            messagebox.showwarning("Duplicate ID", f"Item ID '{new_id}' already exists.")
                            return
                
                if new_weight <= 0:
                    messagebox.showwarning("Invalid Input", "Weight must be positive.")
                    return
                
                if new_price < 0:
                    messagebox.showwarning("Invalid Input", "Purchase price cannot be negative.")
                    return
                
                # Recalculate
                weight_unit = item.get('weight_unit', 'grams')
                if weight_unit == 'oz':
                    weight_grams = new_weight * TROY_OUNCE_TO_GRAMS
                elif weight_unit == 'lb':
                    weight_grams = new_weight * POUND_TO_GRAMS
                else:
                    weight_grams = new_weight
                
                metal_content = weight_grams * (new_purity / 100)
                
                # Update item
                item['id'] = new_id
                item['metal'] = metal_var.get()
                item['description'] = desc_entry.get().strip()
                item['weight'] = new_weight
                item['weight_grams'] = weight_grams
                item['purity'] = new_purity
                item['metal_content'] = metal_content
                item['purchase_price'] = new_price
                item['cost_per_gram'] = new_price / metal_content if metal_content > 0 and new_price > 0 else 0
                item['purchase_date'] = date_entry.get().strip()
                item['profit_goal'] = new_goal
                
                # Update selected item ID tracker
                self.selected_item_id = new_id
                
                self.save_inventory()
                self.refresh_inventory_display()
                dialog.destroy()
                messagebox.showinfo("Success", f"Item '{new_id}' updated.")
                
            except ValueError:
                messagebox.showerror("Invalid Input", "Please enter valid numbers.")
        
        btn_frame = ttk.Frame(form_frame)
        btn_frame.grid(row=8, column=0, columnspan=2, pady=(20, 0))
        ttk.Button(btn_frame, text="💾 Save Changes", command=save_changes).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side='left', padx=5)
    
    def fetch_inventory_prices_thread(self):
        """Start fetching prices for all metals in a separate thread"""
        self.inv_fetch_btn.config(state='disabled')
        self.inv_status_label.config(text="Fetching prices...")
        
        thread = threading.Thread(target=self.fetch_inventory_prices, daemon=True)
        thread.start()
    
    def fetch_inventory_prices(self):
        """Fetch current prices for all metals"""
        try:
            prices_fetched = 0
            total_metals = len(METALS)
            
            for metal_name, metal_config in METALS.items():
                self.root.after(0, lambda m=metal_name: self.inv_status_label.config(text=f"Fetching {m}..."))
                
                # Try gold-api.com first
                price_oz = self.get_current_spot_price(metal_config['symbol'])
                
                # Fallback to Yahoo Finance with retry
                if price_oz is None:
                    price_oz = self.get_yf_current_price_with_retry(metal_config['yf_ticker'])
                
                if price_oz is not None:
                    # Store price per gram
                    self.inventory_prices[metal_name] = price_oz / TROY_OUNCE_TO_GRAMS
                    prices_fetched += 1
            
            # Update UI on main thread
            def update_ui():
                self.inv_fetch_btn.config(state='normal')
                if prices_fetched == total_metals:
                    self.inv_status_label.config(text=f"All {total_metals} metals updated ✓")
                elif prices_fetched > 0:
                    self.inv_status_label.config(text=f"{prices_fetched}/{total_metals} metals updated")
                else:
                    self.inv_status_label.config(text="Failed to fetch prices")
                self.refresh_inventory_display()
            
            self.root.after(0, update_ui)
            
        except Exception as e:
            def show_error():
                self.inv_fetch_btn.config(state='normal')
                self.inv_status_label.config(text="Error")
                messagebox.showerror("Fetch Error", f"Error fetching prices:\n{e}")
            self.root.after(0, show_error)
    
    def get_sorted_inventory(self):
        """Return sorted and filtered inventory"""
        # Filter
        filter_metal = self.filter_var.get()
        if filter_metal == 'All Metals':
            filtered = self.inventory
        else:
            filtered = [i for i in self.inventory if i.get('metal') == filter_metal]
        
        # Calculate values for sorting
        items_with_calc = []
        for item in filtered:
            profit_pct = 0
            goal_pct = 0
            current_value = 0
            
            metal = item.get('metal', 'Silver')
            # Use inventory_prices which has all metals
            if metal in self.inventory_prices:
                current_value = item['metal_content'] * self.inventory_prices[metal]
                profit = current_value - item['purchase_price']
                profit_pct = (profit / item['purchase_price']) * 100 if item['purchase_price'] > 0 else (100 if current_value > 0 else 0)
                goal = item.get('profit_goal', 100)
                goal_pct = (profit_pct / goal) * 100 if goal > 0 else 0
            
            items_with_calc.append({
                'item': item,
                'profit_pct': profit_pct,
                'goal_pct': goal_pct,
                'current_value': current_value
            })
        
        # Sort
        sort_key = self.sort_var.get()
        if sort_key == "date_desc":
            items_with_calc.sort(key=lambda x: x['item'].get('purchase_date', ''), reverse=True)
        elif sort_key == "date_asc":
            items_with_calc.sort(key=lambda x: x['item'].get('purchase_date', ''))
        elif sort_key == "profit_pct_desc":
            items_with_calc.sort(key=lambda x: x['profit_pct'], reverse=True)
        elif sort_key == "profit_pct_asc":
            items_with_calc.sort(key=lambda x: x['profit_pct'])
        elif sort_key == "goal_pct_desc":
            items_with_calc.sort(key=lambda x: x['goal_pct'], reverse=True)
        elif sort_key == "goal_pct_asc":
            items_with_calc.sort(key=lambda x: x['goal_pct'])
        elif sort_key == "value_desc":
            items_with_calc.sort(key=lambda x: x['current_value'], reverse=True)
        elif sort_key == "value_asc":
            items_with_calc.sort(key=lambda x: x['current_value'])
        elif sort_key == "metal_asc":
            items_with_calc.sort(key=lambda x: x['item'].get('metal', ''))
        elif sort_key == "metal_desc":
            items_with_calc.sort(key=lambda x: x['item'].get('metal', ''), reverse=True)
        elif sort_key == "id_asc":
            items_with_calc.sort(key=lambda x: x['item']['id'].lower())
        elif sort_key == "id_desc":
            items_with_calc.sort(key=lambda x: x['item']['id'].lower(), reverse=True)
        
        return [x['item'] for x in items_with_calc]
    
    def refresh_inventory_display(self):
        """Refresh the inventory display"""
        for widget in self.inv_scrollable_frame.winfo_children():
            widget.destroy()
        
        if not self.inventory:
            ttk.Label(self.inv_scrollable_frame, text="No items in inventory. Add items above.", 
                     foreground="gray").pack(pady=20)
            self.inv_summary_var.set("")
            return
        
        sorted_inventory = self.get_sorted_inventory()
        
        if not sorted_inventory:
            ttk.Label(self.inv_scrollable_frame, text="No items match the current filter.", 
                     foreground="gray").pack(pady=20)
            self.inv_summary_var.set("")
            return
        
        total_invested = 0
        total_current_value = 0
        
        for i, item in enumerate(sorted_inventory):
            self.create_inventory_item_widget(item, i)
            total_invested += item['purchase_price']
            
            metal = item.get('metal', 'Silver')
            # Use inventory_prices which has all metals
            if metal in self.inventory_prices:
                total_current_value += item['metal_content'] * self.inventory_prices[metal]
        
        # Update summary
        if self.inventory_prices and total_current_value > 0:
            total_profit = total_current_value - total_invested
            total_profit_pct = (total_profit / total_invested * 100) if total_invested > 0 else 0
            self.inv_summary_var.set(
                f"Showing: {len(sorted_inventory)} items | "
                f"Invested: ${total_invested:.2f} | "
                f"Value: ${total_current_value:.2f} | "
                f"Profit: ${total_profit:+.2f} ({total_profit_pct:+.1f}%)"
            )
        else:
            self.inv_summary_var.set(f"Showing: {len(sorted_inventory)} items | Invested: ${total_invested:.2f} | Click 'Fetch All Metal Prices' for values")
    
    def create_inventory_item_widget(self, item, index):
        """Create widget for inventory item"""
        item_frame = ttk.Frame(self.inv_scrollable_frame, relief='solid', borderwidth=1)
        item_frame.pack(fill='x', pady=2, padx=2)
        
        def select_item(event=None):
            self.selected_item_id = item['id']
            self.refresh_inventory_display()
        
        item_frame.bind('<Button-1>', select_item)
        
        if self.selected_item_id == item['id']:
            item_frame.configure(relief='sunken')
        
        # Top row
        top_row = ttk.Frame(item_frame)
        top_row.pack(fill='x', padx=5, pady=(5, 2))
        top_row.bind('<Button-1>', select_item)
        
        metal = item.get('metal', 'Silver')
        metal_color = METALS.get(metal, {}).get('color', '#000000')
        
        id_label = ttk.Label(top_row, text=f"[{metal}] {item['id']}", font=('Segoe UI', 10, 'bold'))
        id_label.pack(side='left')
        id_label.bind('<Button-1>', select_item)
        
        if item.get('description'):
            desc_label = ttk.Label(top_row, text=f" - {item['description']}", foreground="gray")
            desc_label.pack(side='left')
            desc_label.bind('<Button-1>', select_item)
        
        date_label = ttk.Label(top_row, text=f"Purchased: {item.get('purchase_date', 'N/A')}", foreground="gray", font=('Segoe UI', 8))
        date_label.pack(side='right')
        date_label.bind('<Button-1>', select_item)
        
        # Middle row
        mid_row = ttk.Frame(item_frame)
        mid_row.pack(fill='x', padx=5, pady=2)
        mid_row.bind('<Button-1>', select_item)
        
        weight_label = ttk.Label(mid_row, text=f"Weight: {item['weight']:.2f} {item.get('weight_unit', 'g')} @ {item['purity']}% = {item['metal_content']:.2f}g pure")
        weight_label.pack(side='left')
        weight_label.bind('<Button-1>', select_item)
        
        if item['purchase_price'] > 0:
            price_text = f"Paid: ${item['purchase_price']:.2f} (${item['cost_per_gram']:.4f}/g)"
        else:
            price_text = "Paid: $0.00 (FREE/Gift)"
        price_label = ttk.Label(mid_row, text=price_text)
        price_label.pack(side='left', padx=(20, 0))
        price_label.bind('<Button-1>', select_item)
        
        # Bottom row
        bottom_row = ttk.Frame(item_frame)
        bottom_row.pack(fill='x', padx=5, pady=(2, 5))
        bottom_row.bind('<Button-1>', select_item)
        
        # Use inventory_prices which has all metals
        if metal in self.inventory_prices:
            current_value = item['metal_content'] * self.inventory_prices[metal]
            profit = current_value - item['purchase_price']
            # Handle $0 purchase price (gift/found items)
            if item['purchase_price'] > 0:
                profit_pct = (profit / item['purchase_price']) * 100
            else:
                profit_pct = 100 if current_value > 0 else 0  # 100% profit on free items
            
            value_label = ttk.Label(bottom_row, text=f"Value: ${current_value:.2f}")
            value_label.pack(side='left')
            value_label.bind('<Button-1>', select_item)
            
            profit_color = "green" if profit >= 0 else "red"
            if item['purchase_price'] == 0:
                profit_text = f"Profit: ${profit:+.2f} (FREE ITEM)"
            else:
                profit_text = f"Profit: ${profit:+.2f} ({profit_pct:+.1f}%)"
            profit_label = ttk.Label(bottom_row, text=profit_text, 
                                    foreground=profit_color, font=('Segoe UI', 9, 'bold'))
            profit_label.pack(side='left', padx=(15, 0))
            profit_label.bind('<Button-1>', select_item)
            
            # Progress bar
            progress_frame = ttk.Frame(bottom_row)
            progress_frame.pack(side='right', padx=(10, 0))
            progress_frame.bind('<Button-1>', select_item)
            
            goal_pct = item.get('profit_goal', 100)
            progress_value = min(100, max(0, (profit_pct / goal_pct) * 100)) if goal_pct > 0 else 0
            
            if progress_value >= 100:
                bar_style = "green.Horizontal.TProgressbar"
                goal_text = "🎯 GOAL REACHED!"
            elif progress_value >= 75:
                bar_style = "yellow.Horizontal.TProgressbar"
                goal_text = f"{progress_value:.0f}% to {goal_pct}% goal"
            elif progress_value >= 50:
                bar_style = "orange.Horizontal.TProgressbar"
                goal_text = f"{progress_value:.0f}% to {goal_pct}% goal"
            else:
                bar_style = "red.Horizontal.TProgressbar"
                goal_text = f"{progress_value:.0f}% to {goal_pct}% goal"
            
            goal_label = ttk.Label(progress_frame, text=goal_text, font=('Segoe UI', 8))
            goal_label.pack(side='top')
            goal_label.bind('<Button-1>', select_item)
            
            progress_bar = ttk.Progressbar(progress_frame, length=120, mode='determinate', 
                                          value=progress_value, style=bar_style)
            progress_bar.pack(side='top')
        else:
            note = f"Click 'Fetch All Metal Prices' to see {metal} value"
            no_price_label = ttk.Label(bottom_row, text=note, foreground="gray", font=('Segoe UI', 8, 'italic'))
            no_price_label.pack(side='left')
            no_price_label.bind('<Button-1>', select_item)
    
    def export_inventory_csv(self):
        """Export inventory to CSV"""
        if not self.inventory:
            messagebox.showwarning("No Data", "No inventory items to export.")
            return
        
        if sys.platform == 'win32':
            initial_dir = os.path.join(os.path.expanduser('~'), 'Documents')
        else:
            initial_dir = os.path.expanduser('~')
        
        filename = None
        
        try:
            temp_window = tk.Toplevel(self.root)
            temp_window.withdraw()
            temp_window.attributes('-topmost', True)
            temp_window.update()
            
            filename = filedialog.asksaveasfilename(
                parent=temp_window,
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
                initialfilename=f"metal_inventory_{datetime.now().strftime('%Y%m%d')}.csv",
                initialdir=initial_dir,
                title="Export Inventory to CSV"
            )
            
            temp_window.destroy()
        except Exception as e:
            print(f"Filedialog error: {e}")
            filename = None
        
        if not filename:
            if messagebox.askyesno("Export to Documents?", 
                                   "Would you like to save the CSV to your Documents folder?"):
                filename = os.path.join(initial_dir, f"metal_inventory_{datetime.now().strftime('%Y%m%d')}.csv")
                counter = 1
                base_filename = filename
                while os.path.exists(filename):
                    name, ext = os.path.splitext(base_filename)
                    filename = f"{name}_{counter}{ext}"
                    counter += 1
            else:
                return
        
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = [
                    'Item ID', 'Metal', 'Description', 'Weight', 'Weight Unit',
                    'Purity (%)', 'Pure Metal (g)', 'Purchase Price ($)',
                    'Cost Per Gram ($)', 'Purchase Date', 'Profit Goal (%)',
                    'Current Value ($)', 'Profit ($)', 'Profit (%)', 'Goal Progress (%)'
                ]
                
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for item in self.inventory:
                    current_value = ''
                    profit = ''
                    profit_pct = ''
                    goal_progress = ''
                    
                    metal = item.get('metal', 'Silver')
                    # Use inventory_prices which has all metals
                    if metal in self.inventory_prices:
                        current_value = item['metal_content'] * self.inventory_prices[metal]
                        profit = current_value - item['purchase_price']
                        if item['purchase_price'] > 0:
                            profit_pct = (profit / item['purchase_price']) * 100
                        else:
                            profit_pct = 100 if current_value > 0 else 0  # Free items
                        goal = item.get('profit_goal', 100)
                        goal_progress = (profit_pct / goal) * 100 if goal > 0 else 0
                    
                    writer.writerow({
                        'Item ID': item['id'],
                        'Metal': metal,
                        'Description': item.get('description', ''),
                        'Weight': f"{item['weight']:.4f}",
                        'Weight Unit': item.get('weight_unit', 'grams'),
                        'Purity (%)': item['purity'],
                        'Pure Metal (g)': f"{item['metal_content']:.4f}",
                        'Purchase Price ($)': f"{item['purchase_price']:.2f}",
                        'Cost Per Gram ($)': f"{item['cost_per_gram']:.4f}",
                        'Purchase Date': item.get('purchase_date', ''),
                        'Profit Goal (%)': item.get('profit_goal', 100),
                        'Current Value ($)': f"{current_value:.2f}" if current_value != '' else 'N/A',
                        'Profit ($)': f"{profit:.2f}" if profit != '' else 'N/A',
                        'Profit (%)': f"{profit_pct:.2f}" if profit_pct != '' else 'N/A',
                        'Goal Progress (%)': f"{goal_progress:.2f}" if goal_progress != '' else 'N/A'
                    })
            
            if messagebox.askyesno("Export Successful", f"Inventory exported to:\n{filename}\n\nOpen containing folder?"):
                folder = os.path.dirname(filename)
                if sys.platform == 'win32':
                    os.startfile(folder)
                elif sys.platform == 'darwin':
                    os.system(f'open "{folder}"')
                else:
                    os.system(f'xdg-open "{folder}"')
            
        except Exception as e:
            messagebox.showerror("Export Error", f"Could not export inventory:\n{e}")
    
    # =========================================================================
    # SETTINGS
    # =========================================================================
    
    def save_all_settings(self):
        """Save all settings"""
        self.settings['default_metal'] = self.default_metal_var.get()
        self.settings['default_unit'] = self.default_unit_var.get()
        self.settings['sales_tax_state'] = self.tax_state_var.get()
        
        try:
            self.settings['custom_tax_rate'] = float(self.custom_tax_var.get())
        except:
            self.settings['custom_tax_rate'] = 0.0
        
        self.save_settings()
        self.update_tax_display()
        self.refresh_calculated_prices_display()
        messagebox.showinfo("Settings Saved", "Your settings have been saved.")
    
    def open_data_folder(self):
        """Open the data folder in file explorer"""
        folder = self.get_app_data_path()
        if sys.platform == 'win32':
            os.startfile(folder)
        elif sys.platform == 'darwin':
            os.system(f'open "{folder}"')
        else:
            os.system(f'xdg-open "{folder}"')
    
    def reset_formulas(self):
        """Reset formulas to default"""
        if messagebox.askyesno("Confirm Reset", "Reset all formulas to default? This cannot be undone."):
            self.custom_formulas = []
            self.load_formulas()  # Will create defaults
            self.refresh_formula_list()
            self.refresh_calculated_prices_display()
            messagebox.showinfo("Reset Complete", "Formulas have been reset to defaults.")


def main():
    root = tk.Tk()
    
    root.update_idletasks()
    width = 900
    height = 900
    x = (root.winfo_screenwidth() // 2) - (width // 2)
    y = (root.winfo_screenheight() // 2) - (height // 2)
    root.geometry(f'{width}x{height}+{x}+{y}')
    
    app = MetalCalculatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
