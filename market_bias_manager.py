"""
Market Bias Manager - Centralized market bias calculation for all currency pairs
Fetches data and calculates bias for all major pairs in background
"""

import multiprocessing as mp
from multiprocessing import Process, Queue, Manager
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import json
import logging
from typing import Dict, Optional, List, Tuple
import time
from queue import Empty

logger = logging.getLogger(__name__)

# Major currency pairs to track
MAJOR_PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", 
    "USDCAD", "USDCHF", "NZDUSD", "EURJPY",
    "GBPJPY", "AUDJPY", "EURGBP", "EURAUD",
    "GBPAUD", "EURCHF", "AUDNZD", "NZDJPY"
]

class MarketBiasManager:
    """Manages market bias calculation for all currency pairs"""
    
    def __init__(self, cache_dir: str = "data/market_bias"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Shared state for bias data
        self.manager = Manager()
        self.bias_data = self.manager.dict()
        self.update_in_progress = self.manager.Value('b', False)
        self.last_update = self.manager.Value('d', 0.0)
        
        # Load cached bias data
        self.load_cached_bias()
        
        # Process management
        self.update_process = None
        self.request_queue = mp.Queue()
        self.response_queue = mp.Queue()
    
    def load_cached_bias(self):
        """Load previously calculated bias from cache"""
        cache_file = self.cache_dir / "bias_state.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                    for pair, bias_info in data.items():
                        self.bias_data[pair] = bias_info
                    logger.info(f"Loaded cached bias for {len(data)} pairs")
            except Exception as e:
                logger.error(f"Error loading cached bias: {e}")
    
    def save_cached_bias(self):
        """Save current bias state to cache"""
        cache_file = self.cache_dir / "bias_state.json"
        try:
            # Convert manager dict to regular dict for JSON serialization
            data = dict(self.bias_data)
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved bias state for {len(data)} pairs")
        except Exception as e:
            logger.error(f"Error saving bias cache: {e}")
    
    def calculate_market_bias(self, df: pd.DataFrame, ha_len: int = 300, ha_len2: int = 30) -> Dict:
        """
        Calculate market bias using Heikin-Ashi method
        Returns bias info dict with bias direction and strength
        """
        if df is None or df.empty or len(df) < ha_len:
            return {'bias': 0, 'strength': 0, 'error': 'Insufficient data'}
        
        try:
            # Fast EMA calculation
            def fast_ema(values, period):
                alpha = 2.0 / (period + 1)
                ema = np.empty_like(values)
                ema[0] = values[0]
                for i in range(1, len(values)):
                    ema[i] = alpha * values[i] + (1 - alpha) * ema[i-1]
                return ema
            
            # Prepare data
            open_vals = df['open'].values.astype(np.float64)
            high_vals = df['high'].values.astype(np.float64)
            low_vals = df['low'].values.astype(np.float64)
            close_vals = df['close'].values.astype(np.float64)
            
            # Initial Data Smoothing
            ha_ema_open = fast_ema(open_vals, ha_len)
            ha_ema_close = fast_ema(close_vals, ha_len)
            ha_ema_high = fast_ema(high_vals, ha_len)
            ha_ema_low = fast_ema(low_vals, ha_len)
            
            # Heikin-Ashi Style Candle Construction
            ha_close_val = (ha_ema_open + ha_ema_high + ha_ema_low + ha_ema_close) / 4
            
            n = len(df)
            ha_open_val = np.empty(n, dtype=np.float64)
            ha_open_val[0] = (ha_ema_open[0] + ha_ema_close[0]) / 2
            
            for i in range(1, n):
                ha_open_val[i] = (ha_open_val[i-1] + ha_close_val[i-1]) / 2
            
            # Secondary Smoothing
            mb_o2 = fast_ema(ha_open_val, ha_len2)
            mb_c2 = fast_ema(ha_close_val, ha_len2)
            
            # Get latest bias
            latest_bias = 1 if mb_c2[-1] > mb_o2[-1] else -1
            
            # Calculate trend strength
            bias_diff = abs(mb_c2[-1] - mb_o2[-1]) / mb_o2[-1] * 100
            
            return {
                'bias': latest_bias,
                'strength': round(bias_diff, 2),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error calculating market bias: {e}")
            return {'bias': 0, 'strength': 0, 'error': str(e)}
    
    def fetch_and_calculate_bias(self, pair: str, window_size: int = 300) -> Optional[Dict]:
        """Fetch data for a pair and calculate its market bias
        
        Args:
            pair: Currency pair (e.g., 'EURUSD')
            window_size: Number of 15M bars needed for calculation (default 300)
        """
        try:
            # Import data fetcher
            from data_fetcher_process import DataFetcherProcess
            
            # Create fetcher instance
            fetcher = DataFetcherProcess(
                request_queue=mp.Queue(),
                response_queue=mp.Queue()
            )
            
            # Calculate date range for 15M data
            # We need exactly window_size bars plus small buffer
            # 300 bars * 15 minutes = 4500 minutes = 75 hours
            end_date = datetime.now()
            bars_to_fetch = window_size + 5  # Small buffer for safety
            minutes_needed = bars_to_fetch * 15
            start_date = end_date - timedelta(minutes=minutes_needed)
            
            logger.info(f"Fetching last {bars_to_fetch} bars of 15M data for {pair}")
            
            # Fetch 15M data
            df = fetcher.fetch_data(
                ticker=pair,
                interval='15M',
                start_date=start_date,
                end_date=end_date
            )
            
            if df is not None and len(df) > 0:
                # Trim to exactly window_size bars (use most recent)
                if len(df) > window_size:
                    df = df.iloc[-window_size:]
                    logger.info(f"Trimmed {pair} data to last {window_size} bars")
                
                # Calculate bias using exact window
                bias_info = self.calculate_market_bias(df, ha_len=window_size, ha_len2=30)
                bias_info['pair'] = pair
                bias_info['bars_used'] = len(df)
                return bias_info
            else:
                return {
                    'pair': pair,
                    'bias': 0,
                    'strength': 0,
                    'error': 'No data available'
                }
                
        except Exception as e:
            logger.error(f"Error fetching/calculating bias for {pair}: {e}")
            return {
                'pair': pair,
                'bias': 0,
                'strength': 0,
                'error': str(e)
            }
    
    def update_all_pairs(self, callback=None, window_size: int = 300):
        """Update market bias for all major pairs in background
        
        Args:
            callback: Function to call when complete (success_count, total_count)
            window_size: Number of 15M bars to use for calculation (default 300)
        """
        if self.update_in_progress.value:
            logger.info("Update already in progress")
            return False
        
        self.update_in_progress.value = True
        
        # Create a queue for results if callback is provided
        result_queue = mp.Queue() if callback else None
        
        # Start update process
        self.update_process = Process(
            target=MarketBiasManager._update_worker,
            args=(MAJOR_PAIRS, self.bias_data, self.update_in_progress, 
                  window_size, self.cache_dir, self.last_update, result_queue)
        )
        self.update_process.start()
        
        # If callback provided, start a thread to wait for results
        if callback and result_queue:
            import threading
            def wait_for_result():
                try:
                    result = result_queue.get(timeout=300)  # 5 minute timeout
                    if result:
                        callback(result['success_count'], result['total_count'])
                except:
                    pass
            
            thread = threading.Thread(target=wait_for_result, daemon=True)
            thread.start()
        
        return True
    
    @staticmethod
    def _update_worker(pairs: List[str], bias_data: dict, 
                      update_flag: mp.Value, window_size: int, 
                      cache_dir: Path, last_update: mp.Value, result_queue=None):
        """Worker process to update all pairs
        
        Args:
            pairs: List of currency pairs to update
            bias_data: Shared dictionary for storing results
            update_flag: Flag indicating update in progress
            window_size: Number of 15M bars to fetch
            cache_dir: Directory for cache files
            last_update: Shared value for last update time
            result_queue: Optional queue for sending results back
        """
        try:
            logger.info(f"Starting bias update for {len(pairs)} pairs with window_size={window_size}")
            
            # Create a temporary manager instance for the worker process
            from market_bias_manager import MarketBiasManager
            temp_manager = MarketBiasManager(cache_dir=str(cache_dir))
            
            # Fetch each pair with the specified window size
            results = []
            for pair in pairs:
                try:
                    result = temp_manager.fetch_and_calculate_bias(pair, window_size=window_size)
                    results.append(result)
                except Exception as e:
                    logger.error(f"Error updating {pair}: {e}")
                    results.append({'pair': pair, 'bias': 0, 'strength': 0, 'error': str(e)})
            
            # Update shared bias data
            success_count = 0
            for result in results:
                if result and 'pair' in result:
                    pair = result['pair']
                    bias_data[pair] = {
                        'bias': result.get('bias', 0),
                        'strength': result.get('strength', 0),
                        'timestamp': result.get('timestamp', ''),
                        'error': result.get('error', '')
                    }
                    if not result.get('error'):
                        success_count += 1
                    
                    logger.info(f"Updated {pair}: Bias={result.get('bias')}, "
                              f"Strength={result.get('strength')}%")
            
            # Save to cache
            temp_manager.bias_data = bias_data
            temp_manager.save_cached_bias()
            
            logger.info(f"Bias update complete: {success_count}/{len(pairs)} successful")
            
            # Send result via queue if provided
            if result_queue:
                result_queue.put({
                    'success_count': success_count,
                    'total_count': len(pairs)
                })
                
        except Exception as e:
            logger.error(f"Error in update worker: {e}")
        finally:
            update_flag.value = False
            last_update.value = time.time()
    
    def get_bias(self, pair: str) -> Dict:
        """Get current bias for a specific pair"""
        if pair in self.bias_data:
            return dict(self.bias_data[pair])
        return {'bias': 0, 'strength': 0, 'error': 'No data available'}
    
    def update_single_pair(self, pair: str, window_size: int = 300) -> Dict:
        """Update bias for a single pair immediately (not in background)
        
        Args:
            pair: Currency pair to update
            window_size: Number of 15M bars to use
            
        Returns:
            Bias data dictionary
        """
        logger.info(f"Updating single pair: {pair}")
        result = self.fetch_and_calculate_bias(pair, window_size)
        
        if result and not result.get('error'):
            # Update stored data
            self.bias_data[pair] = {
                'bias': result.get('bias', 0),
                'strength': result.get('strength', 0),
                'timestamp': result.get('timestamp', ''),
                'bars_used': result.get('bars_used', 0)
            }
            # Save to cache
            self.save_cached_bias()
        
        return result
    
    def get_all_bias(self) -> Dict[str, Dict]:
        """Get bias data for all pairs"""
        return dict(self.bias_data)
    
    def is_updating(self) -> bool:
        """Check if update is in progress"""
        return self.update_in_progress.value
    
    def get_last_update_time(self) -> datetime:
        """Get timestamp of last update"""
        if self.last_update.value > 0:
            return datetime.fromtimestamp(self.last_update.value)
        return None
    
    def stop(self):
        """Stop any running processes"""
        if self.update_process and self.update_process.is_alive():
            self.update_process.terminate()
            self.update_process.join(timeout=5)


# Singleton instance
_manager_instance = None

def get_market_bias_manager() -> MarketBiasManager:
    """Get or create the singleton MarketBiasManager instance"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = MarketBiasManager()
    return _manager_instance


if __name__ == "__main__":
    # Test the market bias manager
    import logging
    logging.basicConfig(level=logging.INFO)
    
    manager = get_market_bias_manager()
    
    print("Testing Market Bias Manager")
    print("=" * 60)
    
    # Test single pair calculation
    print("\nFetching and calculating bias for EURUSD...")
    result = manager.fetch_and_calculate_bias("EURUSD")
    print(f"Result: {result}")
    
    # Test batch update
    print("\nUpdating all major pairs (this will take a moment)...")
    
    def update_callback(success, total):
        print(f"Update complete: {success}/{total} pairs updated successfully")
    
    manager.update_all_pairs(callback=update_callback)
    
    # Wait for update to complete
    import time
    while manager.is_updating():
        print(".", end="", flush=True)
        time.sleep(1)
    
    print("\n\nAll bias data:")
    all_bias = manager.get_all_bias()
    for pair, data in all_bias.items():
        bias_text = "BULLISH" if data.get('bias') == 1 else "BEARISH"
        print(f"{pair:10} {bias_text:8} Strength: {data.get('strength', 0):.2f}%")