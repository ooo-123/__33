from collections import deque
from typing import Dict, List, Tuple, Optional
import time


class RateConverter:
    """Handles conversion between currencies using BFS to find optimal paths"""
    
    def __init__(self):
        self.cache = {}  # Cache conversion rates to avoid repeated calculations
        self.cache_expiry = 60  # Cache for 60 seconds
        self.last_cache_time = {}
        
    def build_rate_graph(self, rates: Dict[str, float]) -> Dict[str, Dict[str, float]]:
        """Build a graph of currency conversions from available rates"""
        graph = {}
        
        # Add all direct rates and their inverses
        for pair, rate_data in rates.items():
            if len(pair) == 6:
                # Handle numpy arrays from bid_offer dict
                if hasattr(rate_data, '__len__') and len(rate_data) >= 2:
                    # It's an array, use mid-point of bid/ask
                    rate = float((rate_data[0] + rate_data[1]) / 2)
                else:
                    # It's a scalar
                    rate = float(rate_data)
                
                if rate > 0:
                    base = pair[:3]
                    quote = pair[3:6]
                    
                    # Add direct rate
                    if base not in graph:
                        graph[base] = {}
                    graph[base][quote] = rate
                    
                    # Add inverse rate
                    if quote not in graph:
                        graph[quote] = {}
                    graph[quote][base] = 1.0 / rate
                
        return graph
    
    def find_rate_bfs(self, from_ccy: str, to_ccy: str, graph: Dict[str, Dict[str, float]]) -> Optional[float]:
        """Find conversion rate using BFS through the currency graph"""
        if from_ccy == to_ccy:
            return 1.0
            
        if from_ccy not in graph:
            return None
            
        # Check cache first
        cache_key = f"{from_ccy}_{to_ccy}"
        current_time = time.time()
        if cache_key in self.cache and (current_time - self.last_cache_time.get(cache_key, 0)) < self.cache_expiry:
            return self.cache[cache_key]
        
        # BFS to find shortest path
        queue = deque([(from_ccy, 1.0)])
        visited = {from_ccy}
        
        while queue:
            current_ccy, current_rate = queue.popleft()
            
            if current_ccy in graph:
                for next_ccy, rate in graph[current_ccy].items():
                    if next_ccy not in visited:
                        new_rate = current_rate * rate
                        
                        if next_ccy == to_ccy:
                            # Cache the result
                            self.cache[cache_key] = new_rate
                            self.last_cache_time[cache_key] = current_time
                            return new_rate
                            
                        visited.add(next_ccy)
                        queue.append((next_ccy, new_rate))
        
        return None
    
    def find_rate(self, from_ccy: str, to_ccy: str, rates: Dict[str, any]) -> Optional[float]:
        """Main method to find conversion rate"""
        # Build graph from current rates
        graph = self.build_rate_graph(rates)
        
        # Find rate using BFS
        return self.find_rate_bfs(from_ccy, to_ccy, graph)


