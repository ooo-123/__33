#!/usr/bin/env python3
"""
Improved non-blocking voice announcement system for FX prices.
Uses separate process with better termination handling.
"""
import os
import time
import pygame
import multiprocessing as mp
from pathlib import Path
from queue import Empty
import queue
import logging
import signal
import threading

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VoiceWorker:
    """Voice worker that runs in a separate process"""
    
    def __init__(self, voice_dir="voice/sounds", speed_multiplier=1.0):
        self.voice_dir = Path(voice_dir)
        self.speed_multiplier = max(0.5, min(3.0, speed_multiplier))  # Clamp between 0.5 and 3.0
        self.current_pair = None
        self.last_bid = None
        self.last_offer = None
        self.first_announcement = True
        self.running = True
        
        # Initialize pygame mixer for audio
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
            logger.info(f"Voice worker audio initialized (speed multiplier: {self.speed_multiplier}x)")
        except pygame.error as e:
            logger.error(f"Audio initialization failed: {e}")
            raise
    
    def stop(self):
        """Stop the worker"""
        self.running = False
        pygame.mixer.quit()
    
    def _play_sound(self, sound_name):
        """Play a sound file with speed adjustment"""
        if not self.running:
            return False
            
        audio_file = self.voice_dir / f"{sound_name}.mp3"
        
        # Fallback for "offered" to "offer" if not available
        if not audio_file.exists() and sound_name == "offered":
            audio_file = self.voice_dir / "offer.mp3"
        
        if not audio_file.exists():
            return False
        
        # Check if file is corrupted (0 bytes)
        if audio_file.stat().st_size == 0:
            # Try fallback again for "offered"
            if sound_name == "offered":
                audio_file = self.voice_dir / "offer.mp3"
                if not audio_file.exists() or audio_file.stat().st_size == 0:
                    return False
            else:
                return False
        
        try:
            sound = pygame.mixer.Sound(str(audio_file))
            
            # Adjust duration based on speed multiplier
            # Note: Files are already at 1.2x, so actual speed = 1.2 * multiplier
            actual_speed = 1.2 * self.speed_multiplier
            
            # Get original duration and calculate new duration
            original_duration = sound.get_length()
            adjusted_duration = original_duration / self.speed_multiplier
            
            channel = sound.play()
            
            # Wait for adjusted duration (simulating speed change)
            start_time = time.time()
            while channel and channel.get_busy() and self.running:
                if time.time() - start_time >= adjusted_duration:
                    channel.stop()
                    break
                time.sleep(0.01)
            
            # Stop sound if we're no longer running
            if not self.running and channel:
                channel.stop()
            
            return True
        except pygame.error as e:
            logger.error(f"Error playing {audio_file}: {e}")
            return False
    
    def _extract_pip_value(self, pip_str):
        """Extract pip value from the pip string, preserving .5 values"""
        if not pip_str:
            return None
        
        try:
            pip_value = float(pip_str)
            return pip_value  # Return float to preserve .5 values
        except (ValueError, TypeError):
            return None
    
    def _play_pip_value(self, pip_value):
        """Play a pip value with special handling for .5 and 0"""
        if pip_value is None:
            return False
        
        # Handle "figure" for 0
        if pip_value == 0:
            return self._play_sound("figure")
        
        # Check if it's a half pip
        is_half = (pip_value % 1) == 0.5
        
        if is_half:
            # Try dedicated half-pip file first (e.g., 13.5 -> 13_5.mp3)
            half_filename = f"{pip_value:.1f}".replace(".", "_")
            half_file_path = self.voice_dir / f"{half_filename}.mp3"
            
            # Check if dedicated file exists and is not corrupted (size > 0)
            if half_file_path.exists() and half_file_path.stat().st_size > 0:
                return self._play_sound(half_filename)
            else:
                # Fallback to combining whole number + "and a half"
                whole_part = int(pip_value)
                if self._play_sound(str(whole_part)):
                    time.sleep(0.05 / self.speed_multiplier)  # Adjust pause based on speed
                    return self._play_sound("and_a_half")
                return False
        else:
            # Play as regular integer
            return self._play_sound(str(int(pip_value)))
    
    def process_announcement(self, data):
        """Process a voice announcement request"""
        if not self.running:
            return
            
        pair = data.get('pair')
        bid_pips = data.get('bid_pips')
        offer_pips = data.get('offer_pips')
        
        # Check if currency pair changed
        pair_changed = pair != self.current_pair
        if pair_changed:
            self.current_pair = pair
            self.first_announcement = True
            logger.info(f"Currency pair changed to {pair}, clearing previous state")
            
            # Announce currency pair
            pair_lower = pair.lower() if pair else ""
            if self._play_sound(pair_lower):
                time.sleep(0.1 / self.speed_multiplier)  # Adjust for speed
            else:
                # Try individual currency names
                if pair and len(pair) == 6:
                    currency_map = {
                        'EUR': 'euro', 'USD': 'dollar', 'GBP': 'pound',
                        'JPY': 'yen', 'AUD': 'aussie', 'NZD': 'kiwi',
                        'CAD': 'canadian', 'CHF': 'swiss', 'CNH': 'yuan',
                        'SGD': 'sing', 'HKD': 'hongkong', 'PLN': 'pole',
                        'NOK': 'norwegian', 'SEK': 'swedish', 'DKK': 'danish'
                    }
                    
                    base = pair[:3]
                    quote = pair[3:]
                    
                    if base in currency_map:
                        self._play_sound(currency_map[base])
                        time.sleep(0.05 / self.speed_multiplier)  # Adjust for speed
                    
                    if quote in currency_map:
                        self._play_sound(currency_map[quote])
                        time.sleep(0.05 / self.speed_multiplier)  # Adjust for speed
        
        # Extract pip values
        bid_pips_value = self._extract_pip_value(bid_pips)
        offer_pips_value = self._extract_pip_value(offer_pips)
        
        # Check if bid equals offer (choice)
        is_choice = (bid_pips_value is not None and 
                    offer_pips_value is not None and 
                    bid_pips_value == offer_pips_value)
        
        # First announcement includes "bid" and "offered" words
        if self.first_announcement:
            self.first_announcement = False
            
            if is_choice:
                # Say the price followed by "choice"
                self._play_pip_value(bid_pips_value)
                time.sleep(0.15)
                self._play_sound("choice")
            else:
                # First time: "68 bid, 71 offered"
                if bid_pips_value is not None:
                    self._play_pip_value(bid_pips_value)
                    time.sleep(0.1 / self.speed_multiplier)
                    self._play_sound("bid")
                    time.sleep(0.2 / self.speed_multiplier)
                
                if offer_pips_value is not None:
                    self._play_pip_value(offer_pips_value)
                    time.sleep(0.1 / self.speed_multiplier)
                    self._play_sound("offered")
            
            self.last_bid = bid_pips_value
            self.last_offer = offer_pips_value
        
        else:
            # Subsequent announcements: just say the numbers "68 71"
            if bid_pips_value != self.last_bid or offer_pips_value != self.last_offer:
                if is_choice:
                    # If both are same, say "X choice"
                    self._play_pip_value(bid_pips_value)
                    time.sleep(0.08 / self.speed_multiplier)  # Adjust for speed
                    self._play_sound("choice")
                else:
                    # Subsequent updates: just numbers "68 71" (no "bid"/"offered")
                    if bid_pips_value is not None:
                        self._play_pip_value(bid_pips_value)
                        time.sleep(0.15 / self.speed_multiplier)  # Slightly longer pause between numbers
                    
                    if offer_pips_value is not None:
                        self._play_pip_value(offer_pips_value)
                
                self.last_bid = bid_pips_value
                self.last_offer = offer_pips_value

