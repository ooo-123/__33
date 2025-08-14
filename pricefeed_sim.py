"""
WebSocket-based price feed for real-time FX data.
Supports both simulated and real WebSocket servers.

Real WebSocket Server Usage:
    python gui_graph.py --websocket
    
Real Server API Format:
    Status: {"type": "status", "symbols": [...], "playback_speed": 1.0}
    Ticks:  {"ccy": "EURUSD", "bid": 1.10285, "offer": 1.10289, "mid": 1.10287, "spread": 2.4}

From the GUI you only call:
    feed = PriceFeedSim(pricing_obj, url="ws://localhost:8765")
    gen  = feed.run()          # identical signature to bbg.run()
    next(gen)                  # yields the same bid_offer dict
"""
import asyncio
import json
import websockets
import threading
import queue
import time
import collections
import numpy as np

class PriceFeedSim:
    def __init__(self, pricing_obj, url="ws://localhost:8765", pairs=None):
        """
        Initialize WebSocket-based price feed simulator.
        
        Args:
            pricing_obj: The pricing object with bid_offer array
            url: WebSocket server URL
            pairs: List of currency pairs to subscribe to
        """
        self.url = url
        self.pricing_obj = pricing_obj
        self.pairs = pairs or [p for p in self.pricing_obj.ccys if p != 'CROSS']
        self.q = queue.Queue(maxsize=10000)  # Back-pressure protection
        self._stop = False
        self._connected = False
        self._last_update_time = {}
        self._update_counts = {}
        
        # Initialize update tracking
        for pair in self.pairs:
            self._last_update_time[pair] = 0
            self._update_counts[pair] = 0

    # ---------------- Server-pull thread ----------------
    async def _consumer(self):
        """Consume price updates from WebSocket server."""
        print(f"🔌 Connecting to price feed at {self.url}...")
        
        while not self._stop:
            try:
                async with websockets.connect(self.url, ping_interval=20) as ws:
                    self._connected = True
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
                print("❌ Connection lost. Reconnecting in 1s...")
                await asyncio.sleep(1)
            except Exception as e:
                self._connected = False
                print(f"❌ WebSocket error: {e}. Reconnecting in 5s...")
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
        Compatible with bloomberg_api.run() interface.
        """
        self._start_bg_loop()
        
        # Wait for initial connection
        connect_timeout = 5.0
        start_time = time.time()
        while not self._connected and (time.time() - start_time) < connect_timeout:
            time.sleep(0.1)
            
        if not self._connected:
            print("⚠️  Warning: Could not connect to price feed. Continuing anyway...")
        
        last_process_time = time.time()
        min_process_interval = 0.01  # Process at most 100 times per second
        
        while not self._stop:
            current_time = time.time()
            
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
        stats = {}
        current_time = time.time()
        
        for pair in self.pairs:
            last_update = self._last_update_time.get(pair, 0)
            age = current_time - last_update if last_update > 0 else float('inf')
            
            stats[pair] = {
                'updates': self._update_counts.get(pair, 0),
                'last_update_age': age,
                'stale': age > 5.0  # Consider stale if no update for 5 seconds
            }
            
        return stats