class PipValueCalculator:
    """Calculates pip values in USD for any currency pair"""
    
    def __init__(self):
        self.rate_converter = RateConverter()
        self.last_calculation = {}  # Cache last calculation per pair
        self.static_pip_values = {}  # Cache static pip values per pair
        
    def get_pip_size(self, quote_ccy: str) -> float:
        """Get pip size based on quote currency"""
        if quote_ccy == 'JPY':
            return 0.01
        else:
            return 0.0001
    
    def calculate_pip_value(self, pair: str, current_rate: float, rates_dict: Dict[str, float]) -> Dict[str, any]:
        """
        Calculate pip value per million base currency
        
        Args:
            pair: Currency pair (e.g., 'EURUSD', 'NZDJPY')
            current_rate: Current rate for the pair
            rates_dict: Dictionary of all available rates
            
        Returns:
            Dictionary with pip value info and calculation details
        """
        if len(pair) != 6:
            return {"error": "Invalid pair format"}
            
        base_ccy = pair[:3]
        quote_ccy = pair[3:6]
        
        # Get pip size
        pip_size = self.get_pip_size(quote_ccy)
        
        # Pip value in quote currency per 1M base
        pip_in_quote = 1_000_000 * pip_size
        
        # Convert quote currency to USD
        if quote_ccy == 'USD':
            quote_to_usd = 1.0
        else:
            # First try direct pair XXXUSD
            direct_pair = quote_ccy + 'USD'
            if direct_pair in rates_dict:
                rate_data = rates_dict[direct_pair]
                # Handle numpy arrays from bid_offer dict
                if hasattr(rate_data, '__len__') and len(rate_data) >= 2:
                    quote_to_usd = float((rate_data[0] + rate_data[1]) / 2)
                else:
                    quote_to_usd = float(rate_data)
            else:
                # Try inverse pair USDXXX
                inverse_pair = 'USD' + quote_ccy
                if inverse_pair in rates_dict:
                    rate_data = rates_dict[inverse_pair]
                    # Handle numpy arrays from bid_offer dict
                    if hasattr(rate_data, '__len__') and len(rate_data) >= 2:
                        usd_to_quote = float((rate_data[0] + rate_data[1]) / 2)
                    else:
                        usd_to_quote = float(rate_data)
                    
                    if usd_to_quote > 0:
                        quote_to_usd = 1.0 / usd_to_quote
                    else:
                        quote_to_usd = None
                else:
                    # Fall back to BFS if direct methods fail
                    quote_to_usd = self.rate_converter.find_rate(quote_ccy, 'USD', rates_dict)
        
        result = {
            "pair": pair,
            "base_ccy": base_ccy,
            "quote_ccy": quote_ccy,
            "pip_size": pip_size,
            "pip_in_quote": pip_in_quote,
            "current_rate": current_rate
        }
        
        if quote_to_usd is not None:
            # Successfully found conversion to USD
            pip_in_usd = pip_in_quote * quote_to_usd
            result.update({
                "pip_in_usd": pip_in_usd,
                "quote_to_usd_rate": quote_to_usd,
                "success": True
            })
        else:
            # Fallback: try via base currency
            base_to_usd = self.rate_converter.find_rate(base_ccy, 'USD', rates_dict)
            
            if base_to_usd is not None and current_rate > 0:
                pip_in_base = pip_in_quote / current_rate
                pip_in_usd = pip_in_base * base_to_usd
                result.update({
                    "pip_in_usd": pip_in_usd,
                    "pip_in_base": pip_in_base,
                    "base_to_usd_rate": base_to_usd,
                    "success": True,
                    "via_base": True
                })
            else:
                # No path to USD found
                if current_rate > 0:
                    pip_in_base = pip_in_quote / current_rate
                    result.update({
                        "pip_in_base": pip_in_base,
                        "success": False,
                        "error": "No USD conversion available"
                    })
                else:
                    result.update({
                        "success": False,
                        "error": "Invalid rate"
                    })
        
        # Cache the result
        self.last_calculation[pair] = result
        
        return result
    
    def precalculate_all_pairs(self, pairs: List[str], rates_dict: Dict[str, any]) -> None:
        """Pre-calculate pip values for all pairs for efficiency"""
        for pair in pairs:
            if len(pair) == 6:
                # Get a representative rate for the pair
                if pair in rates_dict:
                    rate_data = rates_dict[pair]
                    if hasattr(rate_data, '__len__') and len(rate_data) >= 2:
                        rate = float((rate_data[0] + rate_data[1]) / 2)
                    else:
                        rate = float(rate_data) if rate_data else 1.0
                else:
                    rate = 1.0  # Default rate
                
                # Calculate and cache
                result = self.calculate_pip_value(pair, rate, rates_dict)
                if result.get('success'):
                    # Store the pip value in USD (doesn't change with rate for same pair)
                    self.static_pip_values[pair] = result['pip_in_usd']
    
    def get_cached_pip_value(self, pair: str) -> Optional[float]:
        """Get cached pip value in USD for a pair"""
        # Don't use cache for cross currencies (non-G10 pairs)
        base_ccy = pair[:3] if len(pair) >= 6 else ''
        quote_ccy = pair[3:6] if len(pair) >= 6 else ''
        
        # List of G10 currencies that have direct USD pairs
        g10_currencies = ['EUR', 'GBP', 'AUD', 'NZD', 'USD', 'CAD', 'CHF', 'JPY']
        
        # Skip cache for non-G10 crosses
        if quote_ccy not in g10_currencies or (base_ccy not in g10_currencies and 'USD' not in pair):
            return None
            
        return self.static_pip_values.get(pair)
    
    def format_pip_value_display(self, result: Dict[str, any]) -> str:
        """Format pip value calculation result for display"""
        if not result.get("success"):
            if "pip_in_base" in result:
                return f"Pip: {result['pip_in_base']:.6f} {result['base_ccy']}/pip/1M"
            else:
                return "Pip: N/A"
        
        pip_usd = result["pip_in_usd"]
        base_ccy = result["base_ccy"]
        
        # Format based on size
        if pip_usd >= 1000:
            return f"Pip: {pip_usd:,.0f} USD/1M {base_ccy}"
        elif pip_usd >= 10:
            return f"Pip: {pip_usd:.2f} USD/1M {base_ccy}"
        else:
            return f"Pip: {pip_usd:.4f} USD/1M {base_ccy}"
    
    def format_compact_display(self, result: Dict[str, any]) -> str:
        """Format pip value for compact display"""
        if not result.get("success"):
            return "--"
        
        pip_usd = result["pip_in_usd"]
        
        # Very compact format
        if pip_usd >= 1000:
            return f"${pip_usd/1000:.1f}k"
        elif pip_usd >= 100:
            return f"${pip_usd:.0f}"
        elif pip_usd >= 10:
            return f"${pip_usd:.1f}"
        else:
            return f"${pip_usd:.2f}"
    
    def format_compact_display_scaled(self, result: Dict[str, any], order_size: float) -> str:
        """Format pip value for compact display, scaled by order size"""
        if not result.get("success"):
            return "--"
        
        pip_usd = result["pip_in_usd"]
        # Scale by order size (pip_usd is per 1M, so divide order_size by 1M)
        scaled_pip_usd = pip_usd * (order_size / 1.0)
        
        # Very compact format for scaled values with M for millions
        if scaled_pip_usd >= 1_000_000:
            # Use millions
            formatted = f"${scaled_pip_usd/1_000_000:.1f}M"
            # Remove trailing .0
            if formatted.endswith('.0M'):
                return f"${scaled_pip_usd/1_000_000:.0f}M"
            return formatted
        elif scaled_pip_usd >= 10000:
            return f"${scaled_pip_usd/1000:.0f}k"
        elif scaled_pip_usd >= 1000:
            return f"${scaled_pip_usd/1000:.1f}k"
        elif scaled_pip_usd >= 100:
            return f"${scaled_pip_usd:.0f}"
        elif scaled_pip_usd >= 10:
            return f"${scaled_pip_usd:.1f}"
        else:
            return f"${scaled_pip_usd:.2f}"
    
    def format_compact_display_both(self, result: Dict[str, any], order_size: float) -> str:
        """Format pip value showing both per-million and scaled values"""
        if not result.get("success"):
            return "--"
        
        pip_usd = result["pip_in_usd"]
        scaled_pip_usd = pip_usd * (order_size / 1.0)
        
        # Format per-million value
        if pip_usd >= 100:
            per_m = f"${pip_usd:.0f}/M"
        elif pip_usd >= 10:
            per_m = f"${pip_usd:.1f}/M"
        else:
            per_m = f"${pip_usd:.2f}/M"
        
        # Format scaled value with M for millions
        if scaled_pip_usd >= 1_000_000:
            # Use millions
            formatted = f"${scaled_pip_usd/1_000_000:.1f}M"
            # Remove trailing .0
            if formatted.endswith('.0M'):
                scaled = f"${scaled_pip_usd/1_000_000:.0f}M"
            else:
                scaled = formatted
        elif scaled_pip_usd >= 10000:
            scaled = f"${scaled_pip_usd/1000:.0f}k"
        elif scaled_pip_usd >= 1000:
            scaled = f"${scaled_pip_usd/1000:.1f}k"
        elif scaled_pip_usd >= 100:
            scaled = f"${scaled_pip_usd:.0f}"
        elif scaled_pip_usd >= 10:
            scaled = f"${scaled_pip_usd:.1f}"
        else:
            scaled = f"${scaled_pip_usd:.2f}"
        
        # Return both values
        return f"{per_m} ({scaled})"
    
    def format_pip_value_display_scaled(self, result: Dict[str, any], order_size: float) -> str:
        """Format pip value calculation result for display, scaled by order size"""
        if not result.get("success"):
            if "pip_in_base" in result:
                base_pips = result['pip_in_base'] * (order_size / 1.0)
                return f"Pip: {base_pips:.6f} {result['base_ccy']}/pip/{order_size:.0f}M"
            else:
                return "Pip: N/A"
        
        pip_usd = result["pip_in_usd"]
        scaled_pip_usd = pip_usd * (order_size / 1.0)
        base_ccy = result["base_ccy"]
        
        # Format based on size
        if scaled_pip_usd >= 1000:
            return f"Pip: {scaled_pip_usd:,.0f} USD/{order_size:.0f}M {base_ccy}"
        elif scaled_pip_usd >= 10:
            return f"Pip: {scaled_pip_usd:.2f} USD/{order_size:.0f}M {base_ccy}"
        else:
            return f"Pip: {scaled_pip_usd:.4f} USD/{order_size:.0f}M {base_ccy}"