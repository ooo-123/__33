
# import numpy as np
# import pandas as pd

try:
    import blpapi
    bloomberg_available = True
except ImportError:
    bloomberg_available = False

def check_bloomberg_availability():
    """Re-check if Bloomberg Terminal is available"""
    global bloomberg_available
    try:
        import blpapi
        # Try to create a session to verify Bloomberg is actually available
        sessionOptions = blpapi.SessionOptions()
        sessionOptions.setServerHost("localhost")
        sessionOptions.setServerPort(8194)
        session = blpapi.Session(sessionOptions)
        if session.start():
            session.stop()
            bloomberg_available = True
        else:
            bloomberg_available = False
    except:
        bloomberg_available = False
    return bloomberg_available

import numpy as np
import time 
import random

def xccy_bid_offer(leg1_bid, leg1_ask, leg2_bid, leg2_ask, how: str) -> tuple[float, float]:
    """
    Calculate cross currency bid/offer using the deterministic recipe.
    
    Args:
        leg1_bid, leg1_ask: Two-way prices for the first leg
        leg2_bid, leg2_ask: Two-way prices for the second leg
        how: Calculation method - "mult", "div_leg2", "div_leg1", "flip_first_mult"
    
    Returns:
        tuple: (cross_bid, cross_offer)
    """
    if how == "mult":
        return leg1_bid * leg2_bid, leg1_ask * leg2_ask
    elif how == "div_leg2":
        return leg1_bid / leg2_ask, leg1_ask / leg2_bid
    elif how == "div_leg1":
        return leg2_bid / leg1_ask, leg2_ask / leg1_bid
    elif how == "flip_first_mult":
        return (1/leg1_ask) * leg2_bid, (1/leg1_bid) * leg2_ask
    else:
        raise ValueError(f"Unknown calculation mode: {how}")
import pandas as pd
# import talib
# eikon_app_key = "2f478f257ba4721a9c49ad37fe47a8ab0d60278"


# class signals:

#     def __init__(self):
#         self.ccy = "AUD"

#     # def rsi(self, data):

#     #     # Extract the bid price from the data
#     #     return talib.RSI(data, timeperiod=14)[-1]
        