def voice_worker_process(command_queue, voice_dir, stop_event, speed_multiplier=1.0):
    """Worker process for voice announcements"""
    # Ignore SIGINT in worker process
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    
    worker = None
    try:
        worker = VoiceWorker(voice_dir, speed_multiplier)
        logger.info("Voice worker process started")
        
        while not stop_event.is_set():
            try:
                # Check for commands with short timeout
                command = command_queue.get(timeout=0.1)
                
                if command == "STOP":
                    logger.info("Voice worker received STOP command")
                    break
                
                elif isinstance(command, dict):
                    # Clear any remaining announcements in queue to prevent backlog
                    discarded_count = 0
                    try:
                        while True:
                            # Try to get more commands without blocking
                            next_command = command_queue.get_nowait()
                            if next_command == "STOP":
                                logger.info("Voice worker received STOP command")
                                return
                            elif isinstance(next_command, dict):
                                # Replace current command with the newer one
                                command = next_command
                                discarded_count += 1
                    except Empty:
                        # No more commands in queue, proceed with the latest one
                        pass
                    
                    if discarded_count > 0:
                        logger.info(f"Voice worker discarded {discarded_count} old announcements to prevent backlog")
                    
                    worker.process_announcement(command)
                
            except Empty:
                continue
            except Exception as e:
                logger.error(f"Voice worker error: {e}")
                
    except Exception as e:
        logger.error(f"Voice worker process error: {e}")
    finally:
        if worker:
            worker.stop()
        logger.info("Voice worker process ending")

