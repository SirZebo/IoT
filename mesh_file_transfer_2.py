import meshtastic
import meshtastic.ble_interface
from pubsub import pub
import time
import os
import base64
import hashlib
import json
import traceback
import signal
import sys
import subprocess
from threading import Lock

class MeshBLEFileReceiver:
    def __init__(self, mac_address, node_id="leaf2"):
        self.mac_address = mac_address
        self.node_id = node_id  # Unique identifier for this node
        self.interface = None
        self.connected = False
        self.receiving_files = {}
        self.last_reconnect_attempt = 0
        self.reconnect_cooldown = 5
        self.connection_lock = Lock()
        self.last_chunk_time = time.time()
        self.chunk_timeout = 60  # Increased timeout
        self.chunk_size = 100  # Keeping chunk size at 100 bytes
        self.max_retransmission_attempts = 3
        self.known_nodes = {}  # Dictionary to store discovered nodes
        
        # Set up signal handler for graceful exit
        signal.signal(signal.SIGINT, self.signal_handler)
        
        # Create received_files directory
        os.makedirs('received_files', exist_ok=True)
        print(f"Files will be saved in: {os.path.abspath('received_files')}")
        print(f"Node ID: {self.node_id}")

    def signal_handler(self, sig, frame):
        print("\nInterrupt received, saving partial files...")
        for filename in list(self.receiving_files.keys()):
            try:
                partial_path = self.save_partial_file(filename, self.receiving_files[filename]['data'])
                print(f"Saved partial data to {partial_path}")
            except Exception as e:
                print(f"Error saving partial file {filename}: {e}")
        print("Exiting...")
        sys.exit(0)

    def reconnect(self):
        with self.connection_lock:
            current_time = time.time()
            if current_time - self.last_reconnect_attempt < self.reconnect_cooldown:
                return False

            self.last_reconnect_attempt = current_time
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    print(f"\nReconnecting (attempt {attempt + 1}/{max_attempts})...")
                    # Safely close existing connection
                    if self.interface:
                        try:
                            self.interface.close()
                        except Exception as e:
                            print(f"Non-critical error closing interface: {str(e).split('(')[0]}")
                            # Continue despite close error
                    
                    # Wait longer before creating new connection
                    print("Waiting for BLE to stabilize...")
                    time.sleep(5)  
                    
                    # Try to create new connection with longer timeout
                    print("Establishing new connection...")
                    self.interface = meshtastic.ble_interface.BLEInterface(self.mac_address)
                    self.connected = True
                    print("Reconnected successfully!")
                    time.sleep(3)  # Longer stabilization time
                    return True
                except Exception as e:
                    print(f"Reconnection attempt failed: {str(e).split('(')[0]}")
                    # Try resetting Bluetooth before next attempt
                    try:
                        print("Attempting to reset Bluetooth adapter...")
                        subprocess.run(["sudo", "hciconfig", "hci0", "reset"], 
                                      stderr=subprocess.PIPE, 
                                      stdout=subprocess.PIPE,
                                      timeout=5)
                    except:
                        pass  # Ignore if this fails
                    time.sleep(5)  # Longer wait between attempts
            
            print("All reconnection attempts failed. Will try again later.")
            return False

    def connect(self):
        with self.connection_lock:
            try:
                print(f"Connecting to T-Beam at {self.mac_address}...")
                if self.interface:
                    try:
                        self.interface.close()
                    except Exception as e:
                        print(f"Non-critical error closing interface: {str(e).split('(')[0]}")
                
                # Try resetting Bluetooth before connecting
                try:
                    subprocess.run(["sudo", "hciconfig", "hci0", "reset"], 
                                  stderr=subprocess.PIPE, 
                                  stdout=subprocess.PIPE,
                                  timeout=5)
                    print("Reset Bluetooth adapter")
                except:
                    pass  # Ignore if this fails
                
                time.sleep(3)  # Longer delay before initial connection
                print("Establishing connection...")
                self.interface = meshtastic.ble_interface.BLEInterface(self.mac_address)
                self.connected = True
                print("Connected to T-Beam successfully!")
                print("Waiting for files...")
                time.sleep(2)  # Let connection stabilize
                return True
            except Exception as e:
                print(f"Connection error: {e}")
                return False

    def calculate_checksum(self, data):
        return hashlib.md5(data).hexdigest()

    def send_message_safely(self, message, retries=3, delay=2.0):
        """Send a message with retries and reconnection if needed"""
        for attempt in range(retries):
            try:
                # Convert message to a compact string to reduce size
                message_str = json.dumps(message, separators=(',', ':'))
                self.interface.sendText(message_str)
                time.sleep(delay)  # Wait after sending
                return True
            except Exception as e:
                print(f"\nError sending message (attempt {attempt + 1}): {str(e).split('(')[0]}")
                if attempt < retries - 1:
                    print("Waiting before retry...")
                    time.sleep(3)
                    if not self.reconnect():
                        time.sleep(4)
        return False

    def send_chunk_ack(self, filename, chunk_number, sender_id=None):
        """Send acknowledgment for received chunk"""
        try:
            ack_message = {
                't': 'ba',  # Shortened type (batch ack)
                'f': filename,
                'bn': chunk_number,  # Using batch number to match chunk number
                'from': self.node_id
            }
            # Add sender ID if available to target the response
            if sender_id:
                ack_message['to'] = sender_id
                
            print(f"Sending acknowledgment for chunk {chunk_number + 1}")
            return self.send_message_safely(ack_message, delay=2.0)
        except Exception as e:
            print(f"Error sending chunk acknowledgment: {e}")
            return False

    def send_error(self, filename, message, sender_id=None):
        """Send error message to sender"""
        try:
            error_message = {
                't': 'te',  # Shortened type (transfer error)
                'f': filename,
                'm': message,
                'from': self.node_id
            }
            # Add sender ID if available to target the response
            if sender_id:
                error_message['to'] = sender_id
                
            return self.send_message_safely(error_message, delay=2.0)
        except Exception as e:
            print(f"Error sending error message: {e}")
            return False

    def save_partial_file(self, filename, data, is_final=False):
        try:
            prefix = "received_" if is_final else "partial_"
            save_path = os.path.join('received_files', f"{prefix}{filename}")
            with open(save_path, 'wb') as f:
                f.write(data)
            if not is_final:
                print(f"\nSaved partial file: {save_path}")
            return save_path
        except Exception as e:
            print(f"Error saving file: {e}")
            return None

    def verify_and_save_file(self, filename, sender_id=None):
        try:
            if filename in self.receiving_files:
                file_info = self.receiving_files[filename]
                received_data = file_info['data']
                received_checksum = self.calculate_checksum(received_data)
                
                print(f"\nVerifying file {filename}")
                print(f"Received size: {len(received_data)} bytes")
                print(f"Received checksum: {received_checksum}")
                print(f"Expected checksum: {file_info['checksum']}")
                
                if received_checksum == file_info['checksum']:
                    save_path = self.save_partial_file(filename, received_data, True)
                    print(f"File saved successfully: {save_path}")
                    transfer_time = time.time() - file_info['start_time']
                    print(f"Transfer time: {transfer_time:.2f} seconds")
                    
                    # Clean up the file transfer state
                    del self.receiving_files[filename]
                    print("File transfer completed and cleaned up.")
                    return True
                else:
                    print("Checksum mismatch - file transfer failed")
                    missing_chunks = set(range(file_info['total_chunks'])) - file_info['received_chunks']
                    print(f"Missing chunks: {sorted(list(missing_chunks))}")
                    self.send_error(filename, "Checksum verification failed", sender_id)
                    
                    # Still clean up even on failure
                    del self.receiving_files[filename]
                    print("File transfer state cleaned up after error.")
                    return False
        except Exception as e:
            print(f"Error verifying file: {e}")
            # Clean up on exception too
            if filename in self.receiving_files:
                del self.receiving_files[filename]
                print("File transfer state cleaned up after exception.")
            return False

    def announce_presence(self):
        """Announce this node's presence to the network"""
        announcement = {
            't': 'announce',
            'id': self.node_id,
            'role': 'receiver',
            'time': int(time.time())
        }
        if self.send_message_safely(announcement, delay=1.0):
            print(f"Announced presence as {self.node_id}")
            return True
        else:
            print("Failed to announce presence")
            return False

    def handle_file_message(self, message_data):
        try:
            data = json.loads(message_data)
            msg_type = data.get('t', data.get('type', ''))
            filename = data.get('f', data.get('filename', ''))
            sender_id = data.get('from')
            target_node = data.get('to')

            # Reset the chunk timeout whenever we receive any file-related message
            self.last_chunk_time = time.time()

            # Check if this message is targeted for us or is a broadcast
            if target_node and target_node != self.node_id:
                print(f"\nIgnoring file message for {target_node} (we are {self.node_id})")
                return

            # Map shortened message types to full types
            if msg_type == 'fs':
                msg_type = 'file_start'
            elif msg_type == 'fc' and 'cs' in data:  # If has checksum, it's file completion
                msg_type = 'file_completion'
            elif msg_type == 'fc':
                msg_type = 'file_chunk'
            elif msg_type == 'announce':
                # Handle node announcements
                node_id = data.get('id')
                role = data.get('role')
                if node_id != self.node_id:  # Don't track ourselves
                    self.known_nodes[node_id] = {
                        'role': role,
                        'last_seen': time.time()
                    }
                    print(f"Discovered node: {node_id} (role: {role})")
                return
            elif msg_type == 'discover':
                # Respond to discovery requests
                requester_id = data.get('id')
                if requester_id != self.node_id:  # Don't respond to our own requests
                    response = {
                        't': 'announce',
                        'id': self.node_id,
                        'role': 'receiver',
                        'time': int(time.time())
                    }
                    self.send_message_safely(response, delay=1.0)
                    print(f"Responded to discovery request from {requester_id}")
                return

            if msg_type == 'file_start':
                print(f"\nStarting to receive file: {filename}")
                if target_node:
                    print(f"This file is specifically for us ({self.node_id})")
                print(f"From sender: {sender_id or 'Unknown'}")
                print(f"Expected size: {data.get('fs', data.get('file_size'))} bytes")
                print(f"Expected chunks: {data.get('tc', data.get('total_chunks'))}")
                print(f"Expected checksum: {data.get('cs', data.get('checksum'))}")
                batch_size = data.get('bs', data.get('batch_size', 1))  # Default to 1 if not specified
                print(f"Receiving {batch_size} chunk at a time")
                
                self.receiving_files[filename] = {
                    'data': bytearray(),
                    'total_chunks': data.get('tc', data.get('total_chunks')),
                    'received_chunks': set(),
                    'checksum': data.get('cs', data.get('checksum')),
                    'file_size': data.get('fs', data.get('file_size')),
                    'start_time': time.time(),
                    'retransmission_attempts': 0,
                    'batch_size': batch_size,
                    'sender_id': sender_id
                }
                self.last_chunk_time = time.time()

            elif msg_type == 'file_chunk':
                self.last_chunk_time = time.time()
                if filename in self.receiving_files:
                    try:
                        chunk_data = base64.b64decode(data.get('d', data.get('data')))
                        chunk_number = data.get('cn', data.get('chunk_number'))
                        batch_number = data.get('bn', data.get('batch_number'))
                        file_info = self.receiving_files[filename]
                        
                        # Process the chunk
                        if chunk_number not in file_info['received_chunks']:
                            file_info['received_chunks'].add(chunk_number)
                            insert_pos = chunk_number * self.chunk_size
                            
                            # Ensure data buffer is large enough
                            if insert_pos >= len(file_info['data']):
                                file_info['data'].extend(b'\0' * (insert_pos - len(file_info['data']) + len(chunk_data)))
                            
                            # Insert chunk data
                            file_info['data'][insert_pos:insert_pos + len(chunk_data)] = chunk_data
                            
                            progress = (len(file_info['received_chunks']) / file_info['total_chunks']) * 100
                            print(f"\rReceiving {filename}: {progress:.1f}% (Chunk {chunk_number + 1}/{file_info['total_chunks']})", end='')
                            
                            # Save partial file periodically
                            if len(file_info['received_chunks']) % 10 == 0:
                                self.save_partial_file(filename, file_info['data'])
                            
                            # Send acknowledgment for this chunk with added delay
                            time.sleep(2)  # Increased delay before sending ACK
                            self.send_chunk_ack(filename, chunk_number, sender_id)
                        else:
                            # If we already have this chunk, still send ACK
                            self.send_chunk_ack(filename, chunk_number, sender_id)
                    except Exception as e:
                        print(f"\nError processing chunk {chunk_number}: {e}")
                        self.send_error(filename, f"Error processing chunk {chunk_number}", sender_id)

            elif msg_type == 'file_completion':
                if filename in self.receiving_files:
                    print("\nFile transfer complete, verifying file...")
                    self.verify_and_save_file(filename, sender_id)

        except Exception as e:
            print(f"\nError handling file message: {e}")
            traceback.print_exc()
            if filename:
                self.send_error(filename, f"General error: {str(e)}", sender_id)

    def check_timeout(self):
        current_time = time.time()
        
        # Only check for timeout if we have active transfers
        if not self.receiving_files:
            return True
            
        if current_time - self.last_chunk_time > self.chunk_timeout:
            print(f"\nTransfer timeout detected - {int(current_time - self.last_chunk_time)} seconds since last chunk")
            print("Attempting to reconnect...")
            
            # Try reconnection
            reconnect_success = self.reconnect()
            
            # If reconnection fails multiple times, we should save partial files
            if not reconnect_success:
                print("Reconnection failed repeatedly. Saving partial files...")
                # Save partial data for all in-progress transfers
                for filename in list(self.receiving_files.keys()):
                    try:
                        partial_path = self.save_partial_file(filename, self.receiving_files[filename]['data'])
                        print(f"Saved partial data to {partial_path}")
                    except Exception as e:
                        print(f"Error saving partial file {filename}: {e}")
            
            return reconnect_success
        return True

    def list_known_nodes(self):
        """Display list of known nodes"""
        if not self.known_nodes:
            print("\nNo nodes discovered yet.")
            return
            
        print("\nKnown nodes:")
        for node_id, info in self.known_nodes.items():
            last_seen = time.time() - info['last_seen']
            print(f"  {node_id} (role: {info['role']}, last seen: {int(last_seen)}s ago)")

    def on_receive(self, packet, interface):
        try:
            if packet.get('decoded'):
                message = packet['decoded'].get('text', '')
                sender = packet.get('fromId', 'Unknown')
                
                # Reset the chunk timeout whenever we receive any message
                self.last_chunk_time = time.time()
                
                try:
                    data = json.loads(message)
                    if 't' in data or 'type' in data:
                        self.handle_file_message(message)
                    else:
                        print(f"\nReceived from {sender}: {message}")
                except json.JSONDecodeError:
                    print(f"\nReceived from {sender}: {message}")
        except Exception as e:
            # Don't crash on BLE errors
            error_msg = str(e)
            if "BLE" in error_msg or "bluetooth" in error_msg.lower():
                print(f"BLE communication error: {error_msg.split('(')[0]}")
                # Try to reconnect on BLE errors
                try:
                    self.reconnect()
                except:
                    pass
            else:
                print(f"Error processing message: {e}")

    def run(self):
        while True:  # Main connection loop
            try:
                if not self.connected and not self.connect():
                    print("Initial connection failed, retrying in 5 seconds...")
                    time.sleep(5)
                    continue

                pub.subscribe(self.on_receive, "meshtastic.receive")
                
                # Announce presence when we start
                self.announce_presence()

                print("\nReceiver Commands:")
                print("  /announce  - Announce presence")
                print("  /nodes     - List known nodes")
                print("  /quit      - Exit")
                print("\nReceiver is running...")
                print("Press Ctrl+C to exit")

                while True:
                    try:
                        # Non-blocking input check
                        import select
                        if select.select([sys.stdin], [], [], 0.0)[0]:
                            command = input().strip()
                            
                            if command.lower() == '/quit':
                                print("\nExiting...")
                                self.signal_handler(signal.SIGINT, None)
                                return
                            elif command.lower() == '/announce':
                                self.announce_presence()
                            elif command.lower() == '/nodes':
                                self.list_known_nodes()
                            elif command:
                                print("\nAvailable commands:")
                                print("  /announce  - Announce presence")
                                print("  /nodes     - List known nodes")
                                print("  /quit      - Exit")
                    except Exception as e:
                        print(f"Error processing command: {e}")
                    
                    # Check for timeouts
                    if not self.check_timeout():
                        break
                        
                    # Sleep to prevent CPU usage
                    time.sleep(1)
                    
            except KeyboardInterrupt:
                print("\nExiting...")
                self.signal_handler(signal.SIGINT, None)
                break
            except Exception as e:
                print(f"\nError in main loop: {e}")
                # Save any partial files on unexpected errors
                for filename in list(self.receiving_files.keys()):
                    try:
                        partial_path = self.save_partial_file(filename, self.receiving_files[filename]['data'])
                        print(f"Saved partial data to {partial_path}")
                    except:
                        pass
                        
                if not self.reconnect():
                    time.sleep(5)
            finally:
                if self.interface:
                    try:
                        self.interface.close()
                    except:
                        pass

# Change this to your T-Beam's MAC address
MAC_ADDRESS = "08:F9:E0:F6:31:AE"  # For leaf2

if __name__ == "__main__":
    import sys
    node_id = "leaf2"  # Default node ID
    
    # Check if node ID was provided as command line argument
    if len(sys.argv) > 1:
        node_id = sys.argv[1]
        
    # Use the MAC address from the script (update for each node)
    receiver = MeshBLEFileReceiver(MAC_ADDRESS, node_id)
    receiver.run()