class pricing:
    

    def __init__(self):

        self.major_ccys = ["AUDUSD","EURUSD","GBPUSD","USDJPY","NZDUSD","USDCAD","USDCHF","USDSGD","USDNOK"]

        self.majors = {"AUD":"AUDUSD","EUR":"EURUSD",
                       "GBP":"GBPUSD","JPY":"USDJPY",
                       "NZD":"NZDUSD","CAD":"USDCAD",
                       "CHF":"USDCHF","SGD":"USDSGD",
                       "NOK":"USDNOK","SEK":"EURSEK",
                       "CNH":"USDCNH","HKD":"USDHKD",
                       "PLN":"USDPLN", "DKK":"EURDKK"}

        self.executable_sizes = ["2-5M", "5-10", "10-20", "20-30"]
        self.ccy = "AUDUSD"
        self.decimal_places = 1000
        self.synthetic_cross_mode = False
        self.ccy_1_leg, self.ccy_2_leg = None, None
        self.cross_ccy = None
        
        # Price direction tracking
        self.previous_bid = 0.0
        self.previous_offer = 0.0
        self.bid_direction = 'same'  # 'up', 'down', 'same'
        self.offer_direction = 'same'
        
        # Inverse price tracking
        self.inverse_bid = 0.0
        self.inverse_offer = 0.0
        self.inverse_mid = 0.0
        self.previous_inverse_bid = 0.0
        self.previous_inverse_offer = 0.0
        self.inverse_bid_direction = 'same'
        self.inverse_offer_direction = 'same'
        self.inverse_ccy = ""  # Will hold the inverted currency pair name
        self.pips_str_inverse_bid = ""
        self.pips_str_inverse_offer = ""
        self.pips_str_inverse_mid = ""
        
        # Configuration for decimal places
        self.config = {
            'manual_dp_override': {},  # {currency_pair: decimal_places}
            'use_standard_dp': True
        }
        
        # Market data timestamp tracking
        self.market_data_timestamp = None  # Timestamp from market data feed
        self.last_market_update_time = 0  # Local time when last market data received
        
        # Load Spreads DF
        self.load_spreads_df()
        
        # 0 Bid, 1 Offer, 2 High, 3 Low
        self.bid_offer = {k:np.array([0.0,0.0,0.0, 0.0]) for k in self.ccys}
    
        self.reverse_size_input = 0
        self.reverse_size_output = 0.0

        self.pips_places = 2
        self.skew_round_value = 0.00005
        self.round_dp = 6
        self.manual_spread = 0.0
        self.manual_spread_interval = 0.5  # Half-pip increments for precision
        self.skew = 0.0  # Initialize skew to prevent AttributeError

        # X = time, Y1 = Bid, Y2 = offer
        # Using collections.deque for better performance with fixed-size data
        from collections import deque
        # Replace numpy array with deque for better performance
        self.bid_offer_signals_rolling = deque(maxlen=100)
        self.bid_offer_signals_rolling.append([time.time(), 0.0, 0.0])

        # numpy array 2 - 5M, 5 - 10, 10 -20, 20-30, 30+
        self.bid_offer_by_size = np.zeros((5,2))

        # self.signals = signals()

        self.get_ccy_spreads_conventions()

    def load_spreads_df(self):
        try:
            # Spreads
            # 1 Default
            self.spread_matrix = pd.read_csv("data/spreads/spreads.csv", index_col="CCY")
            self.spread_matrix.columns = [int(i) for i in self.spread_matrix.columns]
            self.ccys = [ccy for ccy in self.spread_matrix.index]

            self.spread_matrix_choices = ['Default','Super','Korea','PBOC China']


            # 1 AUD Super
            self.spread_matrix_super = pd.read_csv("data/spreads/spreads_super.csv", index_col="CCY")
            self.spread_matrix_super.columns = [int(i) for i in self.spread_matrix_super.columns]
            # 2 Korea
            self.spread_matrix_korea = pd.read_csv("data/spreads/spreads_korea.csv", index_col="CCY")
            self.spread_matrix_korea.columns = [int(i) for i in self.spread_matrix_korea.columns]
            #3 PBOC
            self.spread_matrix_pboc_china = pd.read_csv("data/spreads/spreads_pboc_china.csv", index_col="CCY")
            self.spread_matrix_pboc_china.columns = [int(i) for i in self.spread_matrix_pboc_china.columns]

            self.choose_spread_matrix() # Will chose the default spread matrix
        except Exception as e:
            print(e)
            self.choose_spread_matrix()  # Will chose the default spread matrix

    def get_ccy_crosses_base_conventions(self):
        None
    
    def get_cross_decimal_convention(self, cross_ccy):
        """
        Determine decimal places for cross rates according to market conventions.
        
        Based on industry standard (Bloomberg, ECN, broker conventions):
        1. If quote currency is JPY -> 3 decimal places, pip = 0.01
        2. If quote currency is not JPY -> 5 decimal places, pip = 0.0001
        3. Special case: JPY as base currency -> 5 decimal places
        
        Reference: https://www.myfxbook.com/forex-calculators/pip-calculator
        """
        base_ccy = cross_ccy[:3]
        quote_ccy = cross_ccy[3:6]
        
        if quote_ccy == 'JPY':
            # Pair ends with JPY -> 3 decimal places (industry standard)
            # pip = 0.01, pips_places = 0 (pip starts at 2nd decimal)
            return {
                "decimal_places": 100,  # for 0.01 pip size
                "pips_places": 0,  # pip at 2nd decimal, no skip
                "skew_round_value": 0.005,  # half pip = 0.005
                "round_dp": 3
            }
        elif base_ccy == 'JPY':
            # JPY is base currency (e.g., JPYUSD) -> 5 decimal places
            return {
                "decimal_places": 10000,  # for 0.0001 pip size
                "pips_places": 2,  # pip at 4th decimal, skip 2
                "skew_round_value": 0.00005,  # half pip = 0.00005
                "round_dp": 5
            }
        else:
            # Standard cross (non-JPY) -> 5 decimal places
            return {
                "decimal_places": 10000,  # for 0.0001 pip size
                "pips_places": 2,  # pip at 4th decimal, skip 2
                "skew_round_value": 0.00005,  # half pip = 0.00005
                "round_dp": 5
            }

    def get_ccy_spreads_conventions(self):


        self.ccy_spd_conventions = {

        "AUDUSD":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},#
        "EURUSD":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},#
        "GBPUSD":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},#
        "NZDUSD":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},#
        "USDCAD":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},#
        "USDJPY":{"decimal_places": 100,"pips_places":0,"skew_round_value":0.005,"round_dp":3},#
        "EURJPY":{"decimal_places": 100,"pips_places":0,"skew_round_value":0.005,"round_dp":3},#
        "AUDJPY":{"decimal_places": 100,"pips_places":0,"skew_round_value":0.005,"round_dp":3},#
        "EURGBP":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},#
        "EURCHF":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},#
        "USDCHF":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},#
        "AUDNZD":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},#
        "GBPAUD":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},#
        "USDNOK":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},#
        "USDSGD":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},#
        "USDCNH":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},#
        "EURCAD":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},#
        "EURNZD":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},#
        "EURSEK":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},#
        "USDPLN":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},#
        "EURAUD":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},#
        "EURNOK":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},
        "EURDKK":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},
        "USDHKD":{"decimal_places": 10000,"pips_places":2,"skew_round_value":0.00005,"round_dp":5},
    
        }

    def get_spread_pip_multiplier(self, ccy_pair):
        """Get the correct multiplier for spread calculation in pips"""
        if ccy_pair.endswith('JPY'):
            return 100  # For JPY pairs, pip is at 2nd decimal
        else:
            return 10000  # For other pairs, pip is at 4th decimal

    def get_crosses_spreads(self, cross_ccy, order_size):
        """Set up cross currency calculation with proper leg identification"""
        
        self.cross_ccy = cross_ccy
        self.ccy_1, self.ccy_2 = self.cross_ccy[:3], self.cross_ccy[3:]
        
        # Map currencies to their major pairs
        if self.ccy_1 in self.majors.keys():
            self.ccy_1_leg = self.majors[self.ccy_1]
        else:
            # Handle case where currency is not in majors - construct USD pair
            self.ccy_1_leg = f"USD{self.ccy_1}" if self.ccy_1 != 'USD' else None
            
        if self.ccy_2 in self.majors.keys():
            self.ccy_2_leg = self.majors[self.ccy_2]
        else:
            # Handle case where currency is not in majors - construct USD pair
            self.ccy_2_leg = f"USD{self.ccy_2}" if self.ccy_2 != 'USD' else None
        
        # Validate that we have valid legs
        if self.ccy_1_leg is None or self.ccy_2_leg is None:
            # Don't raise, just deactivate synthetic mode and return
            self.synthetic_cross_mode = False
            print(f"Cannot construct cross for {cross_ccy} - missing major pair mappings")
            return
        
        # Check if the leg pairs exist in our bid_offer data
        if self.ccy_1_leg not in self.bid_offer or self.ccy_2_leg not in self.bid_offer:
            missing = []
            if self.ccy_1_leg not in self.bid_offer:
                missing.append(self.ccy_1_leg)
            if self.ccy_2_leg not in self.bid_offer:
                missing.append(self.ccy_2_leg)
            # Don't raise, just deactivate synthetic mode and return
            self.synthetic_cross_mode = False
            print(f"Cannot create cross {cross_ccy}: Missing market data for legs: {missing}")
            return

        
        # Calculate mid rates to determine order sizes
        self.price_mid_cross()
        
        # Calculate appropriate order sizes for each leg
        self.order_size_ccy_leg_1 = order_size
        
        # Determine leg 2 order size based on cross calculation type
        if self.cross_calculation_type in ['multiply', 'invert_first_multiply']:
            # When multiplying rates, leg 2 size is converted through the common currency
            if 'USD' in self.ccy_1_leg and 'USD' in self.ccy_2_leg:
                # Both legs involve USD
                if self.ccy_1_leg.endswith('USD'):  # e.g., EURUSD
                    # Convert to USD amount, then use for second leg
                    usd_amount = self.order_size_ccy_leg_1 * self.mid_1
                    self.order_size_ccy_leg_2 = usd_amount
                else:  # e.g., USDCAD
                    # Already in USD terms
                    self.order_size_ccy_leg_2 = self.order_size_ccy_leg_1
            else:
                # Use mid rate to convert
                self.order_size_ccy_leg_2 = round(self.order_size_ccy_leg_1 * self.mid_2, 2)
        else:
            # For division operations, typically use same notional
            self.order_size_ccy_leg_2 = self.order_size_ccy_leg_1
        

        
        # Get spreads for both legs
        self.get_spread_cross_1(self.order_size_ccy_leg_1)
        self.get_spread_cross_2(self.order_size_ccy_leg_2)
        
        # Calculate prices for both legs
        self.price_crosses_cross_1()
        self.price_crosses_cross_2()
        
        self.synthetic_cross_mode = True
    
    def deactivate_synthetic_mode(self):
        self.synthetic_cross_mode = False
        try:
            del self.bid_offer[self.cross_ccy]
        except Exception as e:
            print(e)
        self.cross_ccy = None
        self.ccy_1_leg, self.ccy_2_leg = None, None
        self.synthetic_cross_mode = False
        

    def detect_usd_quote_ccy(self,ccy):
        return ccy[-3:] == 'USD'

    def create_dict_bid_offer_by_size(self):
        self.bid_offer_by_size = {k: [0.0, 0.0] for k in self.executable_sizes}
        # print(self.create_dict_bid_offer_by_size)
    
    def create_bid_offer(self):

        self.bid_offer_signals_rolling = np.zeros((1,3))

    def update_np_array(self):
        # Use deque's efficient append operation instead of numpy insert
        # This is much faster for maintaining a fixed-size rolling window
        self.bid_offer_signals_rolling.appendleft([
            time.time(),
            self.bid_offer[self.ccy][0],
            self.bid_offer[self.ccy][1]
        ])
        # No need to manually limit size as deque handles this automatically

    def widen(self):
        
        self.manual_spread += self.manual_spread_interval
        self.manual_spread = self.manual_spread
        if abs(self.manual_spread) < 0.000001:
            self.manual_spread = 0.0
        # Manual spread adjusted

    def tighten(self):
        
        self.manual_spread -= self.manual_spread_interval
        self.manual_spread = self.manual_spread
        if abs(self.manual_spread) < 0.000001:
            self.manual_spread = 0.0
        # Manual spread adjusted
    
    def price_mid_cross(self):
        """Calculate mid cross rate using proper algebraic formulas"""
        
        self.mid_1 = (self.bid_offer[self.ccy_1_leg][0] + self.bid_offer[self.ccy_1_leg][1])/2
        self.mid_2 = (self.bid_offer[self.ccy_2_leg][0] + self.bid_offer[self.ccy_2_leg][1])/2
        
        # Determine cross rate based on currency orientations
        # Format: desired cross is ccy_1/ccy_2 (e.g., EUR/CNH)
        
        # Check what we have available and apply correct formula
        leg1_base = self.ccy_1_leg[:3]  # e.g., 'EUR' from 'EURUSD'
        leg1_quote = self.ccy_1_leg[3:]  # e.g., 'USD' from 'EURUSD'
        leg2_base = self.ccy_2_leg[:3]   # e.g., 'USD' from 'USDCNH' 
        leg2_quote = self.ccy_2_leg[3:]  # e.g., 'CNH' from 'USDCNH'
        
        # Apply the algebraic cancellation rule
        # Write rates so the common currency appears once on top and once on bottom
        
        # Debug print (commented out for production)
        # print(f"Debug: {self.cross_ccy} -> Leg1: {self.ccy_1_leg} ({leg1_base}/{leg1_quote}), Leg2: {self.ccy_2_leg} ({leg2_base}/{leg2_quote})")
        
        # Check for special cases first - JPY/CNH, JPY/HKD, HKD/JPY, NOK/HKD
        if self.ccy_1 == 'JPY' and self.ccy_2 in ['CNH', 'HKD']:
            # JPY/CNH = USD/CNH ÷ USD/JPY
            # JPY/HKD = USD/HKD ÷ USD/JPY
            self.mid_cross = self.mid_2 / self.mid_1  # leg2 / leg1
            self.cross_calculation_type = 'divide_same_base'
        elif self.ccy_1 == 'HKD' and self.ccy_2 == 'JPY':
            # HKD/JPY = USD/JPY ÷ USD/HKD
            self.mid_cross = self.mid_2 / self.mid_1  # leg2 / leg1
            self.cross_calculation_type = 'divide_same_base'
        elif self.ccy_1 == 'NOK' and self.ccy_2 == 'HKD':
            # NOK/HKD = USD/HKD ÷ USD/NOK
            # Need to check which leg is which
            if self.ccy_1_leg == 'USDNOK' and self.ccy_2_leg == 'USDHKD':
                self.mid_cross = self.mid_2 / self.mid_1
                self.cross_calculation_type = 'divide_same_base'
            else:
                # Handle other configurations
                self.mid_cross = self.mid_1 / self.mid_2
                self.cross_calculation_type = 'divide_leg2'
        elif leg1_quote == leg2_base:  # Common currency in opposite positions
            # Standard multiplication for most pairs
            self.mid_cross = self.mid_1 * self.mid_2
            self.cross_calculation_type = 'multiply'
            
        elif leg1_quote == leg2_quote:  # Common currency in same position (denominator)
            # A/B ÷ C/B = A/C (divide)
            # Example: EUR/USD ÷ GBP/USD = EUR/GBP
            self.mid_cross = self.mid_1 / self.mid_2
            self.cross_calculation_type = 'divide_same_quote'
            
        elif leg1_base == leg2_base:  # Common currency in same position (numerator)
            # B/A ÷ B/C = C/A, so A/C = C/A inverted = (B/C) ÷ (B/A)
            # Example: For CAD/JPY from USD/CAD and USD/JPY: (USD/JPY) ÷ (USD/CAD)
            self.mid_cross = self.mid_2 / self.mid_1
            self.cross_calculation_type = 'divide_same_base'
            
        elif leg1_base == leg2_quote:  # Need to flip one rate
            # B/A × C/B = C/A, so A/C = (C/A)^-1 = 1 / ((C/B) × (B/A))
            # But this is equivalent to: A/C = (A/B) × (B/C) where A/B = 1/(B/A)
            self.mid_cross = (1/self.mid_1) * self.mid_2
            self.cross_calculation_type = 'invert_first_multiply'
            
        else:
            # Handle special cases where currencies don't follow standard patterns
            # Check for cases like GBPCAD: GBPUSD and USDCAD
            if (leg1_base == self.ccy_1 and leg1_quote == 'USD' and 
                leg2_base == 'USD' and leg2_quote == self.ccy_2):
                # This is the pattern: ccy1/USD and USD/ccy2 where we want ccy1/ccy2
                # Default to division for this pattern
                self.mid_cross = self.mid_1 / self.mid_2
                self.cross_calculation_type = 'special_usd_divide'
            else:
                # True fallback
                print(f"Warning: Unexpected currency configuration for {self.cross_ccy}")
                print(f"Leg1: {self.ccy_1_leg} ({leg1_base}/{leg1_quote}), Leg2: {self.ccy_2_leg} ({leg2_base}/{leg2_quote})")
                self.mid_cross = self.mid_1 * self.mid_2  # Default to multiply
                self.cross_calculation_type = 'fallback_multiply'



    def price_crosses_cross_1(self):

        self.mid_1 =  (self.bid_offer[self.ccy_1_leg][0] + self.bid_offer[self.ccy_1_leg][1])/2
        self.mid_1 = round(round(self.mid_1/self.skew_round_value_cross_1) * self.skew_round_value_cross_1,self.round_dp_cross_1)
        
               
        self.bid_1 = round(self.mid_1 + self.bid_spread_cross_1 + self.skew_cross_1, self.round_dp_cross_1)
        self.offer_1 = round(self.mid_1 + self.offer_spread_cross_1 + self.skew_cross_1, self.round_dp_cross_1)
    
    def price_crosses_cross_2(self):

        self.mid_2 =  (self.bid_offer[self.ccy_2_leg][0] + self.bid_offer[self.ccy_2_leg][1])/2
        self.mid_2 = round(round(self.mid_2/self.skew_round_value_cross_2) * self.skew_round_value_cross_2,self.round_dp_cross_2)
        
                
        self.bid_2 = round(self.mid_2 + self.bid_spread_cross_2 + self.skew_cross_2, self.round_dp_cross_2)
        self.offer_2 = round(self.mid_2 + self.offer_spread_cross_2 + self.skew_cross_2, self.round_dp_cross_2)

    def init_new_synthetic_in_bid_offer_array_dict(self):
        self.bid_offer[self.cross_ccy] = np.array([0.0,0.0,0.0, 0.0])
    
    def price_synthetic_cross(self):
        """Calculate synthetic cross rates with proper bid/ask spreads"""
        # Initialize skew attributes if not present
        if not hasattr(self, 'skew'):
            self.skew = 0
        if not hasattr(self, 'skew_cross_1'):
            self.skew_cross_1 = 0
        if not hasattr(self, 'skew_cross_2'):
            self.skew_cross_2 = 0
        
        # Ensure self.ccy matches the cross currency for inverse calculation
        self.ccy = self.cross_ccy

        self.price_crosses_cross_1()
        self.price_crosses_cross_2()
        
        # Map calculation types to the helper function modes
        mode_mapping = {
            'multiply': 'mult',
            'usd_common_multiply': 'mult',
            'divide_same_quote': 'div_leg2',
            'special_usd_divide': 'div_leg2',
            'divide_by_convention': 'div_leg2',
            'divide_same_base': 'div_leg1',
            'invert_first_multiply': 'flip_first_mult',
            'fallback_multiply': 'mult'
        }
        
        # Get the appropriate calculation mode
        mode = mode_mapping.get(self.cross_calculation_type, 'mult')
        
        # Use the deterministic recipe for cross rate spreads
        self.bid, self.offer = xccy_bid_offer(
            self.bid_1, self.offer_1,  # leg1 bid/ask
            self.bid_2, self.offer_2,  # leg2 bid/ask
            mode
        )

        # Get proper decimal convention for the cross (not just from leg 2)
        cross_convention = self.get_cross_decimal_convention(self.cross_ccy)
        cross_round_dp = cross_convention['round_dp']
        
        # CRITICAL: Update the display attributes so GUI shows correct precision
        self.round_dp = cross_convention['round_dp']
        self.decimal_places = cross_convention['decimal_places']
        self.pips_places = cross_convention['pips_places']
        self.skew_round_value = cross_convention['skew_round_value']
        
        # Apply proper rounding based on cross orientation
        self.bid = round(self.bid, cross_round_dp)
        self.offer = round(self.offer, cross_round_dp)
        self.mid =  (self.bid + self.offer)/2
        
        # Update decimal places for cross if different from leg 2
        self.decimal_places_cross = cross_convention['decimal_places']
        self.pips_places_cross = cross_convention['pips_places']

        self.bid_offer[self.cross_ccy][0] = self.bid 
        self.bid_offer[self.cross_ccy][1] = self.offer

        self.price_pips_bid_synthetic()
        self.price_pips_mid_synthetic()
        self.price_pips_offer_synthetic()

        # Spread - use correct pip multiplier for cross currency
        spread_multiplier = self.get_spread_pip_multiplier(self.cross_ccy)
        self.spread = round((self.offer - self.bid) * spread_multiplier, 1)
        
        # Calculate inverse prices for synthetic cross
        self.calculate_inverse_prices()

    def price(self):
        # Cache the current currency to avoid repeated lookups
        ccy = self.ccy
        bid_offer_data = self.bid_offer[ccy]
        
        # Calculate mid price first
        self.mid = round(round((bid_offer_data[0] + bid_offer_data[1])/2 / self.skew_round_value) * self.skew_round_value, self.round_dp)
        
        # Make sure bid_spread and offer_spread are initialized
        if not hasattr(self, 'bid_spread') or not hasattr(self, 'offer_spread'):
            self.get_spread(self.order_size if hasattr(self, 'order_size') else 10)
        
        # Calculate bid and offer with spread
        self.bid = round(self.mid + self.bid_spread + self.skew, self.round_dp)
        self.offer = round(self.mid + self.offer_spread + self.skew, self.round_dp)
        
        # Update price directions for arrow indicators
        self.update_price_directions(self.bid, self.offer)
        
        # Calculate pip strings based on whether it's synthetic or not
        if self.synthetic_cross_mode:
            self.price_pips_bid_synthetic()
            self.price_pips_mid_synthetic()
            self.price_pips_offer_synthetic()
        else:
            self.price_pips_bid()
            self.price_pips_mid()
            self.price_pips_offer()
        
        # Calculate high/low percentages for display
        try:
            # Prevent division by zero by checking if high/low values are non-zero
            high_val = bid_offer_data[2]
            low_val = bid_offer_data[3]
            
            # Only calculate percentages if values are non-zero
            if abs(high_val) > 0.000001:  # Use small epsilon instead of exact zero
                self.high_percent = (abs(self.mid-high_val)/high_val)*100
            else:
                self.high_percent = 0
                
            if abs(low_val) > 0.000001:  # Use small epsilon instead of exact zero
                self.low_percent = (abs(self.mid-low_val)/low_val)*100
            else:
                self.low_percent = 0
                
            self.high, self.low = high_val, low_val
            self.near_highs = (self.high_percent<self.low_percent)
            
        except Exception:
            # Initialize to defaults if error
            self.high_percent = 0
            self.low_percent = 0
            self.near_highs = False
        
        # Update data points for the graph - this is a potentially expensive operation
        # so we do it after the critical price calculations
        self.update_np_array()
        
        # Calculate inverse prices after main price calculation
        self.calculate_inverse_prices()
    
    def get_high_val(self):
        """Get formatted high value for current currency pair"""
        try:
            high = self.bid_offer[self.ccy][2]
            return f"{high:.{int(np.log10(self.decimal_places))}f}"
        except:
            return "N/A"
    
    def get_low_val(self):
        """Get formatted low value for current currency pair"""
        try:
            low = self.bid_offer[self.ccy][3]
            return f"{low:.{int(np.log10(self.decimal_places))}f}"
        except:
            return "N/A"
        try:
            # Prevent division by zero by checking if high/low values are non-zero
            high_val = self.bid_offer[self.ccy][2]
            low_val = self.bid_offer[self.ccy][3]
            
            # Only calculate percentages if values are non-zero
            if abs(high_val) > 0.000001:  # Use small epsilon instead of exact zero
                self.high_percent = (abs(self.mid-high_val)/high_val)*100
            else:
                self.high_percent = 0
                
            if abs(low_val) > 0.000001:  # Use small epsilon instead of exact zero
                self.low_percent = (abs(self.mid-low_val)/low_val)*100
            else:
                self.low_percent = 0
                
            self.high, self.low = high_val, low_val
            self.near_highs = (self.high_percent<self.low_percent)
            
        except Exception as e:
            # Error handling for high/low percentage calculation
            pass
    
    def reverse_order_size(self):

        if self.reverse_size_input > 0:
            self.reverse_size_output = round(self.reverse_size_input/self.mid,3)
        else:
            self.reverse_size_output = 0
    
    def calculate_inverse_prices(self):
        """Calculate inverse bid/offer prices and update direction tracking"""
        # Inverse pricing: bid becomes 1/offer, offer becomes 1/bid
        if self.bid > 0 and self.offer > 0:
            # Store previous values for direction tracking
            self.previous_inverse_bid = self.inverse_bid
            self.previous_inverse_offer = self.inverse_offer
            
            # Calculate inverse prices (market making logic)
            self.inverse_bid = 1 / self.offer  # You buy at their offer
            self.inverse_offer = 1 / self.bid  # You sell at their bid
            self.inverse_mid = (self.inverse_bid + self.inverse_offer) / 2
            
            # Update inverse currency pair name
            if len(self.ccy) == 6:
                self.inverse_ccy = self.ccy[3:] + self.ccy[:3]
            
            # Track direction changes (opposite of regular prices)
            if self.previous_inverse_bid > 0:
                if self.inverse_bid > self.previous_inverse_bid:
                    self.inverse_bid_direction = 'up'
                elif self.inverse_bid < self.previous_inverse_bid:
                    self.inverse_bid_direction = 'down'
                else:
                    self.inverse_bid_direction = 'same'
                    
            if self.previous_inverse_offer > 0:
                if self.inverse_offer > self.previous_inverse_offer:
                    self.inverse_offer_direction = 'up'
                elif self.inverse_offer < self.previous_inverse_offer:
                    self.inverse_offer_direction = 'down'
                else:
                    self.inverse_offer_direction = 'same'
            
            # Calculate pip strings for inverse prices
            self.calculate_inverse_pips()
    
    def calculate_inverse_pips(self):
        """Calculate pip display strings for inverse prices"""
        # Get decimal convention for inverse pair
        inverse_convention = self.get_inverse_decimal_convention()
        round_dp = inverse_convention['round_dp']
        pips_places = inverse_convention['pips_places']
        
        # Determine digits to extract based on inverse pair type
        # JPY as base currency needs 3 digits (e.g., JPYNZD: 119.00)
        # Non-JPY pairs need 2 digits (e.g., AUDGBP: 61.8)
        base_ccy = self.inverse_ccy[:3] if hasattr(self, 'inverse_ccy') else ""
        if base_ccy == 'JPY':
            digits_to_extract = 3
            decimal_places = 2
        else:
            digits_to_extract = 2
            decimal_places = 1
        
        # Format inverse bid pips
        try:
            bid_str = f"{self.inverse_bid:.{round_dp}f}"
            if '.' in bid_str and len(bid_str.split('.')[1]) > pips_places:
                pips_part = bid_str.split('.')[1][pips_places:]
                if len(pips_part) >= digits_to_extract:
                    # Extract digits and include decimal portion
                    if digits_to_extract == 2 and len(pips_part) > 2:
                        # For non-JPY pairs, include the third digit as decimal
                        pip_value = float(pips_part[:2] + "." + pips_part[2:3])
                    else:
                        # For JPY pairs, extract 3 digits as is
                        pip_value = float(pips_part[:digits_to_extract])
                    # Don't round to 0.5 for inverse pairs - show exact value
                    self.pips_str_inverse_bid = f"{pip_value:.{decimal_places}f}"
                else:
                    # Pad with zeros if needed
                    padded = pips_part.ljust(digits_to_extract, '0')
                    self.pips_str_inverse_bid = f"{float(padded):.{decimal_places}f}"
            else:
                self.pips_str_inverse_bid = "0.00"
        except:
            self.pips_str_inverse_bid = "0.00"
            
        # Format inverse offer pips
        try:
            offer_str = f"{self.inverse_offer:.{round_dp}f}"
            if '.' in offer_str and len(offer_str.split('.')[1]) > pips_places:
                pips_part = offer_str.split('.')[1][pips_places:]
                if len(pips_part) >= digits_to_extract:
                    # Extract digits and include decimal portion
                    if digits_to_extract == 2 and len(pips_part) > 2:
                        # For non-JPY pairs, include the third digit as decimal
                        pip_value = float(pips_part[:2] + "." + pips_part[2:3])
                    else:
                        # For JPY pairs, extract 3 digits as is
                        pip_value = float(pips_part[:digits_to_extract])
                    # Don't round to 0.5 for inverse pairs - show exact value
                    self.pips_str_inverse_offer = f"{pip_value:.{decimal_places}f}"
                else:
                    # Pad with zeros if needed
                    padded = pips_part.ljust(digits_to_extract, '0')
                    self.pips_str_inverse_offer = f"{float(padded):.{decimal_places}f}"
            else:
                self.pips_str_inverse_offer = "0.00"
        except:
            self.pips_str_inverse_offer = "0.00"
            
        # Format inverse mid pips
        try:
            mid_str = f"{self.inverse_mid:.{round_dp}f}"
            if '.' in mid_str and len(mid_str.split('.')[1]) > pips_places:
                pips_part = mid_str.split('.')[1][pips_places:]
                if len(pips_part) >= digits_to_extract:
                    # Extract digits and include decimal portion
                    if digits_to_extract == 2 and len(pips_part) > 2:
                        # For non-JPY pairs, include the third digit as decimal
                        pip_value = float(pips_part[:2] + "." + pips_part[2:3])
                    else:
                        # For JPY pairs, extract 3 digits as is
                        pip_value = float(pips_part[:digits_to_extract])
                    # Don't round to 0.5 for inverse pairs - show exact value
                    self.pips_str_inverse_mid = f"{pip_value:.{decimal_places}f}"
                else:
                    # Pad with zeros if needed
                    padded = pips_part.ljust(digits_to_extract, '0')
                    self.pips_str_inverse_mid = f"{float(padded):.{decimal_places}f}"
            else:
                self.pips_str_inverse_mid = "0.00"
        except:
            self.pips_str_inverse_mid = "0.00"
    
    def get_default_decimal_convention(self):
        """Get default decimal convention"""
        return {
            "decimal_places": 10000,
            "pips_places": 2,
            "skew_round_value": 0.00005,
            "round_dp": 5
        }
    
    def get_display_decimal_places_for_currency(self, quote):
        """
        Returns the number of decimal places that will put exactly *one pip*
        in the 4-th visible digit (5-th for JPY pairs – we still add one extra).
        """
        # Simple rule: JPY pairs get 3 dp, others get 5 dp
        if quote == "JPY":
            return 3  # For JPY as quote currency
        else:
            return 5  # For all other currencies

    def get_inverse_decimal_convention(self):
        """Get decimal convention for inverse currency pair"""
        if not self.inverse_ccy:
            return self.get_default_decimal_convention()
            
        # Check if inverse pair has a specific convention
        if self.inverse_ccy in self.ccy_spd_conventions:
            return self.ccy_spd_conventions[self.inverse_ccy]
        
        # Get base and quote currencies for inverse pair
        base_ccy = self.inverse_ccy[:3]
        quote_ccy = self.inverse_ccy[3:]
        
        # Use the new pip-aware decimal places logic
        display_dp = self.get_display_decimal_places_for_currency(quote_ccy)
        
        # For inverse pairs, add an extra decimal place for better precision
        # This is especially important for small values like JPYNZD
        if self.inverse_bid > 0 and self.inverse_bid < 0.1:
            display_dp += 1  # Add extra precision for small inverse values
        
        # Determine pip size and decimal places multiplier
        if quote_ccy == 'JPY':
            # Quote is JPY, so pip = 0.01
            return {
                "decimal_places": 100,  # for 0.01 pip size
                "pips_places": 0,  # For JPY pairs, pip is at 2nd decimal, skip 0 digits
                "skew_round_value": 0.005,
                "round_dp": display_dp
            }
        else:
            # Special handling for JPY as base currency (e.g., JPYNZD)
            if base_ccy == 'JPY':
                # JPY base pairs have very small values (e.g., 0.01190)
                # The pip is at the 3rd and 4th decimal places
                return {
                    "decimal_places": 10000,  # for 0.0001 pip size
                    "pips_places": 1,  # Skip only 1 digit for JPY base pairs
                    "skew_round_value": 0.00005,
                    "round_dp": display_dp
                }
            else:
                # Regular non-JPY pairs
                return {
                    "decimal_places": 10000,  # for 0.0001 pip size
                    "pips_places": 2,  # For non-JPY pairs, pip is at 4th decimal, skip 2 digits
                    "skew_round_value": 0.00005,
                    "round_dp": display_dp
                }
    
    def get_formatted_inverse_bid_with_arrow(self):
        """Get formatted inverse bid with direction arrow and color"""
        arrow = ""
        color = "#ffffff"  # Default white
        
        if self.inverse_bid_direction == 'up':
            arrow = " ↑"
            color = "#51cf66"  # Green
        elif self.inverse_bid_direction == 'down':
            arrow = " ↓"
            color = "#ff6b6b"  # Red
            
        # Format based on decimal convention
        convention = self.get_inverse_decimal_convention()
        formatted_bid = f"{self.inverse_bid:.{convention['round_dp']}f}"
        
        return f"Bid: {self.inverse_ccy} {formatted_bid}{arrow}", color
    
    def get_formatted_inverse_offer_with_arrow(self):
        """Get formatted inverse offer with direction arrow and color"""
        arrow = ""
        color = "#ffffff"  # Default white
        
        if self.inverse_offer_direction == 'up':
            arrow = " ↑"
            color = "#51cf66"  # Green
        elif self.inverse_offer_direction == 'down':
            arrow = " ↓"
            color = "#ff6b6b"  # Red
            
        # Format based on decimal convention
        convention = self.get_inverse_decimal_convention()
        formatted_offer = f"{self.inverse_offer:.{convention['round_dp']}f}"
        
        return f"Offer: {self.inverse_ccy} {formatted_offer}{arrow}", color

    def price_pips_mid(self):
        # Apply half-pip rounding to mid before extracting pips
        rounded_mid = self.round_to_half_pip(self.mid + self.skew)
        # Use round_dp + 1 to ensure we have enough decimal places
        decimals_needed = max(6, self.round_dp + 1)
        result = f"{rounded_mid:.{decimals_needed}f}".split(".")[1][self.pips_places:]
        # Round pips to nearest 0.5
        if len(result) >= 2:
            pip_value = float(result[:2] + "." + result[2:])
            rounded_pip = round(pip_value * 2) / 2  # Round to nearest 0.5
            self.pips_str_mid = f"{rounded_pip:.1f}"
        else:
            self.pips_str_mid = result.ljust(2, '0')

    # ====== 1  ======
    
    def price_pips_bid_synthetic(self):
        # Use cross-specific decimal convention
        cross_convention = self.get_cross_decimal_convention(self.cross_ccy)
        round_dp = cross_convention['round_dp']
        pips_places = cross_convention['pips_places']
        
        # Format with enough decimals
        decimals_needed = max(6, round_dp + 1)
        result = f"{self.bid:.{decimals_needed}f}".split(".")[1][pips_places:]
        # Take only first 2 digits for display
        if len(result) >= 2:
            self.pips_str_bid = str(round(float(str(result[:2] + "." + result[2:]))*2)/2)
        else:
            self.pips_str_bid = result.ljust(2, '0')
        
        
    def price_pips_mid_synthetic(self):
        # Initialize skew_cross if not present
        if not hasattr(self, 'skew'):
            self.skew = 0
        
        # Use cross-specific decimal convention    
        cross_convention = self.get_cross_decimal_convention(self.cross_ccy)
        round_dp = cross_convention['round_dp']
        pips_places = cross_convention['pips_places']
        
        # Format with enough decimals
        decimals_needed = max(6, round_dp + 1)
        result = f"{round(self.mid+self.skew, round_dp):.{decimals_needed}f}".split(".")[1][pips_places:]
        # Take only first 2 digits for display
        if len(result) >= 2:
            self.pips_str_mid = str(round(float(str(result[:2] + "." + result[2:]))*2)/2)
        else:
            self.pips_str_mid = result.ljust(2, '0')

    def price_pips_offer_synthetic(self):
        # Use cross-specific decimal convention
        cross_convention = self.get_cross_decimal_convention(self.cross_ccy)
        round_dp = cross_convention['round_dp']
        pips_places = cross_convention['pips_places']
        
        # Format with enough decimals
        decimals_needed = max(6, round_dp + 1)
        result = f"{self.offer:.{decimals_needed}f}".split(".")[1][pips_places:]
        # Take only first 2 digits for display
        if len(result) >= 2:
            self.pips_str_offer = str(round(float(str(result[:2] + "." + result[2:]))*2)/2)
        else:
            self.pips_str_offer = result.ljust(2, '0')
     # ====== 1  ======

    
    def price_pips_bid(self):
        # Apply half-pip rounding to bid before extracting pips
        rounded_bid = self.round_to_half_pip(self.bid)
        # Use round_dp + 1 to ensure we have enough decimal places
        decimals_needed = max(6, self.round_dp + 1)
        result = f"{rounded_bid:.{decimals_needed}f}".split(".")[1][self.pips_places:]
        # Round pips to nearest 0.5
        if len(result) >= 2:
            pip_value = float(result[:2] + "." + result[2:])
            rounded_pip = round(pip_value * 2) / 2  # Round to nearest 0.5
            self.pips_str_bid = f"{rounded_pip:.1f}"
        else:
            self.pips_str_bid = result.ljust(2, '0')

    def price_pips_offer(self):
        # Apply half-pip rounding to offer before extracting pips
        rounded_offer = self.round_to_half_pip(self.offer)
        # Use round_dp + 1 to ensure we have enough decimal places
        decimals_needed = max(6, self.round_dp + 1)
        result = f"{rounded_offer:.{decimals_needed}f}".split(".")[1][self.pips_places:]
        # Round pips to nearest 0.5
        if len(result) >= 2:
            pip_value = float(result[:2] + "." + result[2:])
            rounded_pip = round(pip_value * 2) / 2  # Round to nearest 0.5
            self.pips_str_offer = f"{rounded_pip:.1f}"
        else:
            self.pips_str_offer = result.ljust(2, '0')
    
    def round_to_half_pip(self, price):
        """Round price to the nearest half-pip using current decimal convention"""
        # half-pip = 0.5 / decimal_places
        half_pip = 0.5 / self.decimal_places  # works for majors & crosses
        return round(price / half_pip) * half_pip
    
    def get_display_decimal_places(self):
        """Get the correct decimal places for display, with synthetic cross guard"""
        if self.synthetic_cross_mode:
            # For synthetic crosses, use the cross-specific decimal places
            return getattr(self, "round_dp", 4)
        return getattr(self, "round_dp", 4)
    
    def get_formatted_bid(self):
        """Get properly formatted bid price for display"""
        # Use the calculated bid value which is set in price() method
        if hasattr(self, 'bid') and self.bid > 0:
            # Apply half-pip rounding for display
            rounded_bid = self.round_to_half_pip(self.bid)
            return f"{rounded_bid:.{self.round_dp}f}"
        # Fallback to raw data if bid not calculated yet
        elif self.ccy in self.bid_offer:
            market_bid = self.bid_offer[self.ccy][0]
            rounded_bid = self.round_to_half_pip(market_bid) if market_bid > 0 else 0
            return f"{rounded_bid:.{self.round_dp}f}" if market_bid > 0 else "0.000000"
        return "0.000000"
    
    def get_formatted_offer(self):
        """Get properly formatted offer price for display"""
        # Use the calculated offer value which is set in price() method
        if hasattr(self, 'offer') and self.offer > 0:
            # Apply half-pip rounding for display
            rounded_offer = self.round_to_half_pip(self.offer)
            return f"{rounded_offer:.{self.round_dp}f}"
        # Fallback to raw data if offer not calculated yet
        elif self.ccy in self.bid_offer:
            market_offer = self.bid_offer[self.ccy][1]
            rounded_offer = self.round_to_half_pip(market_offer) if market_offer > 0 else 0
            return f"{rounded_offer:.{self.round_dp}f}" if market_offer > 0 else "0.000000"
        return "0.000000"
    
    def set_manual_decimal_override(self, currency_pair, decimal_places):
        """Set manual decimal place override for a currency pair"""
        self.config['manual_dp_override'][currency_pair] = decimal_places
    
    def remove_manual_decimal_override(self, currency_pair):
        """Remove manual decimal place override for a currency pair"""
        if currency_pair in self.config['manual_dp_override']:
            del self.config['manual_dp_override'][currency_pair]
    
    def toggle_standard_dp(self):
        """Toggle between standard decimal places and custom logic"""
        self.config['use_standard_dp'] = not self.config['use_standard_dp']
    
    def get_direction_arrow(self, direction):
        """Get arrow symbol and color for price direction"""
        if direction == 'up':
            return '▲', '#51cf66'  # Green up triangle
        elif direction == 'down':
            return '▼', '#ff6b6b'  # Red down triangle  
        else:
            return '▶', '#ffffff'  # White right triangle
    
    def get_formatted_bid_with_arrow(self):
        """Get formatted bid with direction arrow and color"""
        price = self.get_formatted_bid()
        arrow, color = self.get_direction_arrow(self.bid_direction)
        return f"{price} {arrow}", color
    
    def get_formatted_offer_with_arrow(self):
        """Get formatted offer with direction arrow and color"""
        price = self.get_formatted_offer()
        arrow, color = self.get_direction_arrow(self.offer_direction)
        return f"{price} {arrow}", color
    
    def update_price_directions(self, current_bid, current_offer):
        """Update price direction tracking"""
        # Use appropriate epsilon based on decimal places
        epsilon = 10 ** (-self.round_dp - 1)
        
        # Only update directions if we have valid previous prices
        if self.previous_bid > 0 and self.previous_offer > 0:
            # Determine bid direction (simple price movement)
            if abs(current_bid - self.previous_bid) < epsilon:  # Same (within epsilon)
                self.bid_direction = 'same'
            elif current_bid > self.previous_bid:
                self.bid_direction = 'up'    # Price going up = up arrow
            else:
                self.bid_direction = 'down'  # Price going down = down arrow
                
            # Determine offer direction (simple price movement)
            if abs(current_offer - self.previous_offer) < epsilon:  # Same (within epsilon)
                self.offer_direction = 'same'
            elif current_offer > self.previous_offer:
                self.offer_direction = 'up'   # Price going up = up arrow
            else:
                self.offer_direction = 'down' # Price going down = down arrow
        
        # Update previous prices
        self.previous_bid = current_bid
        self.previous_offer = current_offer
    
    def test_cross_rate_calculation(self, cross_pair, expected_rate, tolerance=0.01):
        """Test cross rate calculation against expected value"""
        try:
            # Save current state
            original_ccy = self.ccy
            original_synthetic_mode = self.synthetic_cross_mode
            
            # Calculate the cross rate
            self.get_crosses_spreads(cross_pair, 50)  # Use 50M as test size
            calculated_rate = self.mid_cross
            
            # Check if within tolerance
            error = abs(calculated_rate - expected_rate)
            relative_error = error / expected_rate * 100
            
            result = {
                'pair': cross_pair,
                'expected': expected_rate,
                'calculated': calculated_rate,
                'error': error,
                'relative_error_pct': relative_error,
                'within_tolerance': error <= tolerance,
                'calculation_type': getattr(self, 'cross_calculation_type', 'unknown')
            }
            
            # Restore original state
            self.ccy = original_ccy
            self.synthetic_cross_mode = original_synthetic_mode
            
            return result
            
        except Exception as e:
            return {
                'pair': cross_pair,
                'error_message': str(e),
                'success': False
            }
        
    def get_formatted_market_bid(self):
        """Get properly formatted market bid price for display"""
        market_bid = self.bid_offer[self.ccy][0]
        return f"{market_bid:.{self.round_dp}f}" if market_bid > 0 else "0.00000"
        
    def get_formatted_market_offer(self):
        """Get properly formatted market offer price for display"""
        market_offer = self.bid_offer[self.ccy][1]
        return f"{market_offer:.{self.round_dp}f}" if market_offer > 0 else "0.00000"

    def choose_spread_matrix(self, matrix_choice='Default'):

        
        try:
            # Define what current_spread_matrix is
            if matrix_choice == 'Default':
                self.current_spread_matrix = self.spread_matrix
                

            elif matrix_choice == 'Super':
                self.current_spread_matrix = self.spread_matrix_super
                

            elif matrix_choice == 'Korea':
                self.current_spread_matrix = self.spread_matrix_korea
                
            elif matrix_choice == 'PBOC China':
                self.current_spread_matrix = self.spread_matrix_pboc_china
                
            

        except Exception as e:
            # any errors just use default spread matrix
            self.current_spread_matrix = self.spread_matrix
            print(e)

    def get_spread_cross_1(self, order_size):

        self.skew_cross_1 = 0
        #Determine what currency / how many decimal places:
        try:
            # Get ccy
            ccy_dict = self.ccy_spd_conventions[self.ccy_1_leg]
            
            self.decimal_places_cross_1 = ccy_dict['decimal_places']
            self.pips_places_cross_1 = ccy_dict['pips_places']
            self.skew_round_value_cross_1 = ccy_dict['skew_round_value']
            self.round_dp_cross_1 = ccy_dict['round_dp']
            
        except Exception as e:
            self.decimal_places_cross_1 = 10000
            self.pips_places_cross_1 = 2
            self.skew_round_value_cross_1 = 0.00005
            self.round_dp_cross_1 = 6
            print("Exception:")
            print(e)
    
        # Knowns X order sizes
        size_range = [int(i) for i in self.current_spread_matrix.columns]
        
        if order_size<size_range[0]:
            order_size=size_range[0]
        
        # Is size is not a standard size interp
        if order_size in size_range:
            self.spread_cross_1 = self.current_spread_matrix.loc[self.ccy_1_leg][order_size]
            
        else:
            
            # Ys
            spread_range = self.current_spread_matrix.loc[self.ccy_1_leg].values
            self.spread_cross_1 = round(np.interp(order_size, size_range, spread_range)) # To interp round to 2 decimal places to get half pips use self.spread = round(np.interp(order_size, size_range, spread_range),2) 

        # For synthetic crosses, apply half the manual spread to each leg
        self.spread_cross_1 = (self.spread_cross_1 + self.manual_spread / 2)
        self.spread_cross_1 = round(self.spread_cross_1/0.5)*0.5 #self.spread = round(self.spread/0.5)*0.5

        # If has a 0.5 then split into 1 and 0.5

        try:
            if float(self.spread_cross_1).is_integer():

                self.bid_spread_cross_1 = -((self.spread_cross_1/self.decimal_places_cross_1) / 2)
                self.offer_spread_cross_1 = +((self.spread_cross_1/self.decimal_places_cross_1) / 2)
            else:
                self.bid_spread_cross_1 = -(((self.spread_cross_1-0.5)/self.decimal_places_cross_1) / 2)
                self.offer_spread_cross_1 = +(((self.spread_cross_1+0.5)/self.decimal_places_cross_1) / 2)
        
        except Exception as e:
            self.bid_spread_cross_1 = -((self.spread_cross_1/self.decimal_places_cross_1) / 2)
            self.offer_spread_cross_1 = +((self.spread_cross_1/self.decimal_places_cross_1) / 2)
    
    def get_spread_cross_2(self, order_size):

        self.skew_cross_2 = 0
        #Determine what currency / how many decimal places:
        try:
            # Get ccy
            ccy_dict = self.ccy_spd_conventions[self.ccy_2_leg]
            
            self.decimal_places_cross_2 = ccy_dict['decimal_places']
            self.pips_places_cross_2 = ccy_dict['pips_places']
            self.skew_round_value_cross_2 = ccy_dict['skew_round_value']
            self.round_dp_cross_2 = ccy_dict['round_dp']
            
        except Exception as e:
            self.decimal_places_cross_2 = 10000
            self.pips_places_cross_2 = 2
            self.skew_round_value_cross_2 = 0.00005
            self.round_dp_cross_2 = 6
            print("Exception:")
            print(e)
    
        # Knowns X order sizes
        size_range = [int(i) for i in self.current_spread_matrix.columns]
        
        if order_size<size_range[0]:
            order_size=size_range[0]
        
        # Is size is not a standard size interp
        if order_size in size_range:
            self.spread_cross_2 = self.current_spread_matrix.loc[self.ccy_2_leg][order_size]
            
        else:
            
            # Ys
            spread_range = self.current_spread_matrix.loc[self.ccy_2_leg].values
            self.spread_cross_2 = round(np.interp(order_size, size_range, spread_range)) # To interp round to 2 decimal places to get half pips use self.spread = round(np.interp(order_size, size_range, spread_range),2) 

        # For synthetic crosses, apply half the manual spread to each leg
        self.spread_cross_2 = (self.spread_cross_2 + self.manual_spread / 2)
        self.spread_cross_2 = round(self.spread_cross_2/0.5)*0.5 #self.spread = round(self.spread/0.5)*0.5

        # If has a 0.5 then split into 1 and 0.5

        try:
            if float(self.spread_cross_2).is_integer():

                self.bid_spread_cross_2 = -((self.spread_cross_2/self.decimal_places_cross_2) / 2)
                self.offer_spread_cross_2 = +((self.spread_cross_2/self.decimal_places_cross_2) / 2)
            else:
                self.bid_spread_cross_2 = -(((self.spread_cross_2-0.5)/self.decimal_places_cross_2) / 2)
                self.offer_spread_cross_2 = +(((self.spread_cross_2+0.5)/self.decimal_places_cross_2) / 2)
        
        except Exception as e:
            self.bid_spread_cross_2 = -((self.spread_cross_2/self.decimal_places_cross_2) / 2)
            self.offer_spread_cross_2 = +((self.spread_cross_2/self.decimal_places_cross_2) / 2)

    def get_spread(self, order_size):

        self.skew = 0


        #Determine what currency / how many decimal places:
        try:
            
            # Get ccy
            ccy_dict = self.ccy_spd_conventions[self.ccy]
            
            self.decimal_places = ccy_dict['decimal_places']
            self.pips_places = ccy_dict['pips_places']
            self.skew_round_value = ccy_dict['skew_round_value']
            self.round_dp = ccy_dict['round_dp']
            
                

        except Exception as e:
            self.decimal_places = 10000
            self.pips_places = 2
            self.skew_round_value = 0.00005
            self.round_dp = 6
            print("Exception:")
            print(e)

    
        # Knowns X order sizes
        size_range = [int(i) for i in self.current_spread_matrix.columns]
        
        if order_size<size_range[0]:
            order_size=size_range[0]
        
        # Is size is not a standard size interp
        if order_size in size_range:
            # Check if currency exists in spread matrix (synthetic crosses won't)
            if self.ccy in self.current_spread_matrix.index:
                self.spread = self.current_spread_matrix.loc[self.ccy][order_size]
            else:
                # For synthetic crosses, use a default spread or calculate from legs
                self.spread = 2.0  # Default 2 pip spread for unknown crosses
            
        else:
            # Check if currency exists in spread matrix
            if self.ccy in self.current_spread_matrix.index:
                # Ys
                spread_range = self.current_spread_matrix.loc[self.ccy].values
                self.spread = round(np.interp(order_size, size_range, spread_range)) # To interp round to 2 decimal places to get half pips use self.spread = round(np.interp(order_size, size_range, spread_range),2)
            else:
                # For synthetic crosses, use a default spread
                self.spread = 2.0  # Default 2 pip spread for unknown crosses 

        self.spread = (self.spread + self.manual_spread)
        self.spread = round(self.spread/0.5)*0.5 #self.spread = round(self.spread/0.5)*0.5

        # If has a 0.5 then split into 1 and 0.5

        try:
            if float(self.spread).is_integer():

                self.bid_spread = -((self.spread/self.decimal_places) / 2)
                self.offer_spread = +((self.spread/self.decimal_places) / 2)
            else:
                self.bid_spread = -(((self.spread-0.5)/self.decimal_places) / 2)
                self.offer_spread = +(((self.spread+0.5)/self.decimal_places) / 2)
        
        except Exception as e:
            self.bid_spread = -((self.spread/self.decimal_places) / 2)
            self.offer_spread = +((self.spread/self.decimal_places) / 2)

                


