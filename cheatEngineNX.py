"""
CheatEngineNX: Standalone, shareable Cheat Engine tab for sys-botbase/Nintendo Switch memory editing.

This module provides a Tkinter-based GUI tab for reading, writing, scanning, and managing cheats on a Nintendo Switch running sys-botbase.
It is designed to be easily imported, debugged, and shared as a self-contained component.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import socket
import json
import threading

class CheatEngineTab(tk.Frame):
    """
    Cheat Engine-like tab for sys-botbase memory manipulation on Nintendo Switch.
    Features: fetch base addresses, read/write memory, monitor, freeze, and manage cheats.
    Now includes connect/disconnect/auto-connect logic for standalone use.
    """
    def _reconnect(self):
        """
        Attempt to reconnect by fetching base addresses.
        """
        self.fetch_base_addresses()
        self.reconnect_btn.config(state=tk.DISABLED)
        self.scan_status_label.config(text="Reconnected. Ready.")
        self.output.insert(tk.END, "[Reconnect] Attempted to reconnect to Switch.\n")

    def _pause_keepalive(self):
        """
        Temporarily pause keep-alive during a scan.
        """
        self._keepalive_paused = True
        # If you have a keep-alive manager, call its pause method here

    def _resume_keepalive(self):
        """
        Resume keep-alive after a scan.
        """
        self._keepalive_paused = False
        if self._resume_keepalive_callback:
            self._resume_keepalive_callback()

    def set_resume_keepalive_callback(self, callback):
        """
        Set a callback to resume keep-alive after a scan.
        """
        self._resume_keepalive_callback = callback

    def __init__(self, parent, ip="192.168.1.100", port=6000):
        """
        Initialize the CheatEngineTab with a scrollable frame.
        Args:
            parent: The parent tkinter widget.
            ip (str): The IP address of the Switch running sys-botbase.
            port (int): The port for sys-botbase (default 6000).
        """
        super().__init__(parent)
        self.ip = ip
        self.port = port
        self.main_nso_base = 0
        self.heap_base = 0
        self.monitoring = False
        self.freezing = False
        self.freeze_list = []  # List of (addr, value) tuples
        self.cheats = []  # List of loaded cheats (dicts)
        self._keepalive_paused = False
        self._resume_keepalive_callback = None
        self.connected = False
        # --- Top: Switch connection controls ---
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(top_frame, text="Switch IP:").pack(side=tk.LEFT)
        self.ip_var = tk.StringVar(value=self.ip)
        ip_entry = ttk.Entry(top_frame, textvariable=self.ip_var, width=15)
        ip_entry.pack(side=tk.LEFT, padx=2)
        ttk.Label(top_frame, text="Port:").pack(side=tk.LEFT)
        self.port_var = tk.IntVar(value=self.port)
        port_entry = ttk.Entry(top_frame, textvariable=self.port_var, width=6)
        port_entry.pack(side=tk.LEFT, padx=2)
        self.conn_status = ttk.Label(top_frame, text="Disconnected", foreground="red")
        self.conn_status.pack(side=tk.LEFT, padx=8)
        ttk.Button(top_frame, text="Connect", command=self.connect_switch).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="Disconnect", command=self.disconnect_switch).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="Auto-Connect", command=self.auto_connect_switch).pack(side=tk.LEFT, padx=2)
        # Reconnect button (initially hidden)
        self.reconnect_btn = ttk.Button(self, text="Reconnect", command=self._reconnect, state=tk.DISABLED)
        self.reconnect_btn.pack(side="bottom", pady=4)
        # --- Scrollable Frame Setup ---
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas)
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            )
        )
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        # Mouse wheel scrolling (cross-platform)
        def _on_mousewheel(event):
            if event.delta:
                self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            elif event.num == 4:
                self.canvas.yview_scroll(-3, "units")
            elif event.num == 5:
                self.canvas.yview_scroll(3, "units")
        self.canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.canvas.bind_all("<Button-4>", _on_mousewheel)
        self.canvas.bind_all("<Button-5>", _on_mousewheel)
        self._build_ui(self.scrollable_frame)

    def connect_switch(self):
        """
        Attempt to connect to the Switch by sending a simple command.
        """
        self.ip = self.ip_var.get()
        self.port = int(self.port_var.get())
        try:
            # Try to fetch main NSO base as a connection test
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(2)
                sock.connect((self.ip, self.port))
                sock.sendall(b'getMainNsoBase\n')
                response = sock.recv(1024).decode().strip()
            if response:
                self.conn_status.config(text="Connected", foreground="green")
                self.connected = True
                self.output.insert(tk.END, f"[Switch] Connected to {self.ip}:{self.port}\n")
            else:
                self.conn_status.config(text="No response", foreground="orange")
                self.connected = False
        except Exception as e:
            self.conn_status.config(text="Disconnected", foreground="red")
            self.connected = False
            self.output.insert(tk.END, f"[Switch] Connection failed: {e}\n")

    def disconnect_switch(self):
        """
        Mark as disconnected (no persistent socket to close).
        """
        self.connected = False
        self.conn_status.config(text="Disconnected", foreground="red")
        self.output.insert(tk.END, f"[Switch] Disconnected.\n")

    def auto_connect_switch(self):
        """
        Try to connect every 2 seconds until successful.
        """
        def try_connect():
            if not self.connected:
                self.connect_switch()
                if not self.connected:
                    self.after(2000, try_connect)
        try_connect()

    def _build_ui(self, parent):
        """
        Build the GUI layout for the Cheat Engine tab inside the scrollable frame.
        """
        # --- Base Addresses ---
        base_frame = ttk.LabelFrame(parent, text="Base Addresses")
        base_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(base_frame, text="Fetch Base Addresses", command=self.fetch_base_addresses).pack(side=tk.LEFT, padx=5)
        self.base_label = ttk.Label(base_frame, text="Main NSO: 0x0 | Heap: 0x0")
        self.base_label.pack(side=tk.LEFT, padx=10)

        # --- Memory Input ---
        mem_frame = ttk.LabelFrame(parent, text="Memory Access")
        mem_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(mem_frame, text="Address Type:").grid(row=0, column=0, sticky=tk.W)
        self.addr_type = ttk.Combobox(mem_frame, values=["Absolute", "Main NSO Relative", "Heap Relative"], state="readonly")
        self.addr_type.grid(row=0, column=1, sticky=tk.W)
        self.addr_type.set("Absolute")
        # Add tooltips for address type
        self._add_addr_type_tooltip(self.addr_type)
        ttk.Label(mem_frame, text="Address/Offset (hex):").grid(row=1, column=0, sticky=tk.W)
        self.addr_entry = ttk.Entry(mem_frame)
        self.addr_entry.grid(row=1, column=1, sticky=tk.W)
        # Value Type dropdown replaces Size (bytes)
        ttk.Label(mem_frame, text="Value Type:").grid(row=2, column=0, sticky=tk.W)
        value_size_options = [
            "8 bit unsigned", "8 bit signed",
            "16 bit unsigned", "16 bit signed",
            "32 bit unsigned", "32 bit signed", "32 bit float",
            "64 bit unsigned", "64 bit signed", "64 bit float"
        ]
        self.mem_value_type_combo = ttk.Combobox(mem_frame, values=value_size_options, state="readonly", width=16)
        self.mem_value_type_combo.grid(row=2, column=1, sticky=tk.W)
        self.mem_value_type_combo.set("32 bit unsigned")
        # Tooltip/label for value type
        self.mem_value_type_label = ttk.Label(mem_frame, text="Size set to 4 bytes for 32-bit unsigned integer.", foreground="#007700", font=(None, 8, "italic"))
        self.mem_value_type_label.grid(row=2, column=2, sticky=tk.W)
        def on_mem_value_type_change(event=None):
            size = self._get_type_size(self.mem_value_type_combo.get())
            self.mem_value_type_label.config(text=f"Size set to {size} bytes for {self.mem_value_type_combo.get()}.")
        self.mem_value_type_combo.bind("<<ComboboxSelected>>", on_mem_value_type_change)
        on_mem_value_type_change()
        ttk.Label(mem_frame, text="Value (hex):").grid(row=3, column=0, sticky=tk.W)
        self.value_entry = ttk.Entry(mem_frame)
        self.value_entry.grid(row=3, column=1, sticky=tk.W)
        ttk.Button(mem_frame, text="Read Memory", command=self.read_memory).grid(row=4, column=0, pady=2)
        ttk.Button(mem_frame, text="Write Memory", command=self.write_memory).grid(row=4, column=1, pady=2)

        # --- Monitoring and Freezing ---
        mon_frame = ttk.LabelFrame(parent, text="Monitor & Freeze")
        mon_frame.pack(fill=tk.X, padx=10, pady=5)
        self.monitor_var = tk.BooleanVar()
        ttk.Checkbutton(mon_frame, text="Monitor in Real-Time", variable=self.monitor_var, command=self.toggle_monitor).pack(side=tk.LEFT, padx=5)
        self.freeze_var = tk.BooleanVar()
        ttk.Checkbutton(mon_frame, text="Freeze Value", variable=self.freeze_var, command=self.toggle_freeze).pack(side=tk.LEFT, padx=5)
        ttk.Button(mon_frame, text="Add to Freeze List", command=self.add_to_freeze_list).pack(side=tk.LEFT, padx=5)
        ttk.Button(mon_frame, text="Remove from Freeze List", command=self.remove_from_freeze_list).pack(side=tk.LEFT, padx=5)
        self.freeze_listbox = tk.Listbox(mon_frame, height=3, width=50)
        self.freeze_listbox.pack(side=tk.LEFT, padx=5)

        # --- Output ---
        out_frame = ttk.LabelFrame(parent, text="Output / Log")
        out_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.output = tk.Text(out_frame, height=10, width=80)
        self.output.pack(fill=tk.BOTH, expand=True)

        # --- Cheat Management ---
        cheat_frame = ttk.LabelFrame(parent, text="Cheat Management")
        cheat_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(cheat_frame, text="Save Cheats", command=self.save_cheats).pack(side=tk.LEFT, padx=5)
        ttk.Button(cheat_frame, text="Load Cheats", command=self.load_cheats).pack(side=tk.LEFT, padx=5)
        self.cheat_listbox = tk.Listbox(cheat_frame, height=3, width=50)
        self.cheat_listbox.pack(side=tk.LEFT, padx=5)
        ttk.Button(cheat_frame, text="Apply Selected Cheat", command=self.apply_selected_cheat).pack(side=tk.LEFT, padx=5)
        ttk.Button(cheat_frame, text="Remove Selected Cheat", command=self.remove_selected_cheat).pack(side=tk.LEFT, padx=5)

        # --- Memory Scanner ---
        scanner_frame = ttk.LabelFrame(parent, text="Memory Scanner")
        scanner_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(scanner_frame, text="Address Type:").grid(row=0, column=0, sticky=tk.W)
        self.scan_addr_type = ttk.Combobox(scanner_frame, values=["Absolute", "Main NSO Relative", "Heap Relative"], state="readonly", width=18)
        self.scan_addr_type.grid(row=0, column=1, sticky=tk.W)
        self.scan_addr_type.set("Main NSO Relative")
        # Add tooltips for scanner address type
        self._add_addr_type_tooltip(self.scan_addr_type)
        ttk.Label(scanner_frame, text="Start Offset (hex):").grid(row=1, column=0, sticky=tk.W)
        self.scan_start_entry = ttk.Entry(scanner_frame, width=12)
        self.scan_start_entry.grid(row=1, column=1, sticky=tk.W)
        self.scan_start_entry.insert(0, "0x0")
        ttk.Label(scanner_frame, text="End Offset (hex):").grid(row=2, column=0, sticky=tk.W)
        self.scan_end_entry = ttk.Entry(scanner_frame, width=12)
        self.scan_end_entry.grid(row=2, column=1, sticky=tk.W)
        self.scan_end_entry.insert(0, "0x1000000")
        self.scan_mb_entry = ttk.Entry(scanner_frame, width=6)
        self.scan_mb_entry.grid(row=2, column=2, sticky=tk.W)
        self.scan_mb_entry.insert(0, "16")
        self.scan_end_entry.bind('<KeyRelease>', self._sync_mb_from_end)
        self.scan_mb_entry.bind('<KeyRelease>', self._sync_end_from_mb)
        ttk.Label(scanner_frame, text="Chunk Size (hex):").grid(row=3, column=0, sticky=tk.W)
        self.scan_chunk_entry = ttk.Entry(scanner_frame, width=8)
        self.scan_chunk_entry.grid(row=3, column=1, sticky=tk.W)
        self.scan_chunk_entry.insert(0, "0x1000")
        ttk.Label(scanner_frame, text="Value to Search:").grid(row=4, column=0, sticky=tk.W)
        self.scan_value_entry = ttk.Entry(scanner_frame, width=12)
        self.scan_value_entry.grid(row=4, column=1, sticky=tk.W)
        self.scan_value_entry.insert(0, "100")
        ttk.Label(scanner_frame, text="Value Size:").grid(row=4, column=2, sticky=tk.W)
        value_size_options = [
            "8 bit unsigned", "8 bit signed",
            "16 bit unsigned", "16 bit signed",
            "32 bit unsigned", "32 bit signed", "32 bit float",
            "64 bit unsigned", "64 bit signed", "64 bit float"
        ]
        self.scan_size_combo = ttk.Combobox(scanner_frame, values=value_size_options, state="readonly", width=16)
        self.scan_size_combo.grid(row=4, column=3, sticky=tk.W)
        self.scan_size_combo.set("32 bit unsigned")

        # Comparison dropdown and extra value entry for 'Between'
        ttk.Label(scanner_frame, text="Comparison:").grid(row=4, column=4, sticky=tk.W)
        self.scan_comparison_combo = ttk.Combobox(scanner_frame, values=[
            "Exact Value", "Greater Than", "Less Than", "Between", "Increased Value", "Decreased Value", "Unknown Initial Value"
        ], state="readonly", width=18)
        self.scan_comparison_combo.grid(row=4, column=5, sticky=tk.W)
        self.scan_comparison_combo.set("Exact Value")
        self.scan_value2_entry = ttk.Entry(scanner_frame, width=12)
        self.scan_value2_entry.grid(row=4, column=6, sticky=tk.W)
        self.scan_value2_entry.grid_remove()  # Only show for 'Between'
        def on_comparison_change(event=None):
            if self.scan_comparison_combo.get() == "Between":
                self.scan_value2_entry.grid()
            else:
                self.scan_value2_entry.grid_remove()
        self.scan_comparison_combo.bind("<<ComboboxSelected>>", on_comparison_change)
        ttk.Button(scanner_frame, text="First Scan", command=self.first_scan).grid(row=5, column=0, pady=2)
        ttk.Button(scanner_frame, text="Next Scan", command=self.next_scan).grid(row=5, column=1, pady=2)
        self.scan_results_listbox = tk.Listbox(scanner_frame, height=5, width=60)
        self.scan_results_listbox.grid(row=6, column=0, columnspan=4, pady=2)
        ttk.Button(scanner_frame, text="Add to Monitor/Freeze/Cheat", command=self.add_scan_result_to_cheat).grid(row=7, column=0, columnspan=2, pady=2)
        # Progress bar and status label
        self.scan_progress = ttk.Progressbar(scanner_frame, orient="horizontal", length=300, mode="determinate")
        self.scan_progress.grid(row=8, column=0, columnspan=2, pady=2, sticky=tk.W)
        self.scan_status_label = ttk.Label(scanner_frame, text="Idle")
        self.scan_status_label.grid(row=8, column=2, columnspan=2, sticky=tk.W)
        self._scan_cancelled = False
        self.cancel_scan_btn = ttk.Button(scanner_frame, text="Cancel Scan", command=self.cancel_scan, state=tk.DISABLED)
        self.cancel_scan_btn.grid(row=9, column=0, pady=2, sticky=tk.W)
        self._scan_results = []  # List of (address, value)
        self._last_scan_value = None

    def send_command(self, command):
        """
        Send a command to sys-botbase over TCP and return the response.
        Args:
            command (str): The command string to send.
        Returns:
            str or None: The response from sys-botbase, or None on error.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(2)
                sock.connect((self.ip, self.port))
                sock.sendall(command.encode() + b'\n')
                response = sock.recv(1024).decode().strip()
            return response
        except Exception as e:
            self.output.insert(tk.END, f"[ERROR] {e}\n")
            return None

    def fetch_base_addresses(self):
        """
        Fetch and display the main NSO base and heap base addresses from the Switch.
        """
        try:
            main_nso = self.send_command("getMainNsoBase")
            heap = self.send_command("getHeapBase")
            self.main_nso_base = int(main_nso, 16) if main_nso else 0
            self.heap_base = int(heap, 16) if heap else 0
            self.base_label.config(text=f"Main NSO: {hex(self.main_nso_base)} | Heap: {hex(self.heap_base)}")
            self.output.insert(tk.END, f"Main NSO Base: {hex(self.main_nso_base)}\nHeap Base: {hex(self.heap_base)}\n")
        except Exception as e:
            self.output.insert(tk.END, f"Error fetching base addresses: {e}\n")

    def calculate_address(self, addr_type=None, offset=None):
        """
        Calculate the absolute address based on the selected address type and offset.
        Args:
            addr_type (str, optional): Address type (Absolute, Main NSO Relative, Heap Relative).
            offset (str or int, optional): Offset in hex or int.
        Returns:
            int or None: The calculated address, or None if invalid.
        """
        addr_type = addr_type or self.addr_type.get()
        try:
            offset = int(offset if offset is not None else self.addr_entry.get(), 16)
        except ValueError:
            self.output.insert(tk.END, "Invalid address/offset\n")
            return None
        if addr_type == "Absolute":
            return offset
        elif addr_type == "Main NSO Relative":
            if self.main_nso_base == 0:
                self.output.insert(tk.END, "Main NSO base not set\n")
                return None
            return self.main_nso_base + offset
        elif addr_type == "Heap Relative":
            if self.heap_base == 0:
                self.output.insert(tk.END, "Heap base not set\n")
                return None
            return self.heap_base + offset

    def _get_type_size(self, type_str):
        """
        Return the size in bytes for a given value type string.
        """
        if "8 bit" in type_str:
            return 1
        elif "16 bit" in type_str:
            return 2
        elif "32 bit" in type_str:
            return 4
        elif "64 bit" in type_str:
            return 8
        return 4

    def read_memory(self):
        """
        Read memory from the calculated address and display the result in the output area.
        """
        addr = self.calculate_address()
        if addr is None:
            return
        try:
            size = self._get_type_size(self.mem_value_type_combo.get())
            response = self.send_command(f"peek {hex(addr)[2:]} {size}")
            self.output.insert(tk.END, f"Read {size} bytes from {hex(addr)}: {response}\n")
        except Exception:
            self.output.insert(tk.END, "Invalid size\n")

    def write_memory(self):
        """
        Write the specified value to the calculated address in memory.
        """
        addr = self.calculate_address()
        if addr is None:
            return
        value = self.value_entry.get().replace(" ", "")
        self.send_command(f"poke {hex(addr)[2:]} {value}")
        self.output.insert(tk.END, f"Wrote {value} to {hex(addr)}\n")

    def toggle_monitor(self):
        """
        Enable or disable real-time memory monitoring.
        """
        self.monitoring = self.monitor_var.get()
        if self.monitoring:
            self.update_monitor()

    def update_monitor(self):
        """
        Periodically read memory if monitoring is enabled.
        """
        if not self.monitoring:
            return
        self.read_memory()
        self.after(1000, self.update_monitor)

    def toggle_freeze(self):
        """
        Enable or disable freezing of memory values in the freeze list.
        """
        self.freezing = self.freeze_var.get()
        if self.freezing:
            self.update_freeze()

    def update_freeze(self):
        """
        Periodically write frozen values to their addresses if freezing is enabled.
        """
        if not self.freezing:
            return
        for addr, value in self.freeze_list:
            self.send_command(f"poke {hex(addr)[2:]} {value}")
        self.after(100, self.update_freeze)

    def add_to_freeze_list(self):
        """
        Add the current address and value to the freeze list and update the listbox.
        """
        addr = self.calculate_address()
        value = self.value_entry.get().replace(" ", "")
        if addr is not None and value:
            self.freeze_list.append((addr, value))
            self.freeze_listbox.insert(tk.END, f"{hex(addr)}: {value}")
            self.output.insert(tk.END, f"Added freeze: {hex(addr)} = {value}\n")

    def remove_from_freeze_list(self):
        """
        Remove the selected address/value from the freeze list and update the listbox.
        """
        sel = self.freeze_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.freeze_listbox.delete(idx)
        del self.freeze_list[idx]
        self.output.insert(tk.END, f"Removed freeze at index {idx}\n")

    def save_cheats(self):
        """
        Save the current list of cheats to a JSON file.
        """
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON Files", "*.json")])
        if not path:
            return
        with open(path, 'w') as f:
            json.dump(self.cheats, f, indent=2)
        self.output.insert(tk.END, f"Saved cheats to {path}\n")

    def load_cheats(self):
        """
        Load cheats from a JSON file and display them in the listbox.
        """
        path = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
        if not path:
            return
        with open(path, 'r') as f:
            cheats = json.load(f)
        self.cheat_listbox.delete(0, tk.END)
        self.cheats = cheats
        for cheat in cheats:
            self.cheat_listbox.insert(tk.END, self._cheat_human_label(cheat))
        self.output.insert(tk.END, f"Loaded {len(cheats)} cheats from {path}\n")

    def apply_selected_cheat(self):
        """
        Apply the selected cheat by writing its value to the calculated address.
        """
        sel = self.cheat_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        cheat = self.cheats[idx]
        addr = self.calculate_address(cheat["address_type"], cheat["offset"])
        value = cheat["value"]
        self.send_command(f"poke {hex(addr)[2:]} {value}")
        self.output.insert(tk.END, f"Applied cheat: {cheat['description']}\n")

    def remove_selected_cheat(self):
        """
        Remove the selected cheat from the list and update the listbox.
        """
        sel = self.cheat_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.cheat_listbox.delete(idx)
        del self.cheats[idx]
        self.output.insert(tk.END, f"Removed cheat at index {idx}\n")

    def _cheat_human_label(self, cheat):
        """
        Generate a human-readable label for a cheat dict.
        Args:
            cheat (dict): The cheat dictionary.
        Returns:
            str: Human-readable label.
        """
        desc = cheat.get("description", "(No Description)")
        addr_type = cheat.get("address_type", "?")
        offset = cheat.get("offset", "?")
        value = cheat.get("value", "?")
        return f"{desc} ({addr_type} + {offset}) = {value}"

    def _sync_mb_from_end(self, event=None):
        """
        Sync the MB field when the end offset is changed.
        """
        try:
            start = int(self.scan_start_entry.get(), 16)
            end = int(self.scan_end_entry.get(), 16)
            mb = max(0, (end - start) // (1024 * 1024))
            if str(mb) != self.scan_mb_entry.get():
                self.scan_mb_entry.delete(0, tk.END)
                self.scan_mb_entry.insert(0, str(mb))
        except Exception:
            pass

    def _sync_end_from_mb(self, event=None):
        """
        Sync the end offset field when the MB field is changed.
        """
        try:
            start = int(self.scan_start_entry.get(), 16)
            mb = int(self.scan_mb_entry.get())
            end = start + mb * 1024 * 1024
            if hex(end) != self.scan_end_entry.get():
                self.scan_end_entry.delete(0, tk.END)
                self.scan_end_entry.insert(0, hex(end))
        except Exception:
            pass

    def first_scan(self):
        """
        Perform the first memory scan for the specified value in the given range.
        """
        self._scan_cancelled = False
        self.cancel_scan_btn.config(state=tk.NORMAL)
        self._scan_results = []
        self.scan_results_listbox.delete(0, tk.END)
        value_str = self.scan_value_entry.get().strip()
        value_size = self._get_scan_value_size()
        value_type = self._get_scan_value_type()
        value = self._parse_scan_value(value_str, value_size, value_type)
        if value is None:
            self.output.insert(tk.END, "[Scanner] Invalid value to search.\n")
            return
        self._last_scan_value = value
        start_addr = self._get_scan_base() + int(self.scan_start_entry.get(), 16)
        end_addr = self._get_scan_base() + int(self.scan_end_entry.get(), 16)
        chunk_size = int(self.scan_chunk_entry.get(), 16)
        total_chunks = max(1, (end_addr - start_addr) // chunk_size)
        def scan_worker():
            chunk_idx = 0
            def update_progress():
                percent = int(100 * chunk_idx / total_chunks)
                self.scan_progress['value'] = chunk_idx
                self.scan_status_label.config(text=f"Scanning... {percent}% complete")
            self.scan_progress['maximum'] = total_chunks
            self.scan_progress['value'] = 0
            self.scan_status_label.config(text="Scanning... 0% complete")
            self.output.insert(tk.END, f"[Scanner] Scanning {hex(start_addr)} to {hex(end_addr)} for {value} ({self.scan_size_combo.get()})\n")
            # Parse value2 for 'Between' if needed
            value2 = None
            comparison = self.scan_comparison_combo.get()
            if comparison == "Between":
                value2_str = self.scan_value2_entry.get().strip()
                value2 = self._parse_scan_value(value2_str, value_size, value_type)
                if value2 is None:
                    self.after(0, lambda: self.output.insert(tk.END, "[Scanner] Invalid second value for 'Between'.\n"))
                    self.after(0, lambda: self.scan_status_label.config(text="Scan error"))
                    self.after(0, lambda: self.cancel_scan_btn.config(state=tk.DISABLED))
                    return
            for addr in range(start_addr, end_addr, chunk_size):
                if self._scan_cancelled:
                    self.after(0, lambda: self.scan_status_label.config(text="Scan cancelled"))
                    return
                read_size = min(chunk_size, end_addr - addr)
                data = self.send_command(f"peek {hex(addr)[2:]} {read_size}")
                if data:
                    matches = self._find_value_in_bytes(data, value, value_size, value_type, addr, self._get_scan_base(), value2, comparison)
                    for m_addr, m_val, rel_offset in matches:
                        self._scan_results.append((m_addr, m_val, rel_offset))
                        self.after(0, lambda m_addr=m_addr, rel_offset=rel_offset, m_val=m_val: self.scan_results_listbox.insert(tk.END, f"{hex(m_addr)} (offset +{hex(rel_offset)}): {m_val}"))
                chunk_idx += 1
                self.after(0, update_progress)
            self.after(0, lambda: self.scan_status_label.config(text="Scan complete"))
            self.after(0, lambda: self.cancel_scan_btn.config(state=tk.DISABLED))
            self.output.insert(tk.END, f"[Scanner] Found {len(self._scan_results)} matches.\n")
        threading.Thread(target=scan_worker, daemon=True).start()

    def next_scan(self):
        """
        Refine the scan results by searching for the new value among previous matches.
        """
        value_str = self.scan_value_entry.get().strip()
        value_size = self._get_scan_value_size()
        value_type = self._get_scan_value_type()
        value = self._parse_scan_value(value_str, value_size, value_type)
        if value is None:
            self.output.insert(tk.END, "[Scanner] Invalid value to search.\n")
            return
        self._last_scan_value = value
        new_results = []
        self.scan_results_listbox.delete(0, tk.END)
        for addr, _, rel_offset in self._scan_results:
            data = self.send_command(f"peek {hex(addr)[2:]} {value_size}")
            if not data:
                continue
            matches = self._find_value_in_bytes(data, value, value_size, value_type, addr, self._get_scan_base())
            for m_addr, m_val, rel_offset in matches:
                new_results.append((m_addr, m_val, rel_offset))
                self.scan_results_listbox.insert(tk.END, f"{hex(m_addr)} (offset +{hex(rel_offset)}): {m_val}")
        self._scan_results = new_results
        self.output.insert(tk.END, f"[Scanner] Refined to {len(self._scan_results)} matches.\n")

    def _get_scan_base(self):
        """
        Get the base address for scanning based on the selected address type.
        """
        t = self.scan_addr_type.get()
        if t == "Absolute":
            return 0
        elif t == "Main NSO Relative":
            return self.main_nso_base
        elif t == "Heap Relative":
            return self.heap_base
        return 0

    def _get_scan_value_size(self):
        """
        Get the value size in bytes for the scanner (8, 16, 32, 64 bit, signed/unsigned/float).
        """
        size_str = self.scan_size_combo.get()
        if "8 bit" in size_str:
            return 1
        elif "16 bit" in size_str:
            return 2
        elif "32 bit" in size_str:
            return 4
        elif "64 bit" in size_str:
            return 8
        return 4

    def _get_scan_value_type(self):
        """
        Get the value type for the scanner: 'int', 'float', 'signed', 'unsigned'.
        """
        size_str = self.scan_size_combo.get()
        if "float" in size_str:
            return 'float'
        elif "signed" in size_str:
            return 'signed'
        elif "unsigned" in size_str:
            return 'unsigned'
        return 'unsigned'

    def _parse_scan_value(self, value_str, value_size, value_type):
        """
        Parse the value to search for, supporting decimal, hex, float, signed/unsigned.
        """
        try:
            import struct
            if value_type == 'float':
                # 32 or 64 bit float
                if value_size == 4:
                    if value_str.lower().startswith("0x"):
                        as_int = int(value_str, 16)
                        return struct.unpack('<f', as_int.to_bytes(4, 'little'))[0]
                    return float(value_str)
                elif value_size == 8:
                    if value_str.lower().startswith("0x"):
                        as_int = int(value_str, 16)
                        return struct.unpack('<d', as_int.to_bytes(8, 'little'))[0]
                    return float(value_str)
            else:
                if value_str.lower().startswith("0x"):
                    return int(value_str, 16)
                return int(value_str)
        except Exception:
            return None

    def _find_value_in_bytes(self, data, value, value_size, value_type, base_addr, scan_base, value2=None, comparison="Exact Value"):
        """
        Find all occurrences of the value in the given hex string data, using the selected comparison.
        Returns a list of (address, value, relative_offset) tuples.
        Handles little-endian for both int and float, signed/unsigned.
        """
        import binascii
        import struct
        try:
            # Remove spaces and newlines, convert to bytes
            data_bytes = binascii.unhexlify(data.replace(" ", "").replace("\n", ""))
        except Exception:
            return []
        matches = []
        for i in range(0, len(data_bytes) - value_size + 1):
            chunk = data_bytes[i:i+value_size]
            # Parse value from chunk
            try:
                if value_type == 'float':
                    if value_size == 4:
                        chunk_val = struct.unpack('<f', chunk)[0]
                    elif value_size == 8:
                        chunk_val = struct.unpack('<d', chunk)[0]
                    else:
                        continue
                elif value_type == 'signed':
                    chunk_val = int.from_bytes(chunk, byteorder='little', signed=True)
                else:  # unsigned
                    chunk_val = int.from_bytes(chunk, byteorder='little', signed=False)
            except Exception:
                continue
            # Comparison logic
            match = False
            if comparison == "Exact Value":
                if value_type == 'float':
                    match = abs(chunk_val - value) < 1e-6
                else:
                    match = chunk_val == value
            elif comparison == "Greater Than":
                match = chunk_val > value
            elif comparison == "Less Than":
                match = chunk_val < value
            elif comparison == "Between" and value2 is not None:
                match = value <= chunk_val <= value2 or value2 <= chunk_val <= value
            # TODO: Implement Increased/Decreased/Unknown for next/advanced scans
            if match:
                abs_addr = base_addr + i
                rel_offset = abs_addr - scan_base
                matches.append((abs_addr, chunk_val, rel_offset))
        return matches

    def add_scan_result_to_cheat(self):
        """
        Add the selected scan result to the cheat list as a new cheat entry.
        """
        sel = self.scan_results_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        addr, value, rel_offset = self._scan_results[idx]
        # Determine address type and offset
        addr_type = self.scan_addr_type.get()
        base = self._get_scan_base()
        offset = addr - base
        value_type = self._get_scan_value_type()
        value_size = self._get_scan_value_size()
        value_type_str = self.scan_size_combo.get()
        if value_type == 'float':
            import struct
            if value_size == 4:
                value_bytes = struct.pack('<f', value)
            elif value_size == 8:
                value_bytes = struct.pack('<d', value)
            else:
                value_bytes = b''
            value_hex = value_bytes.hex()
        else:
            value_hex = hex(value)[2:].zfill(value_size*2)
        cheat = {
            "description": f"ScanResult {hex(addr)}",
            "address_type": addr_type,
            "offset": hex(offset),
            "value": value_hex
        }
        self.cheats.append(cheat)
        self.cheat_listbox.insert(tk.END, self._cheat_human_label(cheat))
        self.output.insert(tk.END, f"[Scanner] Added {hex(addr)} to cheats.\n")
        # Auto-populate Memory Access section
        self.addr_type.set(addr_type)
        self.addr_entry.delete(0, tk.END)
        self.addr_entry.insert(0, hex(offset))
        self.mem_value_type_combo.set(value_type_str)
        self.value_entry.delete(0, tk.END)
        if value_type == 'float':
            self.value_entry.insert(0, str(value))
        else:
            self.value_entry.insert(0, str(value))
        # Update size label
        size = self._get_type_size(value_type_str)
        self.mem_value_type_label.config(text=f"Size set to {size} bytes for {value_type_str}.")

    def cancel_scan(self):
        """
        Set the scan cancelled flag to True to stop an ongoing scan.
        """
        self._scan_cancelled = True
        self.scan_status_label.config(text="Scan cancelled")
        self.cancel_scan_btn.config(state=tk.DISABLED)

    def _add_addr_type_tooltip(self, combobox):
        """
        Attach tooltips to the address type combobox, showing definitions and pros/cons for each type.
        """
        tooltip_texts = {
            "Absolute": (
                "Absolute Address\n"
                "Definition: A fixed memory address in the Switch's RAM, specified directly (e.g., 0x65ffc01234).\n"
                "Use Case: Used when you know the exact physical address in memory where a value (like health) is stored.\n"
                "Pros: Precise if you have the exact address from a reliable source.\n"
                "Cons: Hard to determine without prior knowledge or scanning. Can become invalid if the game restarts or memory layout changes.\n"
                "Example: Reading health at 0x65ffc01234 directly."
            ),
            "Main NSO Relative": (
                "Main NSO Relative\n"
                "Definition: An offset from the Main NSO Base, which is the starting address of the game's main executable module (NSO file) in RAM.\n"
                "Use Case: Most static game data (e.g., health, items) is stored relative to the main NSO base.\n"
                "Pros: Stable across game restarts if the NSO base is fetched correctly. Commonly used in cheat engines because offsets are portable.\n"
                "Cons: Requires fetching the Main NSO Base first, and the offset must be valid for the specific game version.\n"
                "Example: Health at offset 0x1234 from Main NSO Base 0x65ffc00000."
            ),
            "Heap Relative": (
                "Heap Relative\n"
                "Definition: An offset from the Heap Base, which is the starting address of the heap region where dynamic allocations are stored.\n"
                "Use Case: Used for dynamic data that changes location between sessions (e.g., enemy positions, temporary player stats).\n"
                "Pros: Useful for tracking runtime-allocated data.\n"
                "Cons: The heap base and offsets can change each time the game runs. Harder to create persistent cheats without pointer chains."
            ),
        }
        class ToolTip:
            """
            Simple tooltip for tkinter widgets.
            """
            def __init__(self, widget, text):
                self.widget = widget
                self.text = text
                self.tipwindow = None
                self.widget.bind("<Enter>", self.show_tip)
                self.widget.bind("<Leave>", self.hide_tip)
            def show_tip(self, event=None):
                if self.tipwindow or not self.text:
                    return
                x, y, cx, cy = self.widget.bbox("insert")
                x = x + self.widget.winfo_rootx() + 30
                y = y + self.widget.winfo_rooty() + 20
                self.tipwindow = tw = tk.Toplevel(self.widget)
                tw.wm_overrideredirect(True)
                tw.wm_geometry(f"+{x}+{y}")
                label = tk.Label(tw, text=self.text, justify=tk.LEFT, background="#ffffe0", relief=tk.SOLID, borderwidth=1, font=(None, 9))
                label.pack(ipadx=1)
            def hide_tip(self, event=None):
                tw = self.tipwindow
                self.tipwindow = None
                if tw:
                    tw.destroy()
        # Attach tooltip to the combobox itself (shows summary of all types)
        summary = "Choose how the address/offset is interpreted.\n\n"
        for k, v in tooltip_texts.items():
            summary += f"{k}:\n  {v.split('Definition:')[1].split('Use Case:')[0].strip()}\n"
        ToolTip(combobox, summary)
        # Attach tooltips to dropdown menu items (if possible)
        # Tkinter does not support per-item tooltips in Combobox, so show summary on hover and detailed info on selection change
        def on_select(event):
            val = combobox.get()
            if val in tooltip_texts:
                self.output.insert(tk.END, f"[Info] {tooltip_texts[val]}\n")
        combobox.bind("<<ComboboxSelected>>", on_select)

# --- ManualTab and supporting stubs for standalone use ---
class SwitchService:
    def connect(self):
        pass
    def disconnect(self):
        pass

class ManualController:
    def __init__(self, switch_service):
        self.switch_service = switch_service
    def press_button(self, button):
        pass
    def move_stick(self, stick, x, y, duration):
        pass

class ManualTab(ttk.Frame):
    def __init__(self, parent, switch_service):
        super().__init__(parent)
        self.switch_service = switch_service
        self.controller = ManualController(self.switch_service)
        self._build_ui()

    def _build_ui(self):
        # Buttons
        btn_frame = ttk.LabelFrame(self, text="Buttons")
        btn_frame.pack(padx=10, pady=5, fill=tk.X)
        buttons = [
            "A", "B", "X", "Y", "L", "R", "ZL", "ZR",
            "PLUS", "MINUS", "HOME", "CAPTURE", "LSTICK", "RSTICK"
        ]
        for i, btn in enumerate(buttons):
            ttk.Button(btn_frame, text=btn, width=6, command=lambda b=btn: self._press_button(b)).grid(row=0, column=i, padx=2, pady=2)

        # D-Pad
        dpad_frame = ttk.LabelFrame(self, text="D-Pad")
        dpad_frame.pack(padx=10, pady=5, fill=tk.X)
        ttk.Button(dpad_frame, text="Up", command=lambda: self._press_button("DUP")).grid(row=0, column=1)
        ttk.Button(dpad_frame, text="Left", command=lambda: self._press_button("DLEFT")).grid(row=1, column=0)
        ttk.Button(dpad_frame, text="Right", command=lambda: self._press_button("DRIGHT")).grid(row=1, column=2)
        ttk.Button(dpad_frame, text="Down", command=lambda: self._press_button("DDOWN")).grid(row=2, column=1)

        # Left Stick
        lstick_frame = ttk.LabelFrame(self, text="Left Stick")
        lstick_frame.pack(padx=10, pady=5, fill=tk.X)
        ttk.Button(lstick_frame, text="Up", command=lambda: self._move_stick("LEFT", 0x0000, 0x7FFF)).grid(row=0, column=1)
        ttk.Button(lstick_frame, text="Left", command=lambda: self._move_stick("LEFT", -0x7FFF, 0x0000)).grid(row=1, column=0)
        ttk.Button(lstick_frame, text="Center", command=lambda: self._press_button("LSTICK")).grid(row=1, column=1)
        ttk.Button(lstick_frame, text="Right", command=lambda: self._move_stick("LEFT", 0x7FFF, 0x0000)).grid(row=1, column=2)
        ttk.Button(lstick_frame, text="Down", command=lambda: self._move_stick("LEFT", 0x0000, -0x7FFF)).grid(row=2, column=1)

        # Right Stick
        rstick_frame = ttk.LabelFrame(self, text="Right Stick")
        rstick_frame.pack(padx=10, pady=5, fill=tk.X)
        ttk.Button(rstick_frame, text="Up", command=lambda: self._move_stick("RIGHT", 0x0000, 0x7FFF)).grid(row=0, column=1)
        ttk.Button(rstick_frame, text="Left", command=lambda: self._move_stick("RIGHT", -0x7FFF, 0x0000)).grid(row=1, column=0)
        ttk.Button(rstick_frame, text="Center", command=lambda: self._press_button("RSTICK")).grid(row=1, column=1)
        ttk.Button(rstick_frame, text="Right", command=lambda: self._move_stick("RIGHT", 0x7FFF, 0x0000)).grid(row=1, column=2)
        ttk.Button(rstick_frame, text="Down", command=lambda: self._move_stick("RIGHT", 0x0000, -0x7FFF)).grid(row=2, column=1)

        ttk.Button(self, text="Connect to Switch", command=self._connect).pack(pady=5)
        ttk.Button(self, text="Disconnect", command=self._disconnect).pack(pady=5)

    def _press_button(self, button):
        try:
            self.controller.press_button(button)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to send button: {e}")

    def _move_stick(self, stick, x, y):
        try:
            self.controller.move_stick(stick, x, y, 0.3)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to move stick: {e}")

    def _connect(self):
        try:
            self.switch_service.connect()
            messagebox.showinfo("Switch", "Connected to Switch!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to connect: {e}")

    def _disconnect(self):
        try:
            self.switch_service.disconnect()
            messagebox.showinfo("Switch", "Disconnected from Switch.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to disconnect: {e}")

# --- Main window with tabs ---
if __name__ == "__main__":
    root = tk.Tk()
    root.title("CheatEngineNX - Standalone Cheat Engine for sys-botbase/Switch")
    notebook = ttk.Notebook(root)
    cheat_tab = CheatEngineTab(notebook)
    manual_tab = ManualTab(notebook, SwitchService())
    notebook.add(cheat_tab, text="Cheat Engine")
    notebook.add(manual_tab, text="Manual Control")
    notebook.pack(fill="both", expand=True)
    root.mainloop() 