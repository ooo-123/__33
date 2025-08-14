#!/usr/bin/env python3
"""
Fire-and-forget simulated FX feed.
Run: python sim_feed.py --pairs AUDUSD EURUSD ... --pps 500
"""

import asyncio
import json
import random
import time
import itertools
import argparse
import math
import websockets  # pip install websockets

def make_parser():
    p = argparse.ArgumentParser(description="High-performance FX price feed simulator")
    p.add_argument("--pairs", nargs="+",
                   default=["EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD", 
                           "NZDUSD", "USDCHF", "EURGBP", "EURJPY", "GBPJPY",
                           "AUDJPY", "AUDNZD", "EURCHF", "USDSGD", "USDCNH"],
                   help="Currency pairs to simulate")
    p.add_argument("--pps", type=int, default=200,
                   help="Ticks per second per pair")
    p.add_argument("--port", type=int, default=8765,
                   help="WebSocket server port")
    return p

def mid(bid, ask): 
    return (bid + ask) / 2

async def publish_prices(websocket, path, pairs, pps):
    """One client connection → stream JSON lines forever."""
    seq = itertools.count(1)
    
    # Realistic seed prices for FX pairs
    base_prices = {
        "EURUSD": 1.1618, "USDJPY": 148.79, "GBPUSD": 1.3395, "AUDUSD": 0.6519,
        "USDCAD": 1.3714, "NZDUSD": 0.5949, "USDCHF": 0.8005, "EURGBP": 0.8673,
        "EURJPY": 172.86, "GBPJPY": 199.35, "AUDJPY": 97.00, "AUDNZD": 1.0959,
        "EURCHF": 0.9300, "USDSGD": 1.2849, "USDCNH": 7.1743
    }
    
    # Initialize state with realistic spreads
    state = {}
    for pair in pairs:
        base_price = base_prices.get(pair, random.uniform(0.8, 1.5))
        
        # Realistic spreads based on pair liquidity (in pips)
        if pair in ["EURUSD", "USDJPY", "GBPUSD"]:
            spread = 0.00006  # 0.6 pips for majors
        elif pair in ["AUDUSD", "USDCAD", "NZDUSD", "USDCHF"]:
            spread = 0.00010  # 1.0 pips for liquid pairs
        elif "JPY" in pair:
            spread = 0.008    # 0.8 pips for JPY pairs
        else:
            spread = 0.00020  # 2.0 pips for crosses
            
        state[pair] = {
            "bid": base_price - spread/2,
            "ask": base_price + spread/2,
            "high": base_price + spread/2,
            "low": base_price - spread/2,
            "trend": 0.0,
            "volatility": random.uniform(0.00001, 0.00005)
        }
    
    period = 1 / pps
    
    client_addr = getattr(websocket, 'remote_address', 'unknown')
    print(f"📡 Publishing {len(pairs)} pairs at {pps} ticks/sec to client {client_addr}")
    
    try:
        while True:
            t0 = time.time()
            
            for pair in pairs:
                s = state[pair]
                
                # Simulate realistic price movements with trends
                if random.random() < 0.02:  # 2% chance to change trend
                    s["trend"] = random.uniform(-0.00002, 0.00002)
                
                # Add some market events (news, etc)
                if random.random() < 0.001:  # 0.1% chance of market event
                    s["volatility"] = random.uniform(0.00005, 0.00020)
                else:
                    s["volatility"] *= 0.99  # Decay volatility
                
                # Calculate price movement
                drift = s["trend"] + random.uniform(-s["volatility"], s["volatility"])
                
                # Update prices
                mid_price = mid(s["bid"], s["ask"])
                new_mid = max(0.0001, mid_price * (1 + drift))
                
                # Maintain realistic spread
                if "JPY" in pair:
                    spread = 0.008 + random.uniform(-0.002, 0.002)
                else:
                    spread = s["ask"] - s["bid"] + random.uniform(-0.00001, 0.00001)
                
                s["bid"] = new_mid - spread/2
                s["ask"] = new_mid + spread/2
                s["high"] = max(s["high"], s["ask"])
                s["low"] = min(s["low"], s["bid"])
                
                # Create message
                message = {
                    "seq": next(seq),
                    "ts": time.time(),
                    "pair": pair,
                    "bid": round(s["bid"], 6 if "JPY" not in pair else 3),
                    "ask": round(s["ask"], 6 if "JPY" not in pair else 3),
                    "high": round(s["high"], 6 if "JPY" not in pair else 3),
                    "low": round(s["low"], 6 if "JPY" not in pair else 3)
                }
                
                await websocket.send(json.dumps(message))
            
            # Maintain ticks-per-second rate
            elapsed = time.time() - t0
            sleep_time = max(0, period * len(pairs) - elapsed)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
                
    except websockets.ConnectionClosed:
        print(f"❌ Client disconnected: {client_addr}")
    except Exception as e:
        print(f"❌ Error in publish_prices: {e}")

async def main():
    args = make_parser().parse_args()
    
    print(f"🌐 Sim feed server starting...")
    print(f"📊 Pairs: {len(args.pairs)}")
    print(f"⚡ Rate: {args.pps} ticks/sec per pair")
    print(f"🔌 Port: ws://localhost:{args.port}")
    print(f"💡 Total throughput: {args.pps * len(args.pairs)} ticks/sec")
    print("-" * 50)
    
    async def handler(websocket):
        await publish_prices(websocket, None, args.pairs, args.pps)
    
    async with websockets.serve(handler, "localhost", args.port, max_queue=None):
        print("✅ Server ready. Waiting for connections...")
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    asyncio.run(main())