class bbg:
    def __init__(self, pricing_obj):
        self.chosen_ccy = "AUDUSD"
        
        self.securities = [""]
        
        self.pricing_obj = pricing_obj
        self.ccys = self.pricing_obj.ccys
        self.executable_sizes = self.pricing_obj.executable_sizes

        # Track last update time for each currency pair
        self.last_update_times = {ccy: 0.0 for ccy in self.ccys}
        self.update_counts = {ccy: 0 for ccy in self.ccys}
        self.subscription_health_check_interval = 10.0  # Check subscription health every 10 seconds
        self.last_health_check_time = time.time()
        self.stale_threshold = 5.0  # Consider a currency pair stale if no updates for 5 seconds
        
        # Flag to track shutdown request
        self.shutdown_requested = False

        self.reverse_order_size = 0
        self.reverse_size_output = 0
        self.order_size = 10
        self.bid_spread = 0.0
        self.offer_spread = 0.0
        self.spread = 0.0
        self.high = 0.0
        self.low = 0.0

    def create_ccys_codes_by_size(self):

        self.securities_by_size = [f"{self.pricing_obj.ccy} BGNE {size} Curncy" for size in self.executable_sizes]

    def create_ccys_codes(self):
        # Filter out 'CROSS' as it's not a real currency pair
        self.securities = [f"{ccy} BGNE Curncy" for ccy in self.ccys if ccy != 'CROSS']
        
    
    def processMessage(self, msg):
        # Optimize message processing to reduce overhead
        try:
            # Cache frequently accessed values to avoid repeated lookups
            ccy = msg.correlationIds()[0].value().split(" ")[0]
            bid_offer_array = self.pricing_obj.bid_offer[ccy]
            
            # Update last update time and count for this currency pair
            current_time = time.time()
            self.last_update_times[ccy] = current_time
            self.update_counts[ccy] += 1
            
            # Batch all element checks before updating values
            has_bid = msg.hasElement('BID')
            has_ask = msg.hasElement('ASK')
            has_high = msg.hasElement('HIGH')
            has_low = msg.hasElement('LOW')
            
            # Update values in a single pass if they exist
            if has_bid:
                bid_offer_array[0] = msg.getElement('BID').getValue()
            if has_ask:
                bid_offer_array[1] = msg.getElement('ASK').getValue()
            if has_high:
                bid_offer_array[2] = msg.getElement('HIGH').getValue()
            if has_low:
                bid_offer_array[3] = msg.getElement('LOW').getValue()
                
        except Exception as e:
            # Only log serious errors that aren't just missing elements
            if "unavailable sub-element" not in str(e):
                print(f"Error in processMessage for {ccy}: {e}")
            return  # Exit early on error to avoid further processing
        
        # Only calculate prices if we have valid data
        try:
            pricing_obj = self.pricing_obj
            current_ccy = pricing_obj.ccy
            
            # Use direct comparison instead of multiple conditions when possible
            if ccy == current_ccy and not pricing_obj.synthetic_cross_mode:
                pricing_obj.price()
            elif pricing_obj.synthetic_cross_mode and (ccy == pricing_obj.ccy_1_leg or ccy == pricing_obj.ccy_2_leg):
                pricing_obj.price_synthetic_cross()
        except Exception as e:
            # Use more specific error handling only when needed
            error_type = type(e).__name__
            print(f"{error_type} in price calculation for {ccy}: {e}")
            

        

    def check_subscription_health(self):
        """Check if any currency pairs haven't been updated recently and resubscribe if needed"""
        current_time = time.time()
        
        # Only check periodically to avoid excessive logging and resubscriptions
        if current_time - self.last_health_check_time < self.subscription_health_check_interval:
            return
            
        self.last_health_check_time = current_time
        stale_ccys = []
        
        # Check for stale currency pairs
        for ccy in self.ccys:
            # Skip 'CROSS' as it's not a real currency pair but a placeholder
            if ccy == 'CROSS':
                continue
                
            if ccy in self.last_update_times:
                time_since_update = current_time - self.last_update_times[ccy]
                if time_since_update > self.stale_threshold:
                    stale_ccys.append(ccy)
        
        # If we have stale currency pairs, resubscribe to them
        if stale_ccys:
            print(f"Detected stale currency pairs: {', '.join(stale_ccys)}. Resubscribing...")
            self.resubscribe(stale_ccys)
            
    def resubscribe(self, stale_ccys=None):
        """Resubscribe to all securities or just the stale ones"""
        try:
            subscriptionList = blpapi.SubscriptionList()
            
            # Create the securities list if needed
            self.create_ccys_codes()
            
            # If specific stale currencies are provided, only resubscribe to those
            if stale_ccys:
                # Filter out 'CROSS' as it's not a real currency pair
                filtered_ccys = [ccy for ccy in stale_ccys if ccy != 'CROSS']
                if not filtered_ccys:
                    # If all stale currencies were filtered out (only CROSS was stale), return early
                    return
                securities_to_resubscribe = [f"{ccy} BGNE Curncy" for ccy in filtered_ccys]
                
                # Unsubscribe from these specific securities first
                for security in securities_to_resubscribe:
                    try:
                        unsub_list = blpapi.SubscriptionList()
                        unsub_list.add(security, "BID,ASK,HIGH,LOW", "", blpapi.CorrelationId(security))
                        self.session.unsubscribe(unsub_list)
                    except Exception as e:
                        print(f"Error unsubscribing from {security}: {e}")
                
                # Resubscribe to these securities
                for security in securities_to_resubscribe:
                    subscriptionList.add(security, "BID,ASK,HIGH,LOW", "", blpapi.CorrelationId(security))
                    
                print(f"Resubscribed to {len(securities_to_resubscribe)} securities")
            else:
                # Unsubscribe from all securities
                try:
                    self.session.unsubscribe()
                except Exception as e:
                    print(f"Error unsubscribing from all securities: {e}")
                
                # Resubscribe to all securities
                for security in self.securities:
                    subscriptionList.add(security, "BID,ASK,HIGH,LOW", "", blpapi.CorrelationId(security))
                
                print(f"Resubscribed to all {len(self.securities)} securities")
            
            # Perform the subscription
            self.session.subscribe(subscriptionList)
            
            # Reset update times for resubscribed securities
            current_time = time.time()
            if stale_ccys:
                for ccy in stale_ccys:
                    self.last_update_times[ccy] = current_time
            else:
                for ccy in self.ccys:
                    self.last_update_times[ccy] = current_time
                    
        except Exception as e:
            print(f"Error in resubscribe: {e}")
    
    def shutdown(self):
        """Request shutdown of the Bloomberg data stream"""
        print("Shutting down Bloomberg connection...")
        self.shutdown_requested = True
        try:
            if hasattr(self, 'session') and self.session:
                # Create an empty subscription list for unsubscribing from all securities
                subscriptionList = blpapi.SubscriptionList()
                self.session.unsubscribe(subscriptionList)
                self.session.stop()
                print("Bloomberg session stopped successfully")
        except Exception as e:
            print(f"Error stopping Bloomberg session: {e}")
        print("Bloomberg connection shutdown initiated")
      
    def run(self):

        #########################################
        options = blpapi.SessionOptions()
        options.setServerHost('localhost')
        options.setServerPort(8194)
        
        # Configure session options to handle slow consumer issues
        options.setMaxEventQueueSize(20000)  # Increase from default
        options.setSlowConsumerWarningHiWaterMark(0.75)  # Warn at 75% capacity
        options.setSlowConsumerWarningLoWaterMark(0.5)   # Clear warning at 50% capacity
        
        self.session = blpapi.Session(options)
        options.maxEvents = 10  # Increased from 2 to process more events at once
        self.session.start()
        #########################################
        print("Connecting")

        
        self.create_ccys_codes()
        self.create_ccys_codes_by_size()
        print("Created list of securities")

        # Create a Session
        self.session = blpapi.Session(options)

        # Start a Session
        if not self.session.start():
            print("Failed to start session.")
            return

        if not self.session.openService("//blp/mktdata"):
            print("Failed to open //blp/mktdata")
            return
        

        #security1 = "USAD BGNE Curncy"
        security1 = "AUD BGNE Curncy"
        #security2 = "/cusip/912828GM6@BGN"

        subscriptionList = blpapi.SubscriptionList()
        for security in self.securities:
            subscriptionList.add(security, "BID,ASK,HIGH,LOW", "", blpapi.CorrelationId(security))

        # for security in self.securities_by_size:
        #     subscriptionList.add(security, "BID,ASK,HIGH,LOW", "", blpapi.CorrelationId(security))


        self.session.subscribe(subscriptionList)

        # Flag to track shutdown request
        self.shutdown_requested = False
        
        # Process received events
        while not self.shutdown_requested:
            # We provide timeout to give the chance to Ctrl+C handling:
            while not self.shutdown_requested:
                try:
                    # Check subscription health periodically
                    self.check_subscription_health()
                    
                    # Process events with fair distribution across currency pairs
                    max_events_per_iteration = 40  # Increased to handle more events
                    event_count = 0
                    events_processed = 0
                    
                    # Track which currency pairs were updated in this batch
                    updated_ccys = set()
                    
                    # Process multiple events in a batch to catch up with queue
                    while events_processed < 60:  # Increased to process more events before yielding
                        event = self.session.nextEvent(50)  # Reduced timeout for more responsive handling
                        
                        # Only process subscription data events to avoid wasting time on other events
                        if event.eventType() == blpapi.Event.SUBSCRIPTION_DATA:
                            for msg in event:
                                try:
                                    # Track which currency pair this message is for
                                    ccy = msg.correlationIds()[0].value().split(" ")[0]
                                    updated_ccys.add(ccy)
                                    
                                    # Process the message
                                    self.processMessage(msg)
                                    event_count += 1
                                except Exception as e:
                                    print(f"Error processing message: {e}")
                                
                                # Break after processing a batch of messages
                                if event_count >= max_events_per_iteration:
                                    break
                            
                            if event_count >= max_events_per_iteration:
                                break
                        
                        events_processed += 1
                        
                        # If no more events, break out
                        if event.eventType() == blpapi.Event.TIMEOUT:
                            break
                    
                    # Track update statistics but don't log them by default
                    if hasattr(self, 'yield_count'):
                        self.yield_count += 1
                        # Uncomment the following block to enable logging of update counts
                        # if self.yield_count % 100 == 0:
                        #     # Find currency pairs with lowest update counts
                        #     sorted_counts = sorted([(ccy, count) for ccy, count in self.update_counts.items()],
                        #                          key=lambda x: x[1])
                        #     least_updated = sorted_counts[:3]
                        #     most_updated = sorted_counts[-3:]
                        #     print(f"Update counts - Least: {least_updated}, Most: {most_updated}")
                    else:
                        self.yield_count = 1
                    
                    # Yield after processing a batch of events
                    yield self.pricing_obj.bid_offer
                    
                except Exception as e:
                    print(f"Error in event processing: {e}")
                    # Still yield to keep UI responsive even if there's an error
                    yield self.pricing_obj.bid_offer


