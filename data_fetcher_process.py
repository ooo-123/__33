import multiprocessing as mp
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import time
import json
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import logging
from queue import Empty

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Try to import Bloomberg API
try:
    import blpapi
    BLOOMBERG_AVAILABLE = True
except ImportError:
    BLOOMBERG_AVAILABLE = False
    logger.warning("Bloomberg API not available")

# Try to import xbbg as fallback
try:
    import xbbg as blp
    XBBG_AVAILABLE = True
except ImportError:
    XBBG_AVAILABLE = False
    logger.warning("xbbg not available")


class DataFetcherProcess:
    """Subprocess for fetching historical data from Bloomberg/xbbg"""
    
    def __init__(self, request_queue: mp.Queue, response_queue: mp.Queue, cache_dir: str = "data/ccy_ticks"):
        self.request_queue = request_queue
        self.response_queue = response_queue
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = None
        self.running = True
        
    def setup_bloomberg(self) -> bool:
        """Initialize Bloomberg session"""
        if not BLOOMBERG_AVAILABLE:
            return False
            
        try:
            sessionOptions = blpapi.SessionOptions()
            sessionOptions.setServerHost("localhost")
            sessionOptions.setServerPort(8194)
            self.session = blpapi.Session(sessionOptions)
            
            if not self.session.start():
                logger.error("Failed to start Bloomberg session")
                return False
                
            if not self.session.openService("//blp/refdata"):
                logger.error("Failed to open Bloomberg refdata service")
                return False
                
            logger.info("Bloomberg session initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Bloomberg setup failed: {e}")
            return False
    
    def fetch_bloomberg_intraday(self, ticker: str, interval: int, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """Fetch intraday data using Bloomberg API"""
        if not self.session:
            return None
            
        try:
            refDataService = self.session.getService("//blp/refdata")
            request = refDataService.createRequest("IntradayBarRequest")
            
            request.set("security", ticker)
            request.set("eventType", "TRADE")
            request.set("interval", interval)  # in minutes
            
            request.set("startDateTime", start_date.strftime("%Y-%m-%dT%H:%M:%S"))
            request.set("endDateTime", end_date.strftime("%Y-%m-%dT%H:%M:%S"))
            
            self.session.sendRequest(request)
            
            data = []
            while True:
                event = self.session.nextEvent(500)
                
                if event.eventType() == blpapi.Event.RESPONSE or event.eventType() == blpapi.Event.PARTIAL_RESPONSE:
                    for msg in event:
                        barData = msg.getElement("barData")
                        barTickDataArray = barData.getElement("barTickData")
                        
                        for i in range(barTickDataArray.numValues()):
                            bar = barTickDataArray.getValue(i)
                            data.append({
                                'timestamp': bar.getElementAsDatetime("time"),
                                'open': bar.getElementAsFloat("open"),
                                'high': bar.getElementAsFloat("high"),
                                'low': bar.getElementAsFloat("low"),
                                'close': bar.getElementAsFloat("close"),
                                'volume': bar.getElementAsInteger("volume"),
                                'numEvents': bar.getElementAsInteger("numEvents")
                            })
                
                if event.eventType() == blpapi.Event.RESPONSE:
                    break
                    
            if data:
                df = pd.DataFrame(data)
                df.set_index('timestamp', inplace=True)
                return df
            return None
            
        except Exception as e:
            logger.error(f"Bloomberg intraday fetch error: {e}")
            return None
    
    def fetch_bloomberg_daily(self, ticker: str, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """Fetch daily data using Bloomberg API"""
        if not self.session:
            return None
            
        try:
            refDataService = self.session.getService("//blp/refdata")
            request = refDataService.createRequest("HistoricalDataRequest")
            
            request.getElement("securities").appendValue(ticker)
            request.getElement("fields").appendValue("PX_OPEN")
            request.getElement("fields").appendValue("PX_HIGH")
            request.getElement("fields").appendValue("PX_LOW")
            request.getElement("fields").appendValue("PX_LAST")
            request.getElement("fields").appendValue("VOLUME")
            
            request.set("periodicitySelection", "DAILY")
            request.set("startDate", start_date.strftime("%Y%m%d"))
            request.set("endDate", end_date.strftime("%Y%m%d"))
            
            self.session.sendRequest(request)
            
            data = []
            while True:
                event = self.session.nextEvent(500)
                
                if event.eventType() == blpapi.Event.RESPONSE or event.eventType() == blpapi.Event.PARTIAL_RESPONSE:
                    for msg in event:
                        securityData = msg.getElement("securityData")
                        fieldData = securityData.getElement("fieldData")
                        
                        for i in range(fieldData.numValues()):
                            element = fieldData.getValue(i)
                            data.append({
                                'timestamp': element.getElementAsDatetime("date"),
                                'open': element.getElementAsFloat("PX_OPEN"),
                                'high': element.getElementAsFloat("PX_HIGH"),
                                'low': element.getElementAsFloat("PX_LOW"),
                                'close': element.getElementAsFloat("PX_LAST"),
                                'volume': element.getElementAsFloat("VOLUME") if element.hasElement("VOLUME") else 0
                            })
                
                if event.eventType() == blpapi.Event.RESPONSE:
                    break
                    
            if data:
                df = pd.DataFrame(data)
                df.set_index('timestamp', inplace=True)
                return df
            return None
            
        except Exception as e:
            logger.error(f"Bloomberg daily fetch error: {e}")
            return None
    
    def fetch_xbbg_data(self, ticker: str, interval: str, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """Fetch data using xbbg library as fallback"""
        if not XBBG_AVAILABLE:
            return None
            
        try:
            if interval in ['1M', '15M']:
                # Use intraday bar data
                interval_map = {'1M': 1, '15M': 15}
                df = blp.bdib(
                    ticker=ticker,
                    dt=end_date.strftime('%Y-%m-%d'),
                    session=f'allday',
                    typ='TRADE',
                    interval=interval_map[interval]
                )
                
                # Filter to our date range
                if df is not None and not df.empty:
                    df = df[(df.index >= start_date) & (df.index <= end_date)]
                    df.columns = ['open', 'high', 'low', 'close', 'volume', 'numEvents', 'value']
                    df = df[['open', 'high', 'low', 'close', 'volume']]
                    return df
                    
            else:  # Daily data
                df = blp.bdh(
                    tickers=ticker,
                    flds=['PX_OPEN', 'PX_HIGH', 'PX_LOW', 'PX_LAST', 'VOLUME'],
                    start_date=start_date.strftime('%Y-%m-%d'),
                    end_date=end_date.strftime('%Y-%m-%d')
                )
                
                if df is not None and not df.empty:
                    df.columns = ['open', 'high', 'low', 'close', 'volume']
                    return df
                    
        except Exception as e:
            logger.error(f"xbbg fetch error: {e}")
            
        return None
    
    def generate_simulated_data(self, ticker: str, interval: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """Generate simulated data for testing when Bloomberg/xbbg not available"""
        logger.info(f"Generating simulated data for {ticker} {interval}")
        
        # Determine frequency and number of periods
        if interval == '1M':
            freq = 'min'  # minutely
            periods = int((end_date - start_date).total_seconds() / 60)
        elif interval == '15M':
            freq = '15min'
            periods = int((end_date - start_date).total_seconds() / (60 * 15))
        else:  # 1D
            freq = 'D'
            periods = (end_date - start_date).days
            
        # Create date range
        dates = pd.date_range(start=start_date, end=end_date, freq=freq)[:periods]
        
        # Generate random walk prices
        np.random.seed(42)  # For reproducibility
        returns = np.random.normal(0.0001, 0.002, len(dates))
        
        # Base price based on currency pair
        base_prices = {
            'EURUSD': 1.08,
            'GBPUSD': 1.27,
            'USDJPY': 150.0,
            'AUDUSD': 0.65,
            'USDCAD': 1.35,
            'USDCHF': 0.88,
            'NZDUSD': 0.59
        }
        
        # Extract base currency pair from ticker
        base_pair = ticker.replace(' Curncy', '').replace(' BGN Curncy', '')
        base_price = base_prices.get(base_pair, 1.0)
        
        close_prices = base_price * np.exp(np.cumsum(returns))
        
        # Generate OHLC from close
        data = []
        for i, (date, close) in enumerate(zip(dates, close_prices)):
            volatility = np.random.uniform(0.0005, 0.002)
            high = close * (1 + volatility)
            low = close * (1 - volatility)
            open_price = close_prices[i-1] if i > 0 else close * (1 + np.random.uniform(-0.001, 0.001))
            
            data.append({
                'timestamp': date,
                'open': open_price,
                'high': high,
                'low': low,
                'close': close,
                'volume': np.random.randint(1000, 10000)
            })
            
        df = pd.DataFrame(data)
        df.set_index('timestamp', inplace=True)
        return df
    
    def get_cache_path(self, ticker: str, interval: str, date_str: str) -> Path:
        """Get cache file path for given parameters"""
        ticker_clean = ticker.replace(' ', '_').replace('/', '_')
        ticker_dir = self.cache_dir / ticker_clean
        ticker_dir.mkdir(exist_ok=True)
        
        filename = f"{interval}_{date_str}.csv"
        return ticker_dir / filename
    
    def load_from_cache(self, ticker: str, interval: str, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """Load data from cache if available"""
        try:
            # Clean ticker for consistent file naming
            clean_ticker = ticker.replace(' BGN Curncy', '').replace(' Curncy', '')
            
            # Determine cache file based on interval
            if interval in ['1M', '15M']:
                # Monthly files for intraday
                date_str = start_date.strftime('%Y_%m')
            else:
                # Yearly files for daily
                date_str = start_date.strftime('%Y')
                
            cache_path = self.get_cache_path(clean_ticker, interval, date_str)
            
            if cache_path.exists():
                # Try to read with timestamp as index
                try:
                    df = pd.read_csv(cache_path, index_col='timestamp', parse_dates=True)
                except (KeyError, ValueError):
                    # If timestamp column doesn't exist, try first column as index
                    df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
                
                # Filter to requested date range
                df = df[(df.index >= start_date) & (df.index <= end_date)]
                
                if not df.empty:
                    logger.info(f"Loaded {len(df)} rows from cache: {cache_path}")
                    return df
                    
        except Exception as e:
            logger.error(f"Cache load error: {e}")
            
        return None
    
    def save_to_cache(self, df: pd.DataFrame, ticker: str, interval: str):
        """Save data to cache"""
        try:
            if df.empty:
                return
                
            # Group by month for intraday, year for daily
            if interval in ['1M', '15M']:
                grouped = df.groupby(pd.Grouper(freq='ME'))  # Month End
            else:
                grouped = df.groupby(pd.Grouper(freq='YE'))  # Year End
                
            for date_group, group_df in grouped:
                if group_df.empty:
                    continue
                    
                if interval in ['1M', '15M']:
                    date_str = date_group.strftime('%Y_%m')
                else:
                    date_str = date_group.strftime('%Y')
                    
                cache_path = self.get_cache_path(ticker, interval, date_str)
                
                # Merge with existing cache if present
                if cache_path.exists():
                    existing_df = pd.read_csv(cache_path, index_col='timestamp', parse_dates=True)
                    # Combine and remove duplicates, keeping newest data
                    combined_df = pd.concat([existing_df, group_df])
                    combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
                    combined_df.sort_index(inplace=True)
                    group_df = combined_df
                    
                group_df.to_csv(cache_path)
                logger.info(f"Saved {len(group_df)} rows to cache: {cache_path}")
                
        except Exception as e:
            logger.error(f"Cache save error: {e}")
    
    def fetch_data(self, ticker: str, interval: str, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """Main method to fetch data with fallback logic optimized for Bloomberg"""
        
        # Standardize ticker format early
        bloomberg_ticker = f"{ticker} BGN Curncy" if not ticker.endswith('Curncy') else ticker
        clean_ticker = ticker.replace(' BGN Curncy', '').replace(' Curncy', '')
        
        # Smart cache strategy based on interval and time range
        time_range = end_date - start_date
        use_cache = True
        
        if interval == '1M':
            # For 1-minute data, only use cache if data is older than 5 minutes
            if (datetime.now() - end_date) < timedelta(minutes=5):
                use_cache = False
                logger.info(f"Fetching fresh 1M data for {clean_ticker} (recent data requested)")
        elif interval == '15M':
            # For 15-minute data, only use cache if data is older than 15 minutes
            if (datetime.now() - end_date) < timedelta(minutes=15):
                use_cache = False
                logger.info(f"Fetching fresh 15M data for {clean_ticker} (recent data requested)")
        elif interval == '1D':
            # For daily data, use cache if we have today's close or it's during trading hours
            current_hour = datetime.now().hour
            if current_hour >= 17:  # After market close (5 PM)
                use_cache = True
            else:
                # During trading hours, fetch fresh if requesting today's data
                if end_date.date() == datetime.now().date():
                    use_cache = False
                    logger.info(f"Fetching fresh 1D data for {clean_ticker} (today's data requested)")
        
        # Try cache first if appropriate
        if use_cache:
            cached_data = self.load_from_cache(clean_ticker, interval, start_date, end_date)
            if cached_data is not None and len(cached_data) > 0:
                # Validate cache completeness
                if interval == '1D':
                    expected_days = (end_date - start_date).days
                    if len(cached_data) >= expected_days * 0.5:  # Allow for weekends/holidays
                        logger.info(f"Using cached data for {clean_ticker} {interval}")
                        return cached_data
                elif interval in ['15M', '1M']:
                    # For intraday, check if cache covers the requested range
                    if cached_data.index[0] <= start_date and cached_data.index[-1] >= (end_date - timedelta(hours=1)):
                        logger.info(f"Using cached data for {clean_ticker} {interval}")
                        return cached_data
        
        df = None
        
        # Try Bloomberg/xbbg through centralized manager first
        try:
            from bloomberg_data_manager import get_bloomberg_manager
            bloomberg_mgr = get_bloomberg_manager()
            df = bloomberg_mgr.fetch_data(clean_ticker, interval, start_date, end_date)
            if df is not None:
                logger.info(f"Successfully fetched {len(df)} bars via Bloomberg manager")
        except ImportError:
            logger.warning("Bloomberg manager not available, using direct methods")
        except Exception as e:
            logger.error(f"Bloomberg manager error: {e}")
        
        # Fallback to direct Bloomberg if manager failed
        if df is None and BLOOMBERG_AVAILABLE and self.session:
            logger.info(f"Attempting direct Bloomberg fetch for {bloomberg_ticker}")
            if interval in ['1M', '15M']:
                interval_minutes = {'1M': 1, '15M': 15}[interval]
                df = self.fetch_bloomberg_intraday(bloomberg_ticker, interval_minutes, start_date, end_date)
            else:  # 1D
                df = self.fetch_bloomberg_daily(bloomberg_ticker, start_date, end_date)
        
        # Fallback to direct xbbg
        if df is None and XBBG_AVAILABLE:
            logger.info(f"Attempting direct xbbg fetch for {bloomberg_ticker}")
            df = self.fetch_xbbg_data(bloomberg_ticker, interval, start_date, end_date)
        
        # Final fallback to simulated data
        if df is None:
            logger.info(f"No Bloomberg data available, using simulated data for {clean_ticker}")
            df = self.generate_simulated_data(bloomberg_ticker, interval, start_date, end_date)
        
        # Save to cache using clean ticker for consistent file naming
        if df is not None:
            self.save_to_cache(df, clean_ticker, interval)
        
        return df
    
    def run(self):
        """Main process loop"""
        logger.info("Data fetcher process started")
        
        # Setup Bloomberg if available
        if BLOOMBERG_AVAILABLE:
            self.setup_bloomberg()
        
        while self.running:
            try:
                # Wait for request with timeout
                request = self.request_queue.get(timeout=1)
                
                if request is None or request.get('command') == 'stop':
                    logger.info("Received stop command")
                    break
                
                if request.get('command') == 'fetch':
                    ticker = request['ticker']
                    interval = request['interval']
                    start_date = pd.to_datetime(request['start_date'])
                    end_date = pd.to_datetime(request['end_date'])
                    
                    logger.info(f"Fetching {ticker} {interval} from {start_date} to {end_date}")
                    
                    # Fetch data
                    df = self.fetch_data(ticker, interval, start_date, end_date)
                    
                    # Send response
                    if df is not None:
                        # Convert to dict for queue transfer
                        data_dict = {
                            'success': True,
                            'ticker': ticker,
                            'interval': interval,
                            'data': df.to_dict(),
                            'index': df.index.tolist()
                        }
                    else:
                        data_dict = {
                            'success': False,
                            'ticker': ticker,
                            'interval': interval,
                            'error': 'Failed to fetch data'
                        }
                    
                    self.response_queue.put(data_dict)
                    
            except Empty:
                continue
            except Exception as e:
                logger.error(f"Process error: {e}")
                self.response_queue.put({
                    'success': False,
                    'error': str(e)
                })
        
        # Cleanup
        if self.session:
            self.session.stop()
        
        logger.info("Data fetcher process stopped")


def start_data_fetcher_process(request_queue: mp.Queue, response_queue: mp.Queue):
    """Entry point for subprocess"""
    fetcher = DataFetcherProcess(request_queue, response_queue)
    fetcher.run()


def fetch_multiple_pairs(pairs: List[str], interval: str = '15M', 
                        bars: int = 300) -> Dict[str, pd.DataFrame]:
    """
    Fetch data for multiple currency pairs efficiently
    Used by market bias manager for batch updates
    
    Args:
        pairs: List of currency pairs (e.g., ['EURUSD', 'GBPUSD'])
        interval: Time interval ('1M', '15M', '1H', '1D')
        bars: Number of bars to fetch
        
    Returns:
        Dictionary mapping pair to DataFrame
    """
    from datetime import datetime, timedelta
    
    # Calculate date range based on interval and bars
    end_date = datetime.now()
    if interval == '1M':
        start_date = end_date - timedelta(minutes=bars)
    elif interval == '15M':
        start_date = end_date - timedelta(minutes=bars * 15)
    elif interval == '1H':
        start_date = end_date - timedelta(hours=bars)
    else:  # 1D
        start_date = end_date - timedelta(days=bars)
    
    # Create a fetcher instance
    fetcher = DataFetcherProcess(mp.Queue(), mp.Queue())
    
    # Try to setup Bloomberg if available
    if BLOOMBERG_AVAILABLE:
        fetcher.setup_bloomberg()
    
    results = {}
    for pair in pairs:
        try:
            df = fetcher.fetch_data(pair, interval, start_date, end_date)
            if df is not None and not df.empty:
                results[pair] = df
                logger.info(f"Fetched {len(df)} bars for {pair}")
            else:
                logger.warning(f"No data fetched for {pair}")
        except Exception as e:
            logger.error(f"Error fetching {pair}: {e}")
    
    # Clean up Bloomberg session if opened
    if fetcher.session:
        try:
            fetcher.session.stop()
        except:
            pass
    
    return results


if __name__ == "__main__":
    # Test the data fetcher
    request_q = mp.Queue()
    response_q = mp.Queue()
    
    # Start process
    process = mp.Process(target=start_data_fetcher_process, args=(request_q, response_q))
    process.start()
    
    try:
        # Test request
        request_q.put({
            'command': 'fetch',
            'ticker': 'EURUSD',
            'interval': '1D',
            'start_date': (datetime.now() - timedelta(days=30)).isoformat(),
            'end_date': datetime.now().isoformat()
        })
        
        # Wait for response
        response = response_q.get(timeout=10)
        print(f"Response: {response.get('success')}")
        if response.get('success'):
            print(f"Data points: {len(response.get('index', []))}")
        
    finally:
        # Stop process
        request_q.put({'command': 'stop'})
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()