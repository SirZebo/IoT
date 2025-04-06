import meshtastic
import meshtastic.ble_interface
from pubsub import pub
import time
from datetime import datetime
import os
import base64
import hashlib
import json
import traceback
from threading import Lock, Event

class MeshBLEFileTransfer:
    def __init__(self, mac_address, node_id="leaf1"):
        self.mac_address = mac_address
        self.node_id = node_id  # Unique identifier for this node
        self.interface = None
        self.connected = False
        self.chunk_size = 100  # Keeping chunk size at 100 bytes
        self.batch_size = 1  # Sending just 1 chunk at a time
        self.connection_lock = Lock()
        self.last_reconnect_time = 0
        self.reconnect_cooldown = 5
        self.current_file_path = None
        self.current_file_data = None
        self.ack_received = Event()
        self.last_ack_batch = -1
        self.transfer_timeout = 30  # Timeout for waiting for batch ACK
        self.chunk_delay = 2.0  # Delay between chunks
        self.batch_delay = 3.0  # Delay between batches (reduced since we're only sending 1 chunk)
        self.known_nodes = {}  # Dictionary to store discovered nodes
        print(f"Current working directory: {os.getcwd()}")
        print(f"Node ID: {self.node_id}")

    def reconnect(self):
        with self.connection_lock:
            current_time = time.time()
            if current_time - self.last_reconnect_time < self.reconnect_cooldown:
                return False

            self.last_reconnect_time = current_time
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    print(f"\nReconnecting (attempt {attempt + 1}/{max_attempts})...")
                    if self.interface:
                        try:
                            self.interface.close()
                        except:
                            pass
                    time.sleep(3)  # Longer delay before reconnection
                    self.interface = meshtastic.ble_interface.BLEInterface(self.mac_address)
                    self.connected = True
                    print("Reconnected successfully!")
                    time.sleep(1)  # Let connection stabilize
                    return True
                except Exception as e:
                    print(f"Reconnection attempt failed: {e}")
                    time.sleep(3)
            return False

    def connect(self):
        try:
            print(f"Connecting to T-Beam at {self.mac_address}...")
            if self.interface:
                try:
                    self.interface.close()
                except:
                    pass
            time.sleep(2)  # Longer delay before initial connection
            self.interface = meshtastic.ble_interface.BLEInterface(self.mac_address)
            self.connected = True
            print("Connected to T-Beam successfully!")
            time.sleep(1)  # Let connection stabilize
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
                print(f"\nError sending message (attempt {attempt + 1}): {e}")
                if attempt < retries - 1:
                    print("Waiting before retry...")
                    time.sleep(3)
                    if not self.reconnect():
                        time.sleep(4)
        return False

    def wait_for_batch_ack(self, batch_number, timeout=30):
        """Wait for acknowledgment of a batch"""
        self.ack_received.clear()
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.ack_received.wait(1):  # Wait with timeout of 1 second
                if self.last_ack_batch >= batch_number:
                    return True
                self.ack_received.clear()  # Clear for next wait if not our batch
            
        return False

    def send_batch(self, filename, batch_number, chunk_number, total_chunks, target_node=None):
        """Send a single chunk as a batch"""
        print(f"\nSending chunk {chunk_number + 1}/{total_chunks}")
        
        chunk_start = chunk_number * self.chunk_size
        chunk_end = min(chunk_start + self.chunk_size, len(self.current_file_data))
        chunk = self.current_file_data[chunk_start:chunk_end]
        chunk_b64 = base64.b64encode(chunk).decode('utf-8')
        
        # Send the chunk directly (no batch start/end)
        chunk_message = {
            't': 'fc',  # Shortened type
            'f': filename,
            'cn': chunk_number,
            'bn': batch_number,
            'd': chunk_b64,
            'from': self.node_id
        }
        
        # Add target node if specified
        if target_node:
            chunk_message['to'] = target_node

        print(f"Sending chunk {chunk_number + 1}/{total_chunks} ({len(chunk)} bytes)")
        if not self.send_message_safely(chunk_message, delay=self.chunk_delay):
            print(f"Failed to send chunk {chunk_number + 1}")
            return False
        
        # Wait for chunk acknowledgment
        if self.wait_for_batch_ack(batch_number, timeout=self.transfer_timeout):
            print(f"Chunk {chunk_number + 1} acknowledged")
            return True
        else:
            print(f"No acknowledgment received for chunk {chunk_number + 1}")
            return False

    def send_file(self, filepath, target_node=None):
        try:
            if not os.path.exists(filepath):
                print(f"File not found: {filepath}")
                return False

            self.current_file_path = filepath
            file_size = os.path.getsize(filepath)
            print(f"File size: {file_size} bytes")

            with open(filepath, 'rb') as file:
                self.current_file_data = file.read()

            filename = os.path.basename(filepath)
            total_chunks = (len(self.current_file_data) + self.chunk_size - 1) // self.chunk_size
            file_checksum = self.calculate_checksum(self.current_file_data)

            print(f"Total chunks to send: {total_chunks}")
            print(f"Chunk size: {self.chunk_size} bytes")
            print(f"File checksum: {file_checksum}")
            print(f"Sending 1 chunk at a time")
            
            if target_node:
                print(f"Targeting specific node: {target_node}")
            else:
                print("Broadcasting to all nodes")

            # Send file start message
            start_message = {
                't': 'fs',  # Shortened type
                'f': filename,
                'tc': total_chunks,
                'fs': len(self.current_file_data),
                'cs': file_checksum,
                'bs': self.batch_size,
                'from': self.node_id
            }
            
            # Add target node if specified
            if target_node:
                start_message['to'] = target_node
                
            if not self.send_message_safely(start_message, delay=4.0):
                print("Failed to send start message")
                return False

            print(f"\nStarting file transfer: {filename}")
            time.sleep(5)  # Longer wait for start message to be processed

            # Send chunks one at a time
            success = True
            max_retries = 3
            
            for chunk_number in range(total_chunks):
                # Try to send this chunk with retries
                chunk_success = False
                for retry in range(max_retries):
                    if self.send_batch(filename, chunk_number, chunk_number, total_chunks, target_node):
                        chunk_success = True
                        break
                    else:
                        print(f"Chunk {chunk_number + 1} failed, retrying ({retry + 1}/{max_retries})...")
                        # Reconnect before retry
                        if not self.reconnect():
                            time.sleep(4)
                        time.sleep(3)  # Wait before retry
                
                if not chunk_success:
                    print(f"Failed to send chunk {chunk_number + 1} after {max_retries} attempts")
                    success = False
                    break
                
                # Take a short break between chunks
                time.sleep(self.batch_delay)
                
                # Progress update
                progress = ((chunk_number + 1) / total_chunks) * 100
                print(f"Overall progress: {progress:.1f}%")

            # Send completion message
            if success:
                completion_message = {
                    't': 'fc',  # Shortened type (file completion)
                    'f': filename,
                    'cs': file_checksum,
                    'tc': total_chunks,
                    'from': self.node_id
                }
                
                # Add target node if specified
                if target_node:
                    completion_message['to'] = target_node
                    
                if not self.send_message_safely(completion_message, delay=4.0):
                    print("Failed to send completion message")
                    return False

                print(f"\nFile transfer completed: {filename}")
                return True
            else:
                print(f"\nFile transfer failed: {filename}")
                return False

        except Exception as e:
            print(f"\nError sending file: {e}")
            traceback.print_exc()
            return False
        finally:
            # Clear current file data
            self.current_file_data = None
            self.current_file_path = None

    def announce_presence(self):
        """Announce this node's presence to the network"""
        announcement = {
            't': 'announce',
            'id': self.node_id,
            'role': 'sender',
            'time': int(time.time())
        }
        if self.send_message_safely(announcement, delay=1.0):
            print(f"Announced presence as {self.node_id}")
            return True
        else:
            print("Failed to announce presence")
            return False
            
    def discover_nodes(self):
        """Send a discovery request to find other nodes"""
        discovery_request = {
            't': 'discover',
            'id': self.node_id,
            'time': int(time.time())
        }
        if self.send_message_safely(discovery_request, delay=1.0):
            print("Sent discovery request, waiting for responses...")
            time.sleep(5)  # Wait for responses
            return True
        else:
            print("Failed to send discovery request")
            return False

    def handle_message(self, message_data):
        try:
            data = json.loads(message_data)
            msg_type = data.get('t', data.get('type', ''))
            
            if msg_type in ['ba', 'batch_ack']:
                batch_number = data.get('bn', data.get('batch_number'))
                print(f"Received acknowledgment for chunk {batch_number + 1}")
                self.last_ack_batch = batch_number
                self.ack_received.set()
                
            elif msg_type in ['te', 'transfer_error']:
                error_msg = data.get('m', data.get('message', 'Unknown error'))
                print(f"\nReceived transfer error: {error_msg}")
            
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
                
            elif msg_type == 'discover':
                # Respond to discovery requests
                requester_id = data.get('id')
                if requester_id != self.node_id:  # Don't respond to our own requests
                    response = {
                        't': 'announce',
                        'id': self.node_id,
                        'role': 'sender',
                        'time': int(time.time())
                    }
                    self.send_message_safely(response, delay=1.0)
                    print(f"Responded to discovery request from {requester_id}")
                
        except Exception as e:
            print(f"\nError handling message: {e}")
            traceback.print_exc()

    def on_receive(self, packet, interface):
        try:
            if packet.get('decoded'):
                message = packet['decoded'].get('text', '')
                sender = packet.get('fromId', 'Unknown')
                
                try:
                    data = json.loads(message)
                    if 't' in data or 'type' in data:
                        self.handle_message(message)
                    else:
                        print(f"\nReceived from {sender}: {message}")
                except json.JSONDecodeError:
                    print(f"\nReceived from {sender}: {message}")
        except Exception as e:
            print(f"Error processing message: {e}")

    def list_known_nodes(self):
        """Display list of known nodes"""
        if not self.known_nodes:
            print("\nNo nodes discovered yet. Try running /discover first.")
            return
            
        print("\nKnown nodes:")
        for node_id, info in self.known_nodes.items():
            last_seen = time.time() - info['last_seen']
            print(f"  {node_id} (role: {info['role']}, last seen: {int(last_seen)}s ago)")

    def run(self):
        while True:  # Main connection loop
            try:
                if not self.connected and not self.connect():
                    print("Connection failed, retrying in 5 seconds...")
                    time.sleep(5)
                    continue

                pub.subscribe(self.on_receive, "meshtastic.receive")
                
                # Announce presence when we start
                self.announce_presence()

                print("\nFile Transfer Commands:")
                print("  /send <filepath>              - Send file to all nodes")
                print("  /sendto <filepath> <node_id>  - Send file to specific node")
                print("  /discover                     - Discover other nodes")
                print("  /nodes                        - List known nodes")
                print("  /announce                     - Announce presence")
                print("  /quit                         - Exit")

                while True:
                    try:
                        command = input("\nEnter command: ")
                        
                        if command.lower() == '/quit':
                            return
                        elif command.lower().startswith('/send '):
                            filepath = command[6:].strip()
                            self.send_file(filepath)
                        elif command.lower().startswith('/sendto '):
                            parts = command[8:].strip().split(' ')
                            if len(parts) >= 2:
                                filepath = parts[0]
                                target_node = parts[1]
                                self.send_file(filepath, target_node)
                            else:
                                print("Invalid format. Use: /sendto <filepath> <node_id>")
                        elif command.lower() == '/discover':
                            self.discover_nodes()
                        elif command.lower() == '/nodes':
                            self.list_known_nodes()
                        elif command.lower() == '/announce':
                            self.announce_presence()
                        else:
                            print("Invalid command. Available commands:")
                            print("  /send <filepath>              - Send file to all nodes")
                            print("  /sendto <filepath> <node_id>  - Send file to specific node")
                            print("  /discover                     - Discover other nodes")
                            print("  /nodes                        - List known nodes")
                            print("  /announce                     - Announce presence")
                            print("  /quit                         - Exit")
                    except Exception as e:
                        print(f"Error processing command: {e}")

            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except Exception as e:
                print(f"\nError: {e}")
                if not self.reconnect():
                    time.sleep(5)
            finally:
                if self.interface:
                    try:
                        self.interface.close()
                    except:
                        pass

# Change this MAC address for your first T-Beam
MAC_ADDRESS = "08:F9:E0:F6:1A:0E"

if __name__ == "__main__":
    import sys
    node_id = "leaf1"  # Default node ID
    
    # Check if node ID was provided as command line argument
    if len(sys.argv) > 1:
        node_id = sys.argv[1]
        
    transfer = MeshBLEFileTransfer(MAC_ADDRESS, node_id)
    transfer.run()