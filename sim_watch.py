#!/usr/bin/env python3
"""
Tiny console subscriber - shows the last feed value every 0.5s.
Useful for monitoring the feed independently of the GUI.
"""
import asyncio
import websockets
import json
import time
import collections
import argparse
import os
import sys

class FeedMonitor:
    def __init__(self, url="ws://localhost:8765"):
        self.url = url
        self.latest = collections.defaultdict(dict)
        self.start_time = time.time()
        self.total_messages = 0
        self.last_seq = {}
        
    async def watch(self):
        """Connect to feed and collect updates."""
        print(f"🔌 Connecting to {self.url}...")
        
        while True:
            try:
                async with websockets.connect(self.url) as ws:
                    print("✅ Connected to feed")
                    
                    async for msg in ws:
                        try:
                            tick = json.loads(msg)
                            pair = tick["pair"]
                            
                            # Check for sequence gaps
                            if pair in self.last_seq:
                                expected = self.last_seq[pair] + 1
                                if tick.get("seq", 0) > expected:
                                    tick["gap"] = tick["seq"] - expected
                                    
                            self.last_seq[pair] = tick.get("seq", 0)
                            self.latest[pair] = tick
                            self.total_messages += 1
                            
                        except json.JSONDecodeError:
                            pass
                            
            except websockets.ConnectionClosed:
                print("❌ Connection lost. Reconnecting...")
                await asyncio.sleep(1)
            except Exception as e:
                print(f"❌ Error: {e}")
                await asyncio.sleep(5)
    
    def display(self, refresh_rate=0.5):
        """Display feed data in terminal."""
        while True:
            os.system("cls" if os.name == "nt" else "clear")
            
            # Header
            runtime = time.time() - self.start_time
            print(f"🔴 Live FX Feed Monitor | Runtime: {runtime:.0f}s | Messages: {self.total_messages}")
            print("=" * 80)
            
            # Column headers
            print(f"{'Pair':<8} {'Bid':<10} {'Ask':<10} {'Spread':<8} {'Seq':<10} {'Age':<6} {'Gap'}")
            print("-" * 80)
            
            # Display each pair
            current_time = time.time()
            
            for pair, tick in sorted(self.latest.items()):
                bid = tick.get('bid', 0)
                ask = tick.get('ask', 0)
                spread = (ask - bid) * (10000 if 'JPY' not in pair else 100)
                seq = tick.get('seq', 0)
                age = current_time - tick.get('ts', 0)
                gap = tick.get('gap', '')
                
                # Color code based on staleness
                if age > 5:
                    color = "\033[91m"  # Red for stale
                elif age > 1:
                    color = "\033[93m"  # Yellow for slow
                else:
                    color = "\033[92m"  # Green for fresh
                
                reset = "\033[0m"
                
                # Format based on pair type
                if 'JPY' in pair:
                    price_fmt = f"{bid:>10.3f} / {ask:<10.3f}"
                else:
                    price_fmt = f"{bid:>10.5f} / {ask:<10.5f}"
                
                print(f"{color}{pair:<8} {price_fmt} {spread:>6.1f}p {seq:>8} {age:>5.1f}s {gap:>4}{reset}")
            
            # Footer stats
            print("-" * 80)
            total_pairs = len(self.latest)
            fresh_pairs = sum(1 for t in self.latest.values() if current_time - t.get('ts', 0) < 1)
            print(f"Pairs: {total_pairs} | Fresh: {fresh_pairs} | Rate: {self.total_messages/runtime:.1f} msg/s")
            
            time.sleep(refresh_rate)

async def main():
    parser = argparse.ArgumentParser(description="Monitor FX price feed")
    parser.add_argument("--url", default="ws://localhost:8765", help="WebSocket URL")
    parser.add_argument("--refresh", type=float, default=0.5, help="Display refresh rate (seconds)")
    args = parser.parse_args()
    
    monitor = FeedMonitor(args.url)
    
    # Start watching in background
    watch_task = asyncio.create_task(monitor.watch())
    
    # Run display in separate thread (blocking)
    import threading
    display_thread = threading.Thread(target=monitor.display, args=(args.refresh,))
    display_thread.daemon = True
    display_thread.start()
    
    # Keep async loop running
    try:
        await watch_task
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n✅ Monitor stopped")
        sys.exit(0)