class simulated_data:
    def __init__(self, pricing_obj):
        self.pricing_obj = pricing_obj
        self.ccys = self.pricing_obj.ccys
        # Updated FX rates from July 15, 2025, 16:00 UTC (XE mid-market quotes)
        self.example_rates = {
            "AUDUSD": 0.6519, "EURUSD": 1.1618, "GBPUSD": 1.3395, "NZDUSD": 0.5949, "USDCAD": 1.3714,
            "USDJPY": 148.79, "USDSGD": 1.2849, "USDCHF": 0.8005, "AUDNZD": 1.0959, "USDCNH": 7.1743,
            "EURJPY": 172.86, "AUDJPY": 97.00, "EURGBP": 0.8673, "EURCHF": 0.9300, "AUDGBP": 0.4867,
            "USDNOK": 10.2292, "EURCAD": 1.5932, "USDHKD": 7.8500, "EURNZD": 1.9529, "EURSEK": 11.2853,
            "USDPLN": 3.6704, "EURAUD": 1.7821, "EURNOK": 11.8840, "EURDKK": 7.4635, "USDSEK": 9.7139
        }
        
        # Realistic spreads for different currency pairs (in pips)
        self.typical_spreads = {
            "AUDUSD": 0.8, "EURUSD": 0.6, "GBPUSD": 1.0, "NZDUSD": 1.2, "USDCAD": 1.0,
            "USDJPY": 0.8, "USDSGD": 1.5, "USDCHF": 1.0, "AUDNZD": 2.0, "USDCNH": 3.0,
            "EURJPY": 1.2, "AUDJPY": 1.5, "EURGBP": 1.0, "EURCHF": 1.2, "AUDGBP": 2.0,
            "USDNOK": 4.0, "EURCAD": 1.5, "USDHKD": 2.0, "EURNZD": 3.0, "EURSEK": 4.0,
            "USDPLN": 3.0, "EURAUD": 2.0, "EURNOK": 5.0, "EURDKK": 2.0, "USDSEK": 4.0
        }
        
        # Typical daily ranges in percentage (for realistic high/low simulation)
        self.typical_daily_ranges = {
            "EURUSD": 0.5, "GBPUSD": 0.6, "USDJPY": 0.4, "AUDUSD": 0.7,
            "USDCAD": 0.5, "NZDUSD": 0.8, "USDCHF": 0.5, "EURGBP": 0.4
        }
        
        # Track price trends and volatility for more realistic simulation
        self.price_trends = {ccy: 0.0 for ccy in self.ccys}
        self.volatility_states = {ccy: 'normal' for ccy in self.ccys}
        self.session_highs = {}
        self.session_lows = {}
        self.session_start_time = time.time()
        self.last_session_reset = time.time()
        
        # Initialize session highs and lows
        self._reset_session_high_low()
    
    def _reset_session_high_low(self):
        """Reset session highs and lows to current prices"""
        for ccy in self.ccys:
            if ccy in self.example_rates:
                base_rate = self.example_rates[ccy]
                # Start with a very tight initial range (will expand as prices move)
                spread_pips = self.typical_spreads.get(ccy, 1.0)
                pip_value = 0.01 if 'JPY' in ccy else 0.0001
                initial_spread = spread_pips * pip_value
                
                # Start high/low just slightly above/below the current rate
                self.session_highs[ccy] = base_rate + initial_spread
                self.session_lows[ccy] = base_rate - initial_spread
            else:
                # For unknown pairs, use current rate
                self.session_highs[ccy] = 0.0
                self.session_lows[ccy] = float('inf')

    def generate_simulated_data(self):
        last_update = time.time()
        update_interval = 0.1  # Update every 100ms for smoother data flow
        
        # Initialize bid_offer array with realistic starting values
        for ccy in self.ccys:
            if ccy in self.example_rates:
                base_rate = self.example_rates[ccy]
                spread_pips = self.typical_spreads.get(ccy, 1.0)
                
                if 'JPY' in ccy:
                    pip_value = 0.01
                else:
                    pip_value = 0.0001
                    
                spread = spread_pips * pip_value
                bid = base_rate - spread/2
                offer = base_rate + spread/2
                
                # Initialize with proper high/low values from session tracking
                high = self.session_highs.get(ccy, offer)
                low = self.session_lows.get(ccy, bid)
                self.pricing_obj.bid_offer[ccy] = np.array([bid, offer, high, low])
        
        # Call price() once to initialize all calculated values
        self.pricing_obj.price()
        
        while True:
            current_time = time.time()
            
            # Check if we should reset session (every 24 hours for demo, or every hour for testing)
            if current_time - self.last_session_reset > 3600:  # Reset every hour
                self._reset_session_high_low()
                self.last_session_reset = current_time
                print("📊 Session highs/lows reset")
            
            # Only update data at specified intervals to reduce CPU usage
            if current_time - last_update >= update_interval:
                for ccy in self.ccys:
                    if ccy in self.example_rates:
                        # Get current trend for this currency
                        trend = self.price_trends.get(ccy, 0.0)
                        
                        # Update trend occasionally (trend persistence)
                        if random.random() < 0.05:  # 5% chance to change trend
                            self.price_trends[ccy] = random.uniform(-0.00002, 0.00002)
                        
                        # Simulate market events (breakouts, reversals)
                        if random.random() < 0.001:  # 0.1% chance of significant move
                            # Breakout or reversal
                            self.volatility_states[ccy] = 'high'
                            trend = random.uniform(-0.0001, 0.0001)  # Stronger move
                            self.price_trends[ccy] = trend
                        
                        # Get base rate and apply trend
                        base_rate = self.example_rates[ccy]
                        
                        # Add mean reversion toward middle of daily range
                        daily_range_pct = self.typical_daily_ranges.get(ccy, 0.6) / 100
                        current_high = self.session_highs.get(ccy, base_rate * 1.01)
                        current_low = self.session_lows.get(ccy, base_rate * 0.99)
                        range_position = (base_rate - current_low) / (current_high - current_low) if current_high > current_low else 0.5
                        
                        # Mean reversion component (stronger when near extremes)
                        if range_position > 0.8:  # Near high
                            mean_reversion = -0.00001 * (range_position - 0.5)
                        elif range_position < 0.2:  # Near low
                            mean_reversion = 0.00001 * (0.5 - range_position)
                        else:
                            mean_reversion = 0
                        
                        # Calculate price change with trend and mean reversion
                        volatility = 0.00001 if self.volatility_states[ccy] == 'normal' else 0.00005
                        price_change = trend + mean_reversion + random.uniform(-volatility, volatility)
                        
                        # Update the base rate slightly to simulate price movement
                        self.example_rates[ccy] = max(0.0001, self.example_rates[ccy] * (1 + price_change))
                        new_rate = self.example_rates[ccy]
                        
                        # Decay high volatility state
                        if self.volatility_states[ccy] == 'high' and random.random() < 0.1:
                            self.volatility_states[ccy] = 'normal'
                        
                        # Calculate realistic spread based on currency pair
                        spread_pips = self.typical_spreads.get(ccy, 1.0)
                        
                        # Convert pips to decimal based on currency convention
                        if 'JPY' in ccy:
                            pip_value = 0.01  # JPY pairs use 2 decimal places
                        else:
                            pip_value = 0.0001  # Most pairs use 4 decimal places
                            
                        spread_decimal = spread_pips * pip_value
                        
                        # Add some spread volatility (spreads widen during high volatility)
                        volatility_multiplier = random.uniform(0.8, 1.5)
                        actual_spread = spread_decimal * volatility_multiplier
                        
                        # Calculate bid/offer around the new rate
                        mid_rate = new_rate
                        bid = mid_rate - (actual_spread / 2)
                        offer = mid_rate + (actual_spread / 2)
                        
                        # Track session highs and lows
                        self.session_highs[ccy] = max(self.session_highs[ccy], offer)
                        self.session_lows[ccy] = min(self.session_lows[ccy], bid)
                        
                        # Use session highs/lows for display
                        high = self.session_highs[ccy]
                        low = self.session_lows[ccy]
                        
                        self.pricing_obj.bid_offer[ccy] = np.array([bid, offer, high, low])
                    else:
                        # Handle cross rates and unknown pairs
                        if ccy not in self.example_rates:
                            # Check if this is a cross rate we can calculate
                            if len(ccy) == 6:  # Standard currency pair format
                                ccy1, ccy2 = ccy[:3], ccy[3:]
                                
                                # Try to calculate from component currencies
                                calculated = False
                                for base_ccy in self.example_rates:
                                    if ccy1 in base_ccy and 'USD' in base_ccy:
                                        for quote_ccy in self.example_rates:
                                            if ccy2 in quote_ccy and 'USD' in quote_ccy:
                                                # Calculate cross rate
                                                if base_ccy.endswith('USD'):
                                                    rate1 = self.example_rates[base_ccy]
                                                else:
                                                    rate1 = 1 / self.example_rates[base_ccy]
                                                
                                                if quote_ccy.startswith('USD'):
                                                    rate2 = self.example_rates[quote_ccy]
                                                else:
                                                    rate2 = 1 / self.example_rates[quote_ccy]
                                                
                                                self.example_rates[ccy] = rate1 * rate2
                                                calculated = True
                                                break
                                    if calculated:
                                        break
                                
                                if not calculated:
                                    self.example_rates[ccy] = random.uniform(0.5, 1.5)
                            else:
                                self.example_rates[ccy] = random.uniform(0.5, 1.5)
                        
                        # Initialize session high/low if not set
                        if ccy not in self.session_highs:
                            self.session_highs[ccy] = self.example_rates[ccy] * 1.002
                            self.session_lows[ccy] = self.example_rates[ccy] * 0.998
                            
                        base_rate = self.example_rates[ccy]
                        
                        # Apply some price movement
                        movement = random.uniform(-0.0001, 0.0001)
                        self.example_rates[ccy] = base_rate * (1 + movement)
                        
                        # Determine spread based on liquidity
                        if 'JPY' in ccy:
                            spread = random.uniform(0.01, 0.02)
                        else:
                            spread = random.uniform(0.0001, 0.0005)
                            
                        bid = self.example_rates[ccy] - (spread / 2)
                        offer = self.example_rates[ccy] + (spread / 2)
                        
                        # Update session highs and lows
                        self.session_highs[ccy] = max(self.session_highs[ccy], offer)
                        self.session_lows[ccy] = min(self.session_lows[ccy], bid)
                        
                        high = self.session_highs[ccy]
                        low = self.session_lows[ccy]
                        
                        self.pricing_obj.bid_offer[ccy] = np.array([bid, offer, high, low])
                
                # Update market data timestamp for BLPAPI simulation
                self.pricing_obj.market_data_timestamp = time.time()
                self.pricing_obj.last_market_update_time = time.time()
                
                # Only call price() once per update cycle to trigger calculations
                self.pricing_obj.price()
                
                # Also update synthetic cross if in cross mode
                if self.pricing_obj.synthetic_cross_mode:
                    self.pricing_obj.price_synthetic_cross()
                
                last_update = current_time
            
            time.sleep(0.02)  # Short sleep to prevent excessive CPU usage
            yield self.pricing_obj.bid_offer


def test_cross_rates_with_examples():
    """Test cross rate calculations with user-provided examples"""
    # Create pricing instance
    p = pricing()
    
    # Set up test rates (from user's examples)
    test_rates = {
        'EURUSD': [1.1618, 1.1618],  # bid, ask (using mid for simplicity)
        'USDCNH': [7.1743, 7.1743],
        'NZDUSD': [0.5949, 0.5949],
        'USDJPY': [148.79, 148.79],
        'GBPUSD': [1.3395, 1.3395],
        'USDCAD': [1.3714, 1.3714],
        'USDCHF': [0.8005, 0.8005]
    }
    
    # Load test rates into bid_offer
    for pair, rates in test_rates.items():
        p.bid_offer[pair] = np.array([rates[0], rates[1], rates[1]*1.001, rates[0]*0.999])
    
    # Test cases from user's examples
    test_cases = [
        ('EURCNH', 8.3351),  # EUR/USD × USD/CNH
        ('NZDJPY', 88.52),   # NZD/USD × USD/JPY
        ('GBPCAD', 0.9767),  # GBP/USD ÷ USD/CAD
        ('CHFJPY', 185.90),  # USD/JPY ÷ USD/CHF
    ]
    
    print("\n=== Cross Rate Calculation Tests ===")
    for cross_pair, expected in test_cases:
        result = p.test_cross_rate_calculation(cross_pair, expected, tolerance=0.1)
        
        if 'error_message' in result:
            print(f"{cross_pair}: ERROR - {result['error_message']}")
        else:
            status = "✅ PASS" if result['within_tolerance'] else "❌ FAIL"
            print(f"{cross_pair}: {status}")
            print(f"  Expected: {result['expected']:.4f}")
            print(f"  Calculated: {result['calculated']:.4f}")
            print(f"  Error: {result['relative_error_pct']:.2f}%")
            print(f"  Method: {result['calculation_type']}")
            print()

if __name__ == "__main__":
    test_cross_rates_with_examples()
                        
                        

