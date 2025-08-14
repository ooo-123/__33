import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
import logging
import json

logger = logging.getLogger(__name__)


class ChartCacheManager:
    """Manages cached chart data for efficient loading and updates"""
    
    def __init__(self, cache_dir: str = "data/ccy_ticks"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.cache_dir / "metadata.json"
        self.metadata = self.load_metadata()
        
        # In-memory cache for recently accessed data (LRU-style)
        self.memory_cache = {}  # key: (ticker, interval) -> (data, timestamp)
        self.max_memory_cache_size = 10  # Keep last 10 accessed datasets in memory
        self.cache_ttl = 60  # Seconds to keep data in memory cache
    
    def load_metadata(self) -> Dict:
        """Load cache metadata"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load metadata: {e}")
        return {}
    
    def save_metadata(self):
        """Save cache metadata"""
        try:
            with open(self.metadata_file, 'w') as f:
                json.dump(self.metadata, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")
    
    def get_cache_info(self, ticker: str, interval: str) -> Dict:
        """Get cache information for a ticker/interval combination"""
        key = f"{ticker}_{interval}"
        return self.metadata.get(key, {})
    
    def update_cache_info(self, ticker: str, interval: str, info: Dict):
        """Update cache information"""
        key = f"{ticker}_{interval}"
        self.metadata[key] = info
        self.save_metadata()
    
    def get_latest_timestamp(self, ticker: str, interval: str) -> Optional[datetime]:
        """Get the latest timestamp in cache for incremental updates"""
        info = self.get_cache_info(ticker, interval)
        if 'latest_timestamp' in info:
            return pd.to_datetime(info['latest_timestamp'])
        
        # Check actual files if metadata doesn't have it
        ticker_clean = ticker.replace(' ', '_').replace('/', '_')
        ticker_dir = self.cache_dir / ticker_clean
        
        if not ticker_dir.exists():
            return None
        
        latest = None
        pattern = f"{interval}_*.csv"
        
        for cache_file in ticker_dir.glob(pattern):
            try:
                df = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True, nrows=1)
                if not df.empty:
                    file_latest = df.index[-1]
                    if latest is None or file_latest > latest:
                        latest = file_latest
            except Exception as e:
                logger.error(f"Error reading cache file {cache_file}: {e}")
        
        return latest
    
    def _check_memory_cache(self, ticker: str, interval: str) -> Optional[pd.DataFrame]:
        """Check if data is in memory cache and still fresh"""
        cache_key = (ticker, interval)
        if cache_key in self.memory_cache:
            data, timestamp = self.memory_cache[cache_key]
            if (datetime.now() - timestamp).total_seconds() < self.cache_ttl:
                logger.info(f"Using in-memory cache for {ticker} {interval}")
                return data.copy()  # Return a copy to prevent modifications
            else:
                # Cache expired, remove it
                del self.memory_cache[cache_key]
        return None
    
    def _update_memory_cache(self, ticker: str, interval: str, data: pd.DataFrame):
        """Update memory cache with new data"""
        cache_key = (ticker, interval)
        
        # LRU: Remove oldest if cache is full
        if len(self.memory_cache) >= self.max_memory_cache_size:
            if cache_key not in self.memory_cache:
                # Remove the oldest entry (first in dict)
                oldest_key = next(iter(self.memory_cache))
                del self.memory_cache[oldest_key]
        
        # Add to cache
        self.memory_cache[cache_key] = (data.copy(), datetime.now())
        logger.info(f"Updated memory cache for {ticker} {interval}")
    
    def clear_memory_cache(self, ticker: Optional[str] = None):
        """Clear memory cache for specific ticker or all"""
        if ticker:
            # Clear cache for specific ticker
            keys_to_remove = [key for key in self.memory_cache if key[0] == ticker]
            for key in keys_to_remove:
                del self.memory_cache[key]
            logger.info(f"Cleared memory cache for {ticker}")
        else:
            # Clear all memory cache
            self.memory_cache.clear()
            logger.info("Cleared all memory cache")
    
    def load_data_range(self, ticker: str, interval: str, start_date: datetime, 
                        end_date: datetime, max_points: Optional[int] = None) -> Optional[pd.DataFrame]:
        """Load data from cache for specified date range"""
        # Check memory cache first
        cached_data = self._check_memory_cache(ticker, interval)
        if cached_data is not None:
            # Filter to requested date range
            filtered = cached_data[(cached_data.index >= start_date) & (cached_data.index <= end_date)]
            if not filtered.empty:
                if max_points and len(filtered) > max_points:
                    return filtered.iloc[-max_points:]
                return filtered
        
        ticker_clean = ticker.replace(' ', '_').replace('/', '_')
        ticker_dir = self.cache_dir / ticker_clean
        
        if not ticker_dir.exists():
            return None
        
        all_data = []
        
        # Determine which files to load based on interval
        if interval in ['1M', '15M']:
            # Monthly files for intraday
            current = start_date.replace(day=1)
            while current <= end_date:
                date_str = current.strftime('%Y_%m')
                cache_file = ticker_dir / f"{interval}_{date_str}.csv"
                
                if cache_file.exists():
                    try:
                        df = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
                        all_data.append(df)
                    except Exception as e:
                        logger.error(f"Error reading {cache_file}: {e}")
                
                # Move to next month
                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1)
                else:
                    current = current.replace(month=current.month + 1)
        else:
            # Yearly files for daily
            for year in range(start_date.year, end_date.year + 1):
                date_str = str(year)
                cache_file = ticker_dir / f"{interval}_{date_str}.csv"
                
                if cache_file.exists():
                    try:
                        df = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
                        all_data.append(df)
                    except Exception as e:
                        logger.error(f"Error reading {cache_file}: {e}")
        
        if not all_data:
            return None
        
        # Combine all data
        combined_df = pd.concat(all_data)
        combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
        combined_df.sort_index(inplace=True)
        
        # Filter to requested date range
        combined_df = combined_df[(combined_df.index >= start_date) & (combined_df.index <= end_date)]
        
        # Limit points if requested
        if max_points and len(combined_df) > max_points:
            # Downsample to max_points
            step = len(combined_df) // max_points
            combined_df = combined_df.iloc[::step]
        
        # Update memory cache before returning
        if not combined_df.empty:
            self._update_memory_cache(ticker, interval, combined_df)
        
        return combined_df
    
    def get_latest_data(self, ticker: str, interval: str, num_points: int = 500) -> Optional[pd.DataFrame]:
        """Get the latest N data points from cache"""
        # Check memory cache first
        cached_data = self._check_memory_cache(ticker, interval)
        if cached_data is not None:
            if len(cached_data) > num_points:
                return cached_data.iloc[-num_points:]
            return cached_data
        
        ticker_clean = ticker.replace(' ', '_').replace('/', '_')
        ticker_dir = self.cache_dir / ticker_clean
        
        if not ticker_dir.exists():
            return None
        
        # Find the most recent file
        pattern = f"{interval}_*.csv"
        cache_files = sorted(ticker_dir.glob(pattern), reverse=True)
        
        if not cache_files:
            return None
        
        all_data = []
        points_loaded = 0
        
        for cache_file in cache_files:
            if points_loaded >= num_points:
                break
            
            try:
                df = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
                all_data.append(df)
                points_loaded += len(df)
            except Exception as e:
                logger.error(f"Error reading {cache_file}: {e}")
        
        if not all_data:
            return None
        
        # Combine and get latest points
        combined_df = pd.concat(all_data)
        combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
        combined_df.sort_index(inplace=True)
        
        result = combined_df.tail(num_points)
        
        # Update memory cache before returning
        if not result.empty:
            self._update_memory_cache(ticker, interval, result)
        
        return result
    
    def append_data(self, ticker: str, interval: str, new_data: pd.DataFrame):
        """Append new data to cache, handling duplicates"""
        if new_data.empty:
            return
        
        ticker_clean = ticker.replace(' ', '_').replace('/', '_')
        ticker_dir = self.cache_dir / ticker_clean
        ticker_dir.mkdir(exist_ok=True)
        
        # Group by month/year
        if interval in ['1M', '15M']:
            grouped = new_data.groupby(pd.Grouper(freq='ME'))  # Month End
        else:  # 1D
            grouped = new_data.groupby(pd.Grouper(freq='YE'))  # Year End
        
        for date_group, group_df in grouped:
            if group_df.empty:
                continue
            
            if interval in ['1M', '15M']:
                date_str = date_group.strftime('%Y_%m')
            else:  # 1D
                date_str = date_group.strftime('%Y')
            
            cache_file = ticker_dir / f"{interval}_{date_str}.csv"
            
            # Merge with existing data if file exists
            if cache_file.exists():
                try:
                    existing_df = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
                    # Combine and remove duplicates, keeping newest
                    combined_df = pd.concat([existing_df, group_df])
                    combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
                    combined_df.sort_index(inplace=True)
                    group_df = combined_df
                except Exception as e:
                    logger.error(f"Error merging with existing cache: {e}")
            
            # Save to file
            try:
                group_df.to_csv(cache_file)
                logger.info(f"Saved {len(group_df)} rows to {cache_file}")
            except Exception as e:
                logger.error(f"Error saving to cache: {e}")
        
        # Update metadata
        info = self.get_cache_info(ticker, interval)
        info['latest_timestamp'] = str(new_data.index[-1])
        info['total_points'] = len(new_data)
        info['last_updated'] = str(datetime.now())
        self.update_cache_info(ticker, interval, info)
    
    def clean_old_cache(self, days_to_keep: int = 30):
        """Clean cache files older than specified days"""
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        
        for ticker_dir in self.cache_dir.iterdir():
            if not ticker_dir.is_dir() or ticker_dir.name == 'metadata.json':
                continue
            
            for cache_file in ticker_dir.glob("*.csv"):
                try:
                    # Check file modification time
                    file_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
                    if file_time < cutoff_date:
                        cache_file.unlink()
                        logger.info(f"Deleted old cache file: {cache_file}")
                except Exception as e:
                    logger.error(f"Error cleaning cache file {cache_file}: {e}")
    
    def get_cache_summary(self) -> Dict:
        """Get summary of cached data"""
        summary = {}
        
        for ticker_dir in self.cache_dir.iterdir():
            if not ticker_dir.is_dir():
                continue
            
            ticker = ticker_dir.name.replace('_', '/')
            summary[ticker] = {}
            
            for cache_file in ticker_dir.glob("*.csv"):
                parts = cache_file.stem.split('_', 1)
                if len(parts) == 2:
                    interval = parts[0]
                    
                    if interval not in summary[ticker]:
                        summary[ticker][interval] = {
                            'files': 0,
                            'total_size_mb': 0,
                            'date_range': []
                        }
                    
                    summary[ticker][interval]['files'] += 1
                    summary[ticker][interval]['total_size_mb'] += cache_file.stat().st_size / (1024 * 1024)
                    summary[ticker][interval]['date_range'].append(parts[1])
        
        return summary
    
    def validate_cache(self, ticker: str, interval: str) -> bool:
        """Validate cache integrity for a ticker/interval"""
        ticker_clean = ticker.replace(' ', '_').replace('/', '_')
        ticker_dir = self.cache_dir / ticker_clean
        
        if not ticker_dir.exists():
            return False
        
        pattern = f"{interval}_*.csv"
        cache_files = list(ticker_dir.glob(pattern))
        
        if not cache_files:
            return False
        
        for cache_file in cache_files:
            try:
                df = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True, nrows=5)
                # Basic validation - check required columns
                required_cols = ['open', 'high', 'low', 'close', 'volume']
                if not all(col in df.columns for col in required_cols):
                    logger.error(f"Missing columns in {cache_file}")
                    return False
            except Exception as e:
                logger.error(f"Failed to validate {cache_file}: {e}")
                return False
        
        return True


if __name__ == "__main__":
    # Test the cache manager
    manager = ChartCacheManager()
    
    # Test data creation
    test_data = pd.DataFrame({
        'open': np.random.randn(100) + 100,
        'high': np.random.randn(100) + 101,
        'low': np.random.randn(100) + 99,
        'close': np.random.randn(100) + 100,
        'volume': np.random.randint(1000, 10000, 100)
    }, index=pd.date_range('2024-01-01', periods=100, freq='D'))
    
    # Test append
    manager.append_data('EURUSD', '1D', test_data)
    
    # Test load
    loaded = manager.get_latest_data('EURUSD', '1D', 50)
    if loaded is not None:
        print(f"Loaded {len(loaded)} data points")
    
    # Get summary
    summary = manager.get_cache_summary()
    print(f"Cache summary: {summary}")