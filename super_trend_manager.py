"""
Super Trend Manager - Centralized Super Trend calculation for all currency pairs
Fetches data and calculates trend for all major pairs in background
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

class SuperTrendManager:
    """Manages Super Trend calculation for all currency pairs"""
    
    def __init__(self, cache_dir: str = "data/super_trend"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Shared state for trend data
        self.manager = Manager()
        self.trend_data = self.manager.dict()
        self.update_in_progress = self.manager.Value('b', False)
        self.last_update = self.manager.Value('d', 0.0)
        
        # Load cached trend data
        self.load_cached_trend()
        
        # Process management
        self.update_process = None
        self.request_queue = mp.Queue()
        self.response_queue = mp.Queue()
    
    def load_cached_trend(self):
        """Load previously calculated trend from cache"""
        cache_file = self.cache_dir / "trend_state.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                    for pair, trend_info in data.items():
                        self.trend_data[pair] = trend_info
                    logger.info(f"Loaded cached trend for {len(data)} pairs")
            except Exception as e:
                logger.error(f"Error loading cached trend: {e}")
    
    def save_cached_trend(self):
        """Save current trend state to cache"""
        cache_file = self.cache_dir / "trend_state.json"
        try:
            # Convert manager dict to regular dict for JSON serialization
            data = dict(self.trend_data)
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved trend state for {len(data)} pairs")
        except Exception as e:
            logger.error(f"Error saving trend cache: {e}")
    
    def calculate_super_trend(self, df: pd.DataFrame, atr_period: int = 10, multiplier: float = 3.0) -> Dict:
        """
        Calculate Super Trend using the TIC library
        Returns trend info dict with trend direction
        """
        if df is None or df.empty or len(df) < atr_period * 2:
            return {'trend': 0, 'direction': 'NEUTRAL', 'error': 'Insufficient data'}
        
        try:
            # Import TIC for Super Trend calculation
            from technical_indicators_custom import TIC
            
            # Prepare dataframe with proper column names for TIC
            df_copy = df.copy()
            
            # Ensure we have the required columns with proper capitalization
            # TIC expects 'Open', 'High', 'Low', 'Close' (capitalized)
            column_mapping = {}
            for col in df_copy.columns:
                if col.lower() == 'open':
                    column_mapping[col] = 'Open'
                elif col.lower() == 'high':
                    column_mapping[col] = 'High'
                elif col.lower() == 'low':
                    column_mapping[col] = 'Low'
                elif col.lower() == 'close':
                    column_mapping[col] = 'Close'
                elif col.lower() == 'volume':
                    column_mapping[col] = 'Volume'
            
            df_copy = df_copy.rename(columns=column_mapping)
            
            # Calculate Super Trend using TIC
            df_with_st = TIC.add_super_trend(
                df_copy, 
                atr_period=atr_period, 
                multiplier=multiplier,
                inplace=False
            )
            
            # Get the latest trend direction
            # TIC adds 'SuperTrend_Direction' column with 1 for uptrend, -1 for downtrend
            latest_trend = df_with_st['SuperTrend_Direction'].iloc[-1]
            
            # Get the Super Trend line value
            st_value = df_with_st['SuperTrend_Line'].iloc[-1]
            current_close = df_with_st['Close'].iloc[-1]
            
            # Calculate distance from trend line (as percentage)
            distance = abs(current_close - st_value) / st_value * 100
            
            return {
                'trend': int(latest_trend),
                'direction': 'UP' if latest_trend == 1 else 'DOWN',
                'st_value': round(float(st_value), 5),
                'current_price': round(float(current_close), 5),
                'distance': round(float(distance), 2),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error calculating Super Trend: {e}")
            return {'trend': 0, 'direction': 'NEUTRAL', 'error': str(e)}
    
    def fetch_and_calculate_trend(self, pair: str, window_size: int = 150) -> Optional[Dict]:
        """Fetch data for a pair and calculate its Super Trend
        
        Args:
            pair: Currency pair (e.g., 'EURUSD')
            window_size: Number of 15M bars needed for calculation (default 150)
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
            # 150 bars * 15 minutes = 2250 minutes = 37.5 hours
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
                
                # Calculate trend
                trend_info = self.calculate_super_trend(df, atr_period=10, multiplier=3.0)
                trend_info['pair'] = pair
                trend_info['bars_used'] = len(df)
                return trend_info
            else:
                return {
                    'pair': pair,
                    'trend': 0,
                    'direction': 'NEUTRAL',
                    'error': 'No data available'
                }
                
        except Exception as e:
            logger.error(f"Error fetching/calculating trend for {pair}: {e}")
            return {
                'pair': pair,
                'trend': 0,
                'direction': 'NEUTRAL',
                'error': str(e)
            }
    
    def update_all_pairs(self, callback=None, window_size: int = 150):
        """Update Super Trend for all major pairs in background
        
        Args:
            callback: Function to call when complete (success_count, total_count)
            window_size: Number of 15M bars to use for calculation (default 150)
        """
        if self.update_in_progress.value:
            logger.info("Update already in progress")
            return False
        
        self.update_in_progress.value = True
        
        # Create a queue for results if callback is provided
        result_queue = mp.Queue() if callback else None
        
        # Start update process
        self.update_process = Process(
            target=SuperTrendManager._update_worker,
            args=(MAJOR_PAIRS, self.trend_data, self.update_in_progress, 
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
    def _update_worker(pairs: List[str], trend_data: dict, 
                      update_flag: mp.Value, window_size: int, 
                      cache_dir: Path, last_update: mp.Value, result_queue=None):
        """Worker process to update all pairs
        
        Args:
            pairs: List of currency pairs to update
            trend_data: Shared dictionary for storing results
            update_flag: Flag indicating update in progress
            window_size: Number of 15M bars to fetch
            cache_dir: Directory for cache files
            last_update: Shared value for last update time
            result_queue: Optional queue for sending results back
        """
        try:
            logger.info(f"Starting trend update for {len(pairs)} pairs with window_size={window_size}")
            
            # Create a temporary manager instance for the worker process
            from super_trend_manager import SuperTrendManager
            temp_manager = SuperTrendManager(cache_dir=str(cache_dir))
            
            # Fetch each pair with the specified window size
            results = []
            for pair in pairs:
                try:
                    result = temp_manager.fetch_and_calculate_trend(pair, window_size=window_size)
                    results.append(result)
                except Exception as e:
                    logger.error(f"Error updating {pair}: {e}")
                    results.append({'pair': pair, 'trend': 0, 'direction': 'NEUTRAL', 'error': str(e)})
            
            # Update shared trend data
            success_count = 0
            for result in results:
                if result and 'pair' in result:
                    pair = result['pair']
                    trend_data[pair] = {
                        'trend': result.get('trend', 0),
                        'direction': result.get('direction', 'NEUTRAL'),
                        'st_value': result.get('st_value', 0),
                        'distance': result.get('distance', 0),
                        'timestamp': result.get('timestamp', ''),
                        'error': result.get('error', '')
                    }
                    if not result.get('error'):
                        success_count += 1
                    
                    logger.info(f"Updated {pair}: Trend={result.get('direction')}, "
                              f"Distance={result.get('distance')}%")
            
            # Save to cache
            temp_manager.trend_data = trend_data
            temp_manager.save_cached_trend()
            
            logger.info(f"Trend update complete: {success_count}/{len(pairs)} successful")
            
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
    
    def get_trend(self, pair: str) -> Dict:
        """Get current trend for a specific pair"""
        if pair in self.trend_data:
            return dict(self.trend_data[pair])
        return {'trend': 0, 'direction': 'NEUTRAL', 'error': 'No data available'}
    
    def update_single_pair(self, pair: str, window_size: int = 150) -> Dict:
        """Update trend for a single pair immediately (not in background)
        
        Args:
            pair: Currency pair to update
            window_size: Number of 15M bars to use
            
        Returns:
            Trend data dictionary
        """
        logger.info(f"Updating single pair: {pair}")
        result = self.fetch_and_calculate_trend(pair, window_size)
        
        if result and not result.get('error'):
            # Update stored data
            self.trend_data[pair] = {
                'trend': result.get('trend', 0),
                'direction': result.get('direction', 'NEUTRAL'),
                'st_value': result.get('st_value', 0),
                'distance': result.get('distance', 0),
                'timestamp': result.get('timestamp', ''),
                'bars_used': result.get('bars_used', 0)
            }
            # Save to cache
            self.save_cached_trend()
        
        return result
    
    def get_all_trends(self) -> Dict[str, Dict]:
        """Get trend data for all pairs"""
        return dict(self.trend_data)
    
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

def get_super_trend_manager() -> SuperTrendManager:
    """Get or create the singleton SuperTrendManager instance"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = SuperTrendManager()
    return _manager_instance


if __name__ == "__main__":
    # Test the super trend manager
    import logging
    logging.basicConfig(level=logging.INFO)
    
    manager = get_super_trend_manager()
    
    print("Testing Super Trend Manager")
    print("=" * 60)
    
    # Test single pair calculation
    print("\nFetching and calculating trend for EURUSD...")
    result = manager.fetch_and_calculate_trend("EURUSD")
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
    
    print("\n\nAll trend data:")
    all_trends = manager.get_all_trends()
    for pair, data in all_trends.items():
        trend_text = data.get('direction', 'NEUTRAL')
        print(f"{pair:10} {trend_text:8} Distance: {data.get('distance', 0):.2f}%")