class VoiceAnnouncerV3:
    """Improved voice announcer with better termination"""
    
    def __init__(self, voice_dir="voice/sounds", speed_multiplier=1.0):
        self.voice_dir = Path(voice_dir)
        self.speed_multiplier = max(0.5, min(3.0, speed_multiplier))  # Clamp between 0.5 and 3.0
        self.enabled = False
        self.process = None
        self.command_queue = None
        self.stop_event = None
        self._lock = threading.Lock()
        self.last_pair = None  # Track last announced pair
        self.last_announcement_time = 0  # Rate limiting
        
        # Check if voice files are available
        self.voice_available = self.voice_dir.exists() and any(self.voice_dir.glob("*.mp3"))
        
        if self.voice_available:
            actual_speed = 1.2 * self.speed_multiplier
            logger.info(f"Voice files found in {self.voice_dir} (effective speed: {actual_speed:.1f}x)")
        else:
            logger.warning(f"No voice files found in {self.voice_dir}")
    
    def enable(self):
        """Enable voice announcements"""
        with self._lock:
            if not self.voice_available:
                logger.error("Cannot enable voice - no voice files available")
                return False
            
            if self.enabled:
                return True
            
            try:
                # Create synchronization objects
                self.command_queue = mp.Queue(maxsize=10)
                self.stop_event = mp.Event()
                
                # Start voice worker process
                self.process = mp.Process(
                    target=voice_worker_process,
                    args=(self.command_queue, str(self.voice_dir), self.stop_event, self.speed_multiplier)
                )
                self.process.daemon = True  # Make it a daemon process
                self.process.start()
                
                # Wait briefly to ensure process started
                time.sleep(0.1)
                
                if self.process.is_alive():
                    self.enabled = True
                    logger.info("Voice announcements enabled")
                    return True
                else:
                    logger.error("Voice process failed to start")
                    self._cleanup()
                    return False
                
            except Exception as e:
                logger.error(f"Failed to enable voice: {e}")
                self._cleanup()
                return False
    
    def disable(self):
        """Disable voice announcements"""
        with self._lock:
            if not self.enabled:
                return
            
            logger.info("Disabling voice announcements...")
            
            try:
                # Signal stop event first
                if self.stop_event:
                    self.stop_event.set()
                
                # Send stop command
                if self.command_queue:
                    try:
                        self.command_queue.put_nowait("STOP")
                    except:
                        pass
                
                # Wait briefly for graceful shutdown
                if self.process and self.process.is_alive():
                    self.process.join(timeout=1.0)
                    
                    # Force terminate if still alive
                    if self.process.is_alive():
                        logger.warning("Force terminating voice process")
                        self.process.terminate()
                        self.process.join(timeout=0.5)
                        
                        # Kill if still not dead
                        if self.process.is_alive():
                            logger.error("Force killing voice process")
                            self.process.kill()
                            self.process.join(timeout=0.5)
                
                self._cleanup()
                logger.info("Voice announcements disabled")
                
            except Exception as e:
                logger.error(f"Error disabling voice: {e}")
                self._cleanup()
    
    def _cleanup(self):
        """Clean up resources"""
        self.enabled = False
        
        # Close queue
        if self.command_queue:
            try:
                self.command_queue.close()
                self.command_queue.join_thread()
            except:
                pass
        
        self.process = None
        self.command_queue = None
        self.stop_event = None
    
    def is_enabled(self):
        """Check if voice is enabled"""
        with self._lock:
            return self.enabled and self.process and self.process.is_alive()
    
    def _clear_queue(self):
        """Clear all pending announcements from the queue"""
        if not self.command_queue:
            return
            
        cleared_count = 0
        try:
            while True:
                self.command_queue.get_nowait()
                cleared_count += 1
        except queue.Empty:
            pass
        
        if cleared_count > 0:
            logger.info(f"Cleared {cleared_count} pending voice announcements")
    
    def announce_price(self, bid, offer, currency_pair="", bid_pips=None, offer_pips=None):
        """Queue a price announcement (non-blocking)"""
        if not self.is_enabled():
            return
        
        current_time = time.time()
        
        # Rate limiting: Don't announce more than once every 0.5 seconds for same pair
        # unless currency pair changed
        if (currency_pair == self.last_pair and 
            current_time - self.last_announcement_time < 0.5):
            return
        
        # If currency pair changed, clear the queue to prevent mixing announcements
        if currency_pair != self.last_pair:
            self._clear_queue()
            self.last_pair = currency_pair
        
        self.last_announcement_time = current_time
        
        try:
            # Queue the announcement without blocking
            self.command_queue.put_nowait({
                'pair': currency_pair,
                'bid': bid,
                'offer': offer,
                'bid_pips': bid_pips,
                'offer_pips': offer_pips
            })
        except:
            # Queue is full, skip this announcement
            pass
    
    def __del__(self):
        """Cleanup on deletion"""
        try:
            self.disable()
        except:
            pass

# Testing
if __name__ == "__main__":
    print("🎙️  Voice Announcer V3 Test")
    print("=" * 30)
    
    announcer = VoiceAnnouncerV3()
    
    # Test enable/disable cycle
    for i in range(3):
        print(f"\n--- Test cycle {i+1} ---")
        
        if announcer.enable():
            print("✅ Voice enabled")
            
            # Test announcement
            announcer.announce_price(
                1.1028, 1.1029, "EURUSD",
                bid_pips="13.5", offer_pips="14.0"
            )
            
            time.sleep(2)
            
            print("Disabling voice...")
            announcer.disable()
            print("✅ Voice disabled")
            
            time.sleep(1)
        else:
            print("❌ Failed to enable voice")
    
    print("\n✅ Test complete")