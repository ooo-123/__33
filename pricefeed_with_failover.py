"""
Enhanced WebSocket-based price feed with automatic failover to simulated data.
When WebSocket connection fails, automatically switches to built-in simulation.

Usage:
    feed = PriceFeedWithFailover(pricing_obj, url="ws://localhost:8765")
    gen = feed.run()          # Automatically handles failover
    next(gen)                 # Always yields bid_offer dict (from WebSocket or simulation)
"""
import asyncio
import json
import websockets
import threading
import queue
import time
import collections
import numpy as np
import random
from fx import simulated_data


class PriceFeedWithFailover:
    def __init__(self, pricing_obj, url="ws://localhost:8765", pairs=None, 
                 connection_timeout=5.0, max_reconnect_attempts=3):
        """
        Initialize WebSocket-based price feed with failover to simulated data.
        
        Args:
            pricing_obj: The pricing object with bid_offer array
            url: WebSocket server URL
            pairs: List of currency pairs to subscribe to
            connection_timeout: Timeout for initial connection attempt
            max_reconnect_attempts: Maximum reconnection attempts before failover
        """
        self.url = url
        self.pricing_obj = pricing_obj
        self.pairs = pairs or [p for p in self.pricing_obj.ccys if p != 'CROSS']
        self.q = queue.Queue(maxsize=10000)  # Back-pressure protection
        self._stop = False
        self._connected = False
        self._last_update_time = {}
        self._update_counts = {}
        self._connection_timeout = connection_timeout
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_attempts = 0
        self._use_simulation = False
        self._simulation_gen = None
        self._last_connection_attempt = 0
        self._reconnect_interval = 30.0  # Try to reconnect every 30 seconds
        
        # Initialize update tracking
        for pair in self.pairs:
            self._last_update_time[pair] = 0
            self._update_counts[pair] = 0
            
        # Create simulated data instance for failover
        self.sim_data = simulated_data(self.pricing_obj)

    # ---------------- WebSocket connection handling ----------------
    async def _consumer(self):
        """Consume price updates from WebSocket server with failover logic."""
        while not self._stop:
            # Check if we should attempt reconnection
            if self._use_simulation:
                current_time = time.time()
                if current_time - self._last_connection_attempt > self._reconnect_interval:
                    print(f"🔄 Attempting to reconnect to WebSocket...")
                    self._reconnect_attempts = 0
                    self._use_simulation = False
                    self._last_connection_attempt = current_time
                else:
                    await asyncio.sleep(1)
                    continue
            
            try:
                print(f"🔌 Connecting to price feed at {self.url}...")
                async with websockets.connect(self.url, ping_interval=20) as ws:
                    self._connected = True
                    self._reconnect_attempts = 0
                    if self._use_simulation:
                        print("✅ WebSocket reconnected! Switching from simulation to live feed")
                        self._use_simulation = False
                    else:
                        print("✅ Connected to price feed")
                    
                    async for msg in ws:
                        if self._stop:
                            break
                            
                        try:
                            data = json.loads(msg)
                            
                            # Handle status messages (initial connection info)
                            if data.get("type") == "status":
                                print(f"📊 Server info: {len(data['symbols'])} pairs available")
                                print(f"⚡ Playback speed: {data['playback_speed']}x")
                                continue
                            
                            # Handle tick data messages
                            pair = data["ccy"]  # Real API uses "ccy" not "pair"
                            
                            if pair not in self.pairs:  # Ignore unwanted pairs
                                continue
                            
                            # Update bid_offer array using real API format
                            self.pricing_obj.bid_offer[pair][0] = data["bid"]
                            self.pricing_obj.bid_offer[pair][1] = data["offer"]  # Real API uses "offer" not "ask"
                            # For high/low, we'll use the current bid/offer as placeholders since they're not in the real API
                            self.pricing_obj.bid_offer[pair][2] = data["offer"]  # high placeholder
                            self.pricing_obj.bid_offer[pair][3] = data["bid"]   # low placeholder
                            
                            # Update market data timestamp if available
                            if "ts" in data:
                                self.pricing_obj.market_data_timestamp = data["ts"]
                                self.pricing_obj.last_market_update_time = time.time()
                            
                            # Update tracking
                            self._last_update_time[pair] = time.time()
                            self._update_counts[pair] += 1
                            
                            # Notify consumer thread
                            try:
                                self.q.put_nowait(pair)
                            except queue.Full:
                                # Queue is full - we're falling behind
                                # Drop oldest updates to catch up
                                try:
                                    self.q.get_nowait()
                                    self.q.put_nowait(pair)
                                except queue.Empty:
                                    pass
                                    
                        except (json.JSONDecodeError, KeyError) as e:
                            print(f"⚠️  Invalid message format: {e}")
                            print(f"📝 Expected: 'ccy', 'bid', 'offer' fields for tick data")
                        except Exception as e:
                            print(f"⚠️  Error processing message: {e}")
                            
            except websockets.ConnectionClosed:
                self._connected = False
                self._reconnect_attempts += 1
                if self._reconnect_attempts >= self._max_reconnect_attempts:
                    print(f"❌ Connection lost after {self._reconnect_attempts} attempts.")
                    print("🔄 Switching to simulated data mode...")
                    self._use_simulation = True
                    self._last_connection_attempt = time.time()
                else:
                    print(f"❌ Connection lost. Reconnecting... (attempt {self._reconnect_attempts}/{self._max_reconnect_attempts})")
                    await asyncio.sleep(1)
            except Exception as e:
                self._connected = False
                self._reconnect_attempts += 1
                if self._reconnect_attempts >= self._max_reconnect_attempts:
                    print(f"❌ WebSocket error: {e}")
                    print("🔄 Switching to simulated data mode...")
                    self._use_simulation = True
                    self._last_connection_attempt = time.time()
                else:
                    print(f"❌ WebSocket error: {e}. Reconnecting... (attempt {self._reconnect_attempts}/{self._max_reconnect_attempts})")
                    await asyncio.sleep(5)

    def _start_bg_loop(self):
        """Start background event loop for WebSocket connection."""
        def run_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._consumer())
            
        thread = threading.Thread(target=run_loop, daemon=True)
        thread.start()

    # ---------------- Public API (same as bloomberg_api) ----------------
    def run(self):
        """
        Generator that yields bid_offer dict after price updates.
        Automatically falls back to simulated data if WebSocket fails.
        """
        self._start_bg_loop()
        
        # Wait for initial connection
        start_time = time.time()
        while not self._connected and not self._use_simulation and (time.time() - start_time) < self._connection_timeout:
            time.sleep(0.1)
            
        if not self._connected and not self._use_simulation:
            print("⚠️  Could not connect to WebSocket feed. Switching to simulated data...")
            self._use_simulation = True
            
        # Initialize simulation generator if needed
        if self._use_simulation and not self._simulation_gen:
            self._simulation_gen = self.sim_data.generate_simulated_data()
            print("🟡 Using simulated FX data (WebSocket unavailable)")
        
        last_process_time = time.time()
        min_process_interval = 0.01  # Process at most 100 times per second
        
        while not self._stop:
            current_time = time.time()
            
            # If using simulation, yield from simulation generator
            if self._use_simulation:
                # Check if we should switch back to WebSocket
                if self._connected and not self._use_simulation:
                    print("✅ Switched back to WebSocket feed")
                    self._simulation_gen = None
                else:
                    # Yield from simulation
                    if self._simulation_gen:
                        yield next(self._simulation_gen)
                    continue
            
            # Rate limit processing to avoid overwhelming GUI
            if current_time - last_process_time < min_process_interval:
                time.sleep(min_process_interval - (current_time - last_process_time))
                continue
                
            # Drain queue - keep only the last update for each pair
            changed = set()
            drain_count = 0
            
            try:
                while True:
                    pair = self.q.get_nowait()
                    changed.add(pair)
                    drain_count += 1
                    
                    # Safety limit to prevent infinite loop
                    if drain_count > 1000:
                        break
                        
            except queue.Empty:
                pass
            
            # Re-price only if we have updates
            if changed:
                # Update main currency price
                if not self.pricing_obj.synthetic_cross_mode:
                    self.pricing_obj.price()
                else:
                    # In synthetic cross mode, check if component legs updated
                    leg1 = self.pricing_obj.ccy_1_leg
                    leg2 = self.pricing_obj.ccy_2_leg
                    
                    if leg1 in changed or leg2 in changed:
                        self.pricing_obj.price_synthetic_cross()
                
                last_process_time = current_time
                
            yield self.pricing_obj.bid_offer

    def shutdown(self):
        """Stop the price feed."""
        print("🛑 Shutting down price feed...")
        self._stop = True
        
    def get_stats(self):
        """Get feed statistics for monitoring."""
        stats = {
            'connection_mode': 'simulation' if self._use_simulation else 'websocket',
            'connected': self._connected,
            'reconnect_attempts': self._reconnect_attempts,
            'pairs': {}
        }
        
        current_time = time.time()
        
        for pair in self.pairs:
            last_update = self._last_update_time.get(pair, 0)
            age = current_time - last_update if last_update > 0 else float('inf')
            
            stats['pairs'][pair] = {
                'updates': self._update_counts.get(pair, 0),
                'last_update_age': age,
                'stale': age > 5.0  # Consider stale if no update for 5 seconds
            }
            
        return stats
        
    def is_using_simulation(self):
        """Check if currently using simulated data."""
        return self._use_simulation