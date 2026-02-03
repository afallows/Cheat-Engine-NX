"""
CheatEngineNX Enhanced: Standalone, shareable Cheat Engine tab for sys-botbase/Nintendo Switch memory editing.

This module provides a Tkinter-based GUI tab for reading, writing, scanning, and managing cheats on a Nintendo Switch running sys-botbase.
Enhanced with improved scanning, pointer support, better performance, and comprehensive error handling.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import socket
import json
import threading
import struct
import binascii
from typing import Optional, List, Tuple, Dict, Any

class CheatEngineTab(tk.Frame):
    """
    Enhanced Cheat Engine-like tab for sys-botbase memory manipulation on Nintendo Switch.
    Features: fetch base addresses, read/write memory, monitor, freeze, pointer scanning, and manage cheats.
    """
    
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
        self.freeze_list = []  # List of (addr, value, size) tuples
        self.cheats = []  # List of loaded cheats (dicts)
        self._keepalive_paused = False
        self._resume_keepalive_callback = None
        self.connected = False
        self._scan_results = []  # List of (addr, value, prev_value, rel_offset)
        self._last_scan_value = None
        self._is_unknown_scan = False
        self._scan_cancelled = False
        self._base_cache = {}  # Cache for base addresses
        self.debug_verbose = tk.BooleanVar(value=True)  # Initialize here for send_command
        
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
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
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

    def _reconnect(self):
        """Attempt to reconnect by fetching base addresses."""
        self.fetch_base_addresses()
        self.reconnect_btn.config(state=tk.DISABLED)
        self.scan_status_label.config(text="Reconnected. Ready.")
        self.output.insert(tk.END, "[Reconnect] Attempted to reconnect to Switch.\n")

    def _pause_keepalive(self):
        """Temporarily pause keep-alive during a scan."""
        self._keepalive_paused = True

    def _resume_keepalive(self):
        """Resume keep-alive after a scan."""
        self._keepalive_paused = False
        if self._resume_keepalive_callback:
            self._resume_keepalive_callback()

    def set_resume_keepalive_callback(self, callback):
        """Set a callback to resume keep-alive after a scan."""
        self._resume_keepalive_callback = callback

    def connect_switch(self):
        """Attempt to connect to the Switch by sending a simple command."""
        self.ip = self.ip_var.get()
        self.port = int(self.port_var.get())
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(5)
                sock.connect((self.ip, self.port))
                sock.sendall(b'getMainNsoBase\n')
                response = sock.recv(1024).decode().strip()
            
            if response:
                self.conn_status.config(text="Connected", foreground="green")
                self.connected = True
                self.output.insert(tk.END, f"[Switch] Connected to {self.ip}:{self.port}\n")
                # Auto-fetch base addresses on connect
                self.fetch_base_addresses()
            else:
                self.conn_status.config(text="No response", foreground="orange")
                self.connected = False
        except Exception as e:
            self.conn_status.config(text="Disconnected", foreground="red")
            self.connected = False
            self.output.insert(tk.END, f"[Switch] Connection failed: {e}\n")

    def disconnect_switch(self):
        """Mark as disconnected."""
        self.connected = False
        self.conn_status.config(text="Disconnected", foreground="red")
        self.output.insert(tk.END, f"[Switch] Disconnected.\n")

    def auto_connect_switch(self):
        """Try to connect every 2 seconds until successful."""
        def try_connect():
            if not self.connected:
                self.connect_switch()
                if not self.connected:
                    self.after(2000, try_connect)
        try_connect()

    def _build_ui(self, parent):
        """Build the GUI layout for the Cheat Engine tab inside the scrollable frame."""
        
        # --- Base Addresses ---
        base_frame = ttk.LabelFrame(parent, text="Base Addresses")
        base_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(base_frame, text="Fetch Base Addresses", command=self.fetch_base_addresses).pack(side=tk.LEFT, padx=5)
        ttk.Button(base_frame, text="Refresh Bases", command=self.refresh_base_addresses).pack(side=tk.LEFT, padx=5)
        self.base_label = ttk.Label(base_frame, text="Main NSO: 0x0 | Heap: 0x0")
        self.base_label.pack(side=tk.LEFT, padx=10)

        # --- Memory Input ---
        mem_frame = ttk.LabelFrame(parent, text="Memory Access")
        mem_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(mem_frame, text="Address Type:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        self.addr_type = ttk.Combobox(mem_frame, values=["Absolute", "Main NSO Relative", "Heap Relative"], state="readonly", width=18)
        self.addr_type.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        self.addr_type.set("Absolute")
        self._add_addr_type_tooltip(self.addr_type)
        
        ttk.Label(mem_frame, text="Address/Offset (hex):").grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        self.addr_entry = ttk.Entry(mem_frame, width=20)
        self.addr_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)
        self._add_hex_validation(self.addr_entry)
        
        ttk.Label(mem_frame, text="Value Type:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=2)
        value_size_options = [
            "8 bit unsigned", "8 bit signed",
            "16 bit unsigned", "16 bit signed",
            "32 bit unsigned", "32 bit signed", "32 bit float",
            "64 bit unsigned", "64 bit signed", "64 bit float"
        ]
        self.mem_value_type_combo = ttk.Combobox(mem_frame, values=value_size_options, state="readonly", width=16)
        self.mem_value_type_combo.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        self.mem_value_type_combo.set("32 bit unsigned")
        
        self.mem_value_type_label = ttk.Label(mem_frame, text="Size set to 4 bytes", foreground="#007700", font=(None, 8, "italic"))
        self.mem_value_type_label.grid(row=2, column=2, sticky=tk.W, padx=5, pady=2)
        
        def on_mem_value_type_change(event=None):
            size = self._get_type_size(self.mem_value_type_combo.get())
            self.mem_value_type_label.config(text=f"Size: {size} bytes")
        
        self.mem_value_type_combo.bind("<<ComboboxSelected>>", on_mem_value_type_change)
        
        ttk.Label(mem_frame, text="Value (hex):").grid(row=3, column=0, sticky=tk.W, padx=5, pady=2)
        self.value_entry = ttk.Entry(mem_frame, width=20)
        self.value_entry.grid(row=3, column=1, sticky=tk.W, padx=5, pady=2)
        
        btn_frame = ttk.Frame(mem_frame)
        btn_frame.grid(row=4, column=0, columnspan=3, pady=5)
        ttk.Button(btn_frame, text="Read Memory", command=self.read_memory).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Write Memory", command=self.write_memory).pack(side=tk.LEFT, padx=2)

        # --- Monitoring and Freezing ---
        mon_frame = ttk.LabelFrame(parent, text="Monitor & Freeze")
        mon_frame.pack(fill=tk.X, padx=10, pady=5)
        
        control_frame = ttk.Frame(mon_frame)
        control_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.monitor_var = tk.BooleanVar()
        ttk.Checkbutton(control_frame, text="Monitor in Real-Time", variable=self.monitor_var, command=self.toggle_monitor).pack(side=tk.LEFT, padx=5)
        
        self.freeze_var = tk.BooleanVar()
        ttk.Checkbutton(control_frame, text="Freeze Value", variable=self.freeze_var, command=self.toggle_freeze).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(control_frame, text="Update Rate (ms):").pack(side=tk.LEFT, padx=5)
        self.monitor_rate_var = tk.IntVar(value=1000)
        monitor_rate = ttk.Spinbox(control_frame, from_=100, to=5000, increment=100, textvariable=self.monitor_rate_var, width=8)
        monitor_rate.pack(side=tk.LEFT, padx=2)
        
        btn_frame2 = ttk.Frame(mon_frame)
        btn_frame2.pack(fill=tk.X, padx=5, pady=2)
        ttk.Button(btn_frame2, text="Add to Freeze List", command=self.add_to_freeze_list).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame2, text="Remove from Freeze List", command=self.remove_from_freeze_list).pack(side=tk.LEFT, padx=2)
        
        # Use Treeview for freeze list
        freeze_tree_frame = ttk.Frame(mon_frame)
        freeze_tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.freeze_tree = ttk.Treeview(freeze_tree_frame, columns=("Address", "Value", "Type"), show="headings", height=5)
        self.freeze_tree.heading("Address", text="Address")
        self.freeze_tree.heading("Value", text="Value")
        self.freeze_tree.heading("Type", text="Type")
        self.freeze_tree.column("Address", width=150)
        self.freeze_tree.column("Value", width=100)
        self.freeze_tree.column("Type", width=120)
        self.freeze_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        freeze_scroll = ttk.Scrollbar(freeze_tree_frame, orient="vertical", command=self.freeze_tree.yview)
        freeze_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.freeze_tree.configure(yscrollcommand=freeze_scroll.set)

        # --- Debugging Tools ---
        debug_frame = ttk.LabelFrame(parent, text="Debug Tools")
        debug_frame.pack(fill=tk.X, padx=10, pady=5)
        
        debug_row1 = ttk.Frame(debug_frame)
        debug_row1.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(debug_row1, text="Test Address (absolute hex):").pack(side=tk.LEFT, padx=2)
        self.debug_addr_entry = ttk.Entry(debug_row1, width=20)
        self.debug_addr_entry.pack(side=tk.LEFT, padx=2)
        self.debug_addr_entry.insert(0, "0x6c90bf4cb0")
        
        ttk.Label(debug_row1, text="Size (bytes):").pack(side=tk.LEFT, padx=5)
        self.debug_size_entry = ttk.Entry(debug_row1, width=8)
        self.debug_size_entry.pack(side=tk.LEFT, padx=2)
        self.debug_size_entry.insert(0, "4")
        
        ttk.Button(debug_row1, text="Raw Peek", command=self.debug_raw_peek).pack(side=tk.LEFT, padx=5)
        ttk.Button(debug_row1, text="Parsed Read", command=self.debug_parsed_read).pack(side=tk.LEFT, padx=2)
        
        debug_row2 = ttk.Frame(debug_frame)
        debug_row2.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Button(debug_row2, text="Address Calculator", command=self.debug_address_calculator).pack(side=tk.LEFT, padx=2)
        ttk.Button(debug_row2, text="Compare with Breeze", command=self.debug_compare_breeze).pack(side=tk.LEFT, padx=2)
        ttk.Button(debug_row2, text="Test Connection", command=self.debug_test_connection).pack(side=tk.LEFT, padx=2)
        ttk.Button(debug_row2, text="Clear Log", command=lambda: self.output.delete(1.0, tk.END)).pack(side=tk.LEFT, padx=2)
        
        ttk.Checkbutton(debug_row2, text="Verbose Logging", variable=self.debug_verbose).pack(side=tk.LEFT, padx=5)
        
        # Manual command sender
        debug_row3 = ttk.Frame(debug_frame)
        debug_row3.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(debug_row3, text="Manual Command:").pack(side=tk.LEFT, padx=2)
        self.manual_cmd_entry = ttk.Entry(debug_row3, width=40)
        self.manual_cmd_entry.pack(side=tk.LEFT, padx=2)
        self.manual_cmd_entry.insert(0, "getTitleID")
        ttk.Button(debug_row3, text="Send", command=self.debug_send_manual_command).pack(side=tk.LEFT, padx=2)
        ttk.Label(debug_row3, text="(Try: getTitleID, configure, etc.)", font=(None, 8, "italic")).pack(side=tk.LEFT, padx=5)

        # --- Output ---
        out_frame = ttk.LabelFrame(parent, text="Output / Log")
        out_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        output_container = ttk.Frame(out_frame)
        output_container.pack(fill=tk.BOTH, expand=True)
        
        self.output = tk.Text(output_container, height=10, width=80, wrap=tk.WORD)
        self.output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        output_scroll = ttk.Scrollbar(output_container, orient="vertical", command=self.output.yview)
        output_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.output.configure(yscrollcommand=output_scroll.set)

        # --- Cheat Management ---
        cheat_frame = ttk.LabelFrame(parent, text="Cheat Management")
        cheat_frame.pack(fill=tk.X, padx=10, pady=5)
        
        cheat_btn_frame = ttk.Frame(cheat_frame)
        cheat_btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Button(cheat_btn_frame, text="Save Cheats", command=self.save_cheats).pack(side=tk.LEFT, padx=2)
        ttk.Button(cheat_btn_frame, text="Load Cheats", command=self.load_cheats).pack(side=tk.LEFT, padx=2)
        ttk.Button(cheat_btn_frame, text="Export to Atmosphere", command=self.export_atmosphere).pack(side=tk.LEFT, padx=2)
        
        # Use Treeview for cheats
        cheat_tree_frame = ttk.Frame(cheat_frame)
        cheat_tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.cheat_tree = ttk.Treeview(cheat_tree_frame, columns=("Description", "Address", "Value"), show="headings", height=5)
        self.cheat_tree.heading("Description", text="Description")
        self.cheat_tree.heading("Address", text="Address")
        self.cheat_tree.heading("Value", text="Value")
        self.cheat_tree.column("Description", width=200)
        self.cheat_tree.column("Address", width=150)
        self.cheat_tree.column("Value", width=100)
        self.cheat_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        cheat_scroll = ttk.Scrollbar(cheat_tree_frame, orient="vertical", command=self.cheat_tree.yview)
        cheat_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.cheat_tree.configure(yscrollcommand=cheat_scroll.set)
        
        cheat_btn_frame2 = ttk.Frame(cheat_frame)
        cheat_btn_frame2.pack(fill=tk.X, padx=5, pady=2)
        ttk.Button(cheat_btn_frame2, text="Apply Selected Cheat", command=self.apply_selected_cheat).pack(side=tk.LEFT, padx=2)
        ttk.Button(cheat_btn_frame2, text="Remove Selected Cheat", command=self.remove_selected_cheat).pack(side=tk.LEFT, padx=2)

        # --- Memory Scanner ---
        scanner_frame = ttk.LabelFrame(parent, text="Memory Scanner")
        scanner_frame.pack(fill=tk.X, padx=10, pady=5)
        
        scan_config = ttk.Frame(scanner_frame)
        scan_config.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(scan_config, text="Address Type:").grid(row=0, column=0, sticky=tk.W, padx=2, pady=2)
        self.scan_addr_type = ttk.Combobox(scan_config, values=["Absolute", "Main NSO Relative", "Heap Relative"], state="readonly", width=18)
        self.scan_addr_type.grid(row=0, column=1, sticky=tk.W, padx=2, pady=2)
        self.scan_addr_type.set("Main NSO Relative")
        self._add_addr_type_tooltip(self.scan_addr_type)
        
        ttk.Label(scan_config, text="Start Offset (hex):").grid(row=1, column=0, sticky=tk.W, padx=2, pady=2)
        self.scan_start_entry = ttk.Entry(scan_config, width=15)
        self.scan_start_entry.grid(row=1, column=1, sticky=tk.W, padx=2, pady=2)
        self.scan_start_entry.insert(0, "0x0")
        
        ttk.Label(scan_config, text="End Offset (hex):").grid(row=1, column=2, sticky=tk.W, padx=2, pady=2)
        self.scan_end_entry = ttk.Entry(scan_config, width=15)
        self.scan_end_entry.grid(row=1, column=3, sticky=tk.W, padx=2, pady=2)
        self.scan_end_entry.insert(0, "0x1000000")
        
        ttk.Label(scan_config, text="MB:").grid(row=1, column=4, sticky=tk.W, padx=2, pady=2)
        self.scan_mb_entry = ttk.Entry(scan_config, width=6)
        self.scan_mb_entry.grid(row=1, column=5, sticky=tk.W, padx=2, pady=2)
        self.scan_mb_entry.insert(0, "16")
        
        self.scan_end_entry.bind('<KeyRelease>', self._sync_mb_from_end)
        self.scan_mb_entry.bind('<KeyRelease>', self._sync_end_from_mb)
        
        ttk.Label(scan_config, text="Chunk Size (hex):").grid(row=2, column=0, sticky=tk.W, padx=2, pady=2)
        self.scan_chunk_entry = ttk.Entry(scan_config, width=12)
        self.scan_chunk_entry.grid(row=2, column=1, sticky=tk.W, padx=2, pady=2)
        self.scan_chunk_entry.insert(0, "0x100000")  # 1MB default for better performance
        
        scan_value_frame = ttk.Frame(scanner_frame)
        scan_value_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(scan_value_frame, text="Value:").grid(row=0, column=0, sticky=tk.W, padx=2, pady=2)
        self.scan_value_entry = ttk.Entry(scan_value_frame, width=12)
        self.scan_value_entry.grid(row=0, column=1, sticky=tk.W, padx=2, pady=2)
        self.scan_value_entry.insert(0, "100")
        
        ttk.Label(scan_value_frame, text="Type:").grid(row=0, column=2, sticky=tk.W, padx=2, pady=2)
        self.scan_size_combo = ttk.Combobox(scan_value_frame, values=value_size_options, state="readonly", width=16)
        self.scan_size_combo.grid(row=0, column=3, sticky=tk.W, padx=2, pady=2)
        self.scan_size_combo.set("32 bit unsigned")
        
        ttk.Label(scan_value_frame, text="Comparison:").grid(row=0, column=4, sticky=tk.W, padx=2, pady=2)
        self.scan_comparison_combo = ttk.Combobox(scan_value_frame, values=[
            "Exact Value", "Greater Than", "Less Than", "Between", 
            "Increased Value", "Decreased Value", "Changed Value", "Unchanged Value", "Unknown Initial Value"
        ], state="readonly", width=18)
        self.scan_comparison_combo.grid(row=0, column=5, sticky=tk.W, padx=2, pady=2)
        self.scan_comparison_combo.set("Exact Value")
        
        ttk.Label(scan_value_frame, text="To:").grid(row=0, column=6, sticky=tk.W, padx=2, pady=2)
        self.scan_value2_entry = ttk.Entry(scan_value_frame, width=12)
        self.scan_value2_entry.grid(row=0, column=7, sticky=tk.W, padx=2, pady=2)
        self.scan_value2_entry.grid_remove()
        
        def on_comparison_change(event=None):
            comp = self.scan_comparison_combo.get()
            if comp == "Between":
                self.scan_value2_entry.grid()
            else:
                self.scan_value2_entry.grid_remove()
            
            # Disable value entry for change-based and unknown scans
            if comp in ["Increased Value", "Decreased Value", "Changed Value", "Unchanged Value", "Unknown Initial Value"]:
                self.scan_value_entry.config(state=tk.DISABLED)
            else:
                self.scan_value_entry.config(state=tk.NORMAL)
        
        self.scan_comparison_combo.bind("<<ComboboxSelected>>", on_comparison_change)
        
        scan_btn_frame = ttk.Frame(scanner_frame)
        scan_btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Button(scan_btn_frame, text="First Scan", command=self.first_scan).pack(side=tk.LEFT, padx=2)
        ttk.Button(scan_btn_frame, text="Next Scan", command=self.next_scan).pack(side=tk.LEFT, padx=2)
        ttk.Button(scan_btn_frame, text="Pointer Scan", command=self.pointer_scan).pack(side=tk.LEFT, padx=2)
        self.cancel_scan_btn = ttk.Button(scan_btn_frame, text="Cancel Scan", command=self.cancel_scan, state=tk.DISABLED)
        self.cancel_scan_btn.pack(side=tk.LEFT, padx=2)
        
        # Use Treeview for scan results
        scan_tree_frame = ttk.Frame(scanner_frame)
        scan_tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.scan_tree = ttk.Treeview(scan_tree_frame, columns=("Address", "Offset", "Value", "Type"), show="headings", height=8)
        self.scan_tree.heading("Address", text="Address")
        self.scan_tree.heading("Offset", text="Offset")
        self.scan_tree.heading("Value", text="Value")
        self.scan_tree.heading("Type", text="Type")
        self.scan_tree.column("Address", width=120)
        self.scan_tree.column("Offset", width=100)
        self.scan_tree.column("Value", width=100)
        self.scan_tree.column("Type", width=120)
        self.scan_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scan_scroll = ttk.Scrollbar(scan_tree_frame, orient="vertical", command=self.scan_tree.yview)
        scan_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.scan_tree.configure(yscrollcommand=scan_scroll.set)
        
        ttk.Button(scanner_frame, text="Add to Monitor/Freeze/Cheat", command=self.add_scan_result_to_cheat).pack(pady=5)
        
        # Progress bar and status
        progress_frame = ttk.Frame(scanner_frame)
        progress_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.scan_progress = ttk.Progressbar(progress_frame, orient="horizontal", length=400, mode="determinate")
        self.scan_progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        
        self.scan_status_label = ttk.Label(progress_frame, text="Idle", width=30)
        self.scan_status_label.pack(side=tk.LEFT, padx=5)

    def send_command(self, command: str, timeout: int = 10) -> Optional[str]:
        """
        Send a command to sys-botbase over TCP with retry logic.
        Args:
            command: The command string to send.
            timeout: Socket timeout in seconds.
        Returns:
            The response from sys-botbase, or None on error.
        """
        if not self.connected:
            messagebox.showerror("Error", "Not connected to Switch")
            return None
        
        if self.debug_verbose.get():
            self.output.insert(tk.END, f"[SEND] {command}\n")
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(timeout)
                    sock.connect((self.ip, self.port))
                    sock.sendall(command.encode() + b'\n')
                    
                    # Receive response - might need multiple recv calls
                    response_parts = []
                    while True:
                        try:
                            part = sock.recv(4096).decode()
                            if not part:
                                break
                            response_parts.append(part)
                            # Check if we have a complete response
                            if len(part) < 4096:
                                break
                        except socket.timeout:
                            break
                    
                    response = ''.join(response_parts).strip()
                
                if self.debug_verbose.get():
                    preview = response[:200] + ('...' if len(response) > 200 else '')
                    self.output.insert(tk.END, f"[RECV] ({len(response)} chars) {preview}\n")
                
                # Check for common error patterns
                if not response:
                    self.output.insert(tk.END, f"[WARNING] Empty response from sys-botbase\n")
                    return None
                
                # Check if response is all zeros (common error)
                if response.replace('0', '').replace(' ', '').replace('\n', '') == '':
                    self.output.insert(tk.END, f"[WARNING] All-zero response (possible error)\n")
                
                return response
            except socket.timeout:
                if attempt < max_retries - 1:
                    self.output.insert(tk.END, f"[RETRY] Attempt {attempt + 1} timed out, retrying...\n")
                    continue
                self.output.insert(tk.END, f"[ERROR] Command timed out after {max_retries} attempts\n")
                return None
            except Exception as e:
                if attempt < max_retries - 1:
                    self.output.insert(tk.END, f"[RETRY] Error on attempt {attempt + 1}: {e}\n")
                    continue
                self.output.insert(tk.END, f"[ERROR] {e}\n")
                return None
        return None

    def _format_address(self, addr: int) -> str:
        """Return a sys-botbase-friendly hex address string (no 0x prefix)."""
        return f"{addr:X}"

    def _format_hex_value(self, value: str) -> str:
        """Normalize hex strings (no spaces, uppercase)."""
        return value.replace(" ", "").upper()

    def _send_peek(self, command: str, addr: int, size: int, timeout: int = 10) -> Optional[str]:
        """Send a sys-botbase peek-style command with normalized formatting."""
        return self.send_command(f"{command} {self._format_address(addr)} {size}", timeout=timeout)

    def _send_poke(self, command: str, addr: int, value: str) -> Optional[str]:
        """Send a sys-botbase poke-style command with normalized formatting."""
        return self.send_command(f"{command} {self._format_address(addr)} {self._format_hex_value(value)}")

    def _peek_absolute(self, addr: int, size: int, timeout: int = 10) -> Optional[str]:
        """Read raw bytes using peekAbsolute."""
        return self._send_peek("peekAbsolute", addr, size, timeout=timeout)

    def _peek_main(self, offset: int, size: int, timeout: int = 10) -> Optional[str]:
        """Read raw bytes using peekMain (offset from Main NSO)."""
        return self._send_peek("peekMain", offset, size, timeout=timeout)

    def _peek_heap(self, offset: int, size: int, timeout: int = 10) -> Optional[str]:
        """Read raw bytes using peekHeap (offset from Heap)."""
        return self._send_peek("peekHeap", offset, size, timeout=timeout)

    def _poke_absolute(self, addr: int, value: str) -> Optional[str]:
        """Write raw bytes using pokeAbsolute."""
        return self._send_poke("pokeAbsolute", addr, value)

    def _poke_main(self, offset: int, value: str) -> Optional[str]:
        """Write raw bytes using pokeMain (offset from Main NSO)."""
        return self._send_poke("pokeMain", offset, value)

    def _poke_heap(self, offset: int, value: str) -> Optional[str]:
        """Write raw bytes using pokeHeap (offset from Heap)."""
        return self._send_poke("pokeHeap", offset, value)

    def debug_raw_peek(self):
        """Debug: Send raw peek command and show exact response."""
        try:
            addr_str = self.debug_addr_entry.get().strip()
            size = int(self.debug_size_entry.get().strip())
            
            # Parse address
            if addr_str.lower().startswith("0x"):
                addr = int(addr_str, 16)
            else:
                addr = int(addr_str, 16)
            
            self.output.insert(tk.END, f"\n{'='*60}\n")
            self.output.insert(tk.END, f"[DEBUG] Raw Peek Test - Testing ALL Command Formats\n")
            self.output.insert(tk.END, f"Address: {hex(addr)} ({addr})\n")
            self.output.insert(tk.END, f"Size: {size} bytes\n\n")
            
            # sys-botbase command formats to try (based on actual documentation)
            formats = [
                # Format 1: peek with 0x prefix, decimal size
                (f"peek 0x{addr:X} {size}", "0x prefix uppercase, decimal size"),
                
                # Format 2: peek with 0x prefix, hex size  
                (f"peek 0x{addr:X} 0x{size:X}", "0x prefix uppercase, hex size"),
                
                # Format 3: peek no prefix, decimal size
                (f"peek {addr:X} {size}", "no prefix uppercase, decimal size"),
                
                # Format 4: peek no prefix, hex size
                (f"peek {addr:X} 0x{size:X}", "no prefix uppercase, hex size"),
                
                # Format 5: peek lowercase
                (f"peek {addr:x} {size}", "lowercase hex, decimal size"),
                
                # Format 6: pointerPeek (for pointer reads)
                (f"pointerPeek 0x{size:X} 0x{addr:X}", "pointerPeek format"),
                
                # Format 7: peekAbsolute (if it exists)
                (f"peekAbsolute 0x{addr:X} 0x{size:X}", "peekAbsolute format"),
                
                # Format 8: Original format you were using
                (f"peek {hex(addr)[2:]} {size}", "original format (hex()[2:])"),
            ]
            
            results = []
            for i, (cmd, desc) in enumerate(formats, 1):
                self.output.insert(tk.END, f"--- Test {i}: {desc} ---\n")
                self.output.insert(tk.END, f"Command: {cmd}\n")
                
                response = self.send_command(cmd)
                
                if response:
                    # Check if response is unique
                    clean_hex = response.replace(" ", "").replace("\n", "")
                    
                    self.output.insert(tk.END, f"Response: {response[:60]}{'...' if len(response) > 60 else ''}\n")
                    
                    # Check if it's all zeros or repeated pattern
                    if clean_hex == '0' * len(clean_hex):
                        self.output.insert(tk.END, f"❌ All zeros\n")
                        results.append((cmd, "all_zeros"))
                    elif clean_hex == 'FFD8FFE1' * (len(clean_hex) // 8):
                        self.output.insert(tk.END, f"❌ Repeated FFD8FFE1 pattern (broken)\n")
                        results.append((cmd, "repeated_pattern"))
                    else:
                        # Try to parse and check if it changes with address
                        try:
                            data_bytes = binascii.unhexlify(clean_hex[:size*2])
                            
                            if len(data_bytes) >= 4:
                                u32_le = int.from_bytes(data_bytes[:4], byteorder='little', signed=False)
                                self.output.insert(tk.END, f"✓ Variable data! u32: {u32_le} (0x{u32_le:08x})\n")
                                
                                if u32_le == 3241:
                                    self.output.insert(tk.END, f"✓✓✓ MATCH! Value = 3241 ✓✓✓\n")
                                    results.append((cmd, "MATCH_3241"))
                                else:
                                    results.append((cmd, f"value_{u32_le}"))
                        except Exception as e:
                            self.output.insert(tk.END, f"Parse error: {e}\n")
                            results.append((cmd, "parse_error"))
                else:
                    self.output.insert(tk.END, f"❌ No response\n")
                    results.append((cmd, "no_response"))
                
                self.output.insert(tk.END, f"\n")
            
            # Summary
            self.output.insert(tk.END, f"{'='*60}\n")
            self.output.insert(tk.END, f"SUMMARY:\n")
            unique_responses = {}
            for cmd, result in results:
                if result not in unique_responses:
                    unique_responses[result] = []
                unique_responses[result].append(cmd)
            
            for result, cmds in unique_responses.items():
                self.output.insert(tk.END, f"\n{result}:\n")
                for cmd in cmds:
                    self.output.insert(tk.END, f"  - {cmd}\n")
            
            if "MATCH_3241" in unique_responses:
                self.output.insert(tk.END, f"\n✓✓✓ WORKING COMMAND FOUND! ✓✓✓\n")
                winning_cmd = unique_responses["MATCH_3241"][0]
                self.output.insert(tk.END, f"Use this format: {winning_cmd}\n")
            elif len(unique_responses) == 1 and "repeated_pattern" in unique_responses:
                self.output.insert(tk.END, f"\n❌ ALL COMMANDS RETURNED SAME PATTERN\n")
                self.output.insert(tk.END, f"This indicates sys-botbase is NOT reading from specified addresses.\n")
                self.output.insert(tk.END, f"\nPossible causes:\n")
                self.output.insert(tk.END, f"1. Game process not attached properly\n")
                self.output.insert(tk.END, f"2. Different sys-botbase version with different command syntax\n")
                self.output.insert(tk.END, f"3. sys-botbase not attached to the game process\n")
                self.output.insert(tk.END, f"4. Memory protection preventing reads\n")
                self.output.insert(tk.END, f"\nTry restarting the game and sys-botbase.\n")
            
            self.output.insert(tk.END, f"{'='*60}\n\n")
            self.output.see(tk.END)
            
        except Exception as e:
            messagebox.showerror("Debug Error", str(e))
            self.output.insert(tk.END, f"[DEBUG ERROR] {e}\n")

    def debug_send_manual_command(self):
        """Debug: Send a manual command to sys-botbase."""
        cmd = self.manual_cmd_entry.get().strip()
        if not cmd:
            return
        
        self.output.insert(tk.END, f"\n[MANUAL] Sending: {cmd}\n")
        response = self.send_command(cmd)
        
        if response:
            self.output.insert(tk.END, f"[MANUAL] Response: {response}\n")
        else:
            self.output.insert(tk.END, f"[MANUAL] No response\n")
        
        self.output.see(tk.END)

    def debug_address_calculator(self):
        """Debug: Calculate what the actual address should be based on Breeze's address."""
        addr_str = self.debug_addr_entry.get().strip()
        
        try:
            if addr_str.lower().startswith("0x"):
                breeze_addr = int(addr_str, 16)
            else:
                breeze_addr = int(addr_str, 16)
            
            self.output.insert(tk.END, f"\n{'='*60}\n")
            self.output.insert(tk.END, f"[DEBUG] Address Calculator\n")
            self.output.insert(tk.END, f"Breeze Address: {hex(breeze_addr)} ({breeze_addr})\n\n")
            
            # Get current bases
            main_nso = self.main_nso_base if self.main_nso_base else 0
            heap = self.heap_base if self.heap_base else 0
            
            if main_nso == 0:
                self.output.insert(tk.END, "⚠️  Main NSO base not fetched. Getting it now...\n")
                self.fetch_base_addresses()
                main_nso = self.main_nso_base
                heap = self.heap_base
            
            self.output.insert(tk.END, f"Main NSO Base: {hex(main_nso)}\n")
            self.output.insert(tk.END, f"Heap Base: {hex(heap)}\n\n")
            
            # Calculate possible interpretations
            self.output.insert(tk.END, f"Possible Interpretations:\n")
            self.output.insert(tk.END, f"{'-'*60}\n")
            
            # 1. If Breeze shows absolute address
            self.output.insert(tk.END, f"1. Breeze address IS absolute:\n")
            self.output.insert(tk.END, f"   Use: {hex(breeze_addr)}\n")
            self.output.insert(tk.END, f"   Command: peekAbsolute {self._format_address(breeze_addr)} 4\n")
            if breeze_addr < main_nso:
                self.output.insert(tk.END, f"   ⚠️  UNLIKELY - address is below Main NSO base\n")
            else:
                offset_from_main = breeze_addr - main_nso
                self.output.insert(tk.END, f"   Offset from Main: +{hex(offset_from_main)}\n")
            
            # 2. If Breeze shows Main+offset
            self.output.insert(tk.END, f"\n2. Breeze shows Main NSO + offset:\n")
            absolute_from_main = main_nso + breeze_addr
            self.output.insert(tk.END, f"   Absolute address: {hex(absolute_from_main)}\n")
            self.output.insert(tk.END, f"   Command: peekMain {self._format_address(breeze_addr)} 4\n")
            self.output.insert(tk.END, f"   ✓ MOST LIKELY if Breeze shows 'Main+...'\n")
            
            # 3. If Breeze shows Heap+offset
            if heap > 0:
                self.output.insert(tk.END, f"\n3. Breeze shows Heap + offset:\n")
                absolute_from_heap = heap + breeze_addr
                self.output.insert(tk.END, f"   Absolute address: {hex(absolute_from_heap)}\n")
                self.output.insert(tk.END, f"   Command: peekHeap {self._format_address(breeze_addr)} 4\n")
            
            # Suggest testing
            self.output.insert(tk.END, f"\n{'-'*60}\n")
            self.output.insert(tk.END, f"RECOMMENDED TEST:\n")
            self.output.insert(tk.END, f"Try reading Main NSO + offset:\n")
            self.output.insert(tk.END, f"  Address: {hex(main_nso + breeze_addr)}\n\n")
            
            # Auto-update the debug address field with calculated address
            self.debug_addr_entry.delete(0, tk.END)
            self.debug_addr_entry.insert(0, hex(main_nso + breeze_addr))
            
            self.output.insert(tk.END, f"✓ Updated test address field to: {hex(main_nso + breeze_addr)}\n")
            self.output.insert(tk.END, f"Now click 'Raw Peek' to test!\n")
            self.output.insert(tk.END, f"{'='*60}\n\n")
            self.output.see(tk.END)
            
        except Exception as e:
            messagebox.showerror("Debug Error", str(e))
            self.output.insert(tk.END, f"[DEBUG ERROR] {e}\n")

    def debug_parsed_read(self):
        """Debug: Read using the normal read_memory function with detailed logging."""
        try:
            addr_str = self.debug_addr_entry.get().strip()
            
            # Temporarily set the memory section to this address
            old_addr = self.addr_entry.get()
            old_type = self.addr_type.get()
            
            self.addr_type.set("Absolute")
            self.addr_entry.delete(0, tk.END)
            self.addr_entry.insert(0, addr_str)
            
            self.output.insert(tk.END, f"\n[DEBUG] Parsed Read Test\n")
            self.read_memory()
            
            # Restore
            self.addr_type.set(old_type)
            self.addr_entry.delete(0, tk.END)
            self.addr_entry.insert(0, old_addr)
            
        except Exception as e:
            messagebox.showerror("Debug Error", str(e))

    def debug_compare_breeze(self):
        """Debug: Guide user through comparison with Breeze."""
        addr = self.debug_addr_entry.get().strip()
        
        msg = f"""Breeze Comparison Checklist:

1. In Breeze, verify the address: {addr}
2. Check the value type (u8/u16/u32/u64, signed/unsigned, float)
3. Check if Breeze shows the address as:
   - Absolute
   - Main NSO + offset
   - Heap + offset

4. Verify sys-botbase is responding:
   - Try 'getMainNsoBase' command
   - Try 'getHeapBase' command

5. Common issues:
   - Address might be relative, not absolute
   - Sys-botbase might return data in different endianness
   - Size mismatch (reading 4 bytes but value needs 8)
   - Pointer indirection (Breeze following pointer, we're not)

Current settings:
- IP: {self.ip}
- Port: {self.port}
- Connected: {self.connected}

Try the following in Breeze:
1. Note the EXACT address format Breeze uses
2. Check if it shows "Main+offset" or "Heap+offset"
3. If so, use our relative addressing mode
"""
        
        self.output.insert(tk.END, f"\n{msg}\n")
        self.output.see(tk.END)

    def debug_test_connection(self):
        """Debug: Test basic sys-botbase commands."""
        self.output.insert(tk.END, f"\n{'='*60}\n")
        self.output.insert(tk.END, f"[DEBUG] Connection Test\n")
        self.output.insert(tk.END, f"IP: {self.ip}, Port: {self.port}\n\n")
        
        # Test 1: Get version/info commands
        self.output.insert(tk.END, f"Test 1: System Info Commands\n")
        
        # Try different info commands
        commands_to_test = [
            ("getMainNsoBase", "Get main NSO base address"),
            ("getHeapBase", "Get heap base address"),
            ("getTitleID", "Get running title ID"),
            ("getSystemLanguage", "Get system language"),
            ("pixelPeek", "Test if game is running"),
        ]
        
        for cmd, desc in commands_to_test:
            self.output.insert(tk.END, f"  {cmd}: ")
            result = self.send_command(cmd)
            if result:
                # Show first 50 chars
                preview = result[:50] + ('...' if len(result) > 50 else '')
                self.output.insert(tk.END, f"'{preview}'\n")
            else:
                self.output.insert(tk.END, f"No response\n")
        
        main_nso = self.send_command("getMainNsoBase")
        heap = self.send_command("getHeapBase")
        
        # Test 2: Try peeking at main NSO base (should always work if game is running)
        if main_nso and main_nso != "0":
            try:
                base_addr = int(main_nso, 16)
                self.output.insert(tk.END, f"\nTest 2: Peek at Main NSO Base\n")
                self.output.insert(tk.END, f"  Address: {hex(base_addr)}\n")
                
                # Try reading first 16 bytes
                data = self._peek_absolute(base_addr, 16)
                if data:
                    self.output.insert(tk.END, f"  First 16 bytes: {data[:50]}\n")
                    
                    # Check if it's all zeros
                    if data.replace('0', '').replace(' ', '').replace('\n', '') == '':
                        self.output.insert(tk.END, f"  ❌ WARNING: All zeros returned\n")
                        self.output.insert(tk.END, f"  This suggests sys-botbase can't read memory\n")
                    else:
                        self.output.insert(tk.END, f"  ✓ Got non-zero data\n")
                else:
                    self.output.insert(tk.END, f"  ❌ No data returned\n")
            except Exception as e:
                self.output.insert(tk.END, f"  Error: {e}\n")
        else:
            self.output.insert(tk.END, f"\n❌ Main NSO Base is 0 or not returned\n")
            self.output.insert(tk.END, f"Possible causes:\n")
            self.output.insert(tk.END, f"  1. Game is not running\n")
            self.output.insert(tk.END, f"  2. sys-botbase not attached to game process\n")
            self.output.insert(tk.END, f"  3. Wrong sys-botbase version\n")
            self.output.insert(tk.END, f"  4. Using wrong sysmodule (Breeze might use ldn_mitm or sys-ftpd-ovl)\n")
        
        # Test 3: Test if it's actually sys-botbase or another protocol
        self.output.insert(tk.END, f"\nTest 3: Protocol Detection\n")
        self.output.insert(tk.END, f"Trying to detect which sysmodule is responding...\n")
        
        # Test sys-botbase specific commands
        version = self.send_command("getVersion")
        if version:
            self.output.insert(tk.END, f"  Version command: '{version}'\n")
        
        # Suggestion
        self.output.insert(tk.END, f"\n{'='*60}\n")
        self.output.insert(tk.END, f"TROUBLESHOOTING CHECKLIST:\n\n")
        self.output.insert(tk.END, f"✓ Check Breeze settings:\n")
        self.output.insert(tk.END, f"  - What IP and port does Breeze use?\n")
        self.output.insert(tk.END, f"  - Is Breeze using sys-botbase or something else?\n")
        self.output.insert(tk.END, f"  - Try Breeze's 'Test Connection' button\n\n")
        self.output.insert(tk.END, f"✓ On Switch:\n")
        self.output.insert(tk.END, f"  - Is the game running?\n")
        self.output.insert(tk.END, f"  - Is sys-botbase/atmosphere running?\n")
        self.output.insert(tk.END, f"  - Check Tesla overlay for sys-botbase status\n\n")
        self.output.insert(tk.END, f"✓ Network:\n")
        self.output.insert(tk.END, f"  - Can you ping {self.ip}?\n")
        self.output.insert(tk.END, f"  - Is port {self.port} correct? (usually 6000 for sys-botbase)\n")
        self.output.insert(tk.END, f"  - Check firewall settings\n")
        self.output.insert(tk.END, f"{'='*60}\n\n")
        self.output.see(tk.END)

    def fetch_base_addresses(self):
        """Fetch and display the main NSO base and heap base addresses from the Switch."""
        if not self.connected:
            messagebox.showerror("Error", "Not connected to Switch")
            return
        
        try:
            main_nso = self.send_command("getMainNsoBase")
            heap = self.send_command("getHeapBase")
            
            self.main_nso_base = int(main_nso, 16) if main_nso else 0
            self.heap_base = int(heap, 16) if heap else 0
            
            self._base_cache['main_nso'] = self.main_nso_base
            self._base_cache['heap'] = self.heap_base
            
            self.base_label.config(text=f"Main NSO: {hex(self.main_nso_base)} | Heap: {hex(self.heap_base)}")
            self.output.insert(tk.END, f"Main NSO Base: {hex(self.main_nso_base)}\nHeap Base: {hex(self.heap_base)}\n")
        except Exception as e:
            self.output.insert(tk.END, f"Error fetching base addresses: {e}\n")

    def refresh_base_addresses(self):
        """Clear cache and re-fetch base addresses."""
        self._base_cache.clear()
        self.fetch_base_addresses()

    def calculate_address(self, addr_type: Optional[str] = None, offset: Optional[str] = None) -> Optional[int]:
        """
        Calculate the absolute address based on the selected address type and offset.
        Args:
            addr_type: Address type (Absolute, Main NSO Relative, Heap Relative).
            offset: Offset in hex or int.
        Returns:
            The calculated address, or None if invalid.
        """
        addr_type = addr_type or self.addr_type.get()
        try:
            offset_val = int(offset if offset is not None else self.addr_entry.get(), 16)
        except ValueError:
            messagebox.showerror("Error", "Invalid address/offset format")
            return None
        
        if addr_type == "Absolute":
            return offset_val
        elif addr_type == "Main NSO Relative":
            if self.main_nso_base == 0:
                messagebox.showwarning("Warning", "Main NSO base not set. Fetch base addresses first.")
                return None
            return self.main_nso_base + offset_val
        elif addr_type == "Heap Relative":
            if self.heap_base == 0:
                messagebox.showwarning("Warning", "Heap base not set. Fetch base addresses first.")
                return None
            return self.heap_base + offset_val
        
        return None

    def _get_type_size(self, type_str: str) -> int:
        """Return the size in bytes for a given value type string."""
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
        """Read memory from the calculated address with better error handling."""
        if not self.connected:
            messagebox.showerror("Error", "Not connected to Switch")
            return
        
        try:
            size = self._get_type_size(self.mem_value_type_combo.get())
            addr_type = self.addr_type.get()
            offset_str = self.addr_entry.get()
            offset_val = int(offset_str, 16)

            if addr_type == "Absolute":
                response = self._peek_absolute(offset_val, size)
                addr_display = hex(offset_val)
            elif addr_type == "Main NSO Relative":
                response = self._peek_main(offset_val, size)
                addr_display = f"Main+{hex(offset_val)}"
            elif addr_type == "Heap Relative":
                response = self._peek_heap(offset_val, size)
                addr_display = f"Heap+{hex(offset_val)}"
            else:
                messagebox.showerror("Error", "Unknown address type")
                return
            
            if response:
                self.output.insert(tk.END, f"Read {size} bytes from {addr_display}: {response}\n")
                # Auto-populate value entry
                self.value_entry.delete(0, tk.END)
                self.value_entry.insert(0, response)
            else:
                self.output.insert(tk.END, f"Failed to read from {addr_display}\n")
        except Exception as e:
            messagebox.showerror("Error", f"Read failed: {e}")

    def write_memory(self):
        """Write the specified value to the calculated address."""
        if not self.connected:
            messagebox.showerror("Error", "Not connected to Switch")
            return
        
        addr_type = self.addr_type.get()
        offset_str = self.addr_entry.get()
        try:
            offset_val = int(offset_str, 16)
        except ValueError:
            messagebox.showerror("Error", "Invalid address/offset format")
            return

        value = self._format_hex_value(self.value_entry.get())
        if not value:
            messagebox.showerror("Error", "No value specified")
            return
        
        if addr_type == "Absolute":
            response = self._poke_absolute(offset_val, value)
            addr_display = hex(offset_val)
        elif addr_type == "Main NSO Relative":
            response = self._poke_main(offset_val, value)
            addr_display = f"Main+{hex(offset_val)}"
        elif addr_type == "Heap Relative":
            response = self._poke_heap(offset_val, value)
            addr_display = f"Heap+{hex(offset_val)}"
        else:
            messagebox.showerror("Error", "Unknown address type")
            return

        if response is not None:
            self.output.insert(tk.END, f"Wrote {value} to {addr_display}\n")

    def toggle_monitor(self):
        """Enable or disable real-time memory monitoring."""
        self.monitoring = self.monitor_var.get()
        if self.monitoring:
            self.update_monitor()

    def update_monitor(self):
        """Periodically read memory if monitoring is enabled."""
        if not self.monitoring:
            return
        self.read_memory()
        rate = self.monitor_rate_var.get()
        self.after(rate, self.update_monitor)

    def toggle_freeze(self):
        """Enable or disable freezing of memory values."""
        self.freezing = self.freeze_var.get()
        if self.freezing:
            self.update_freeze()

    def update_freeze(self):
        """Periodically write frozen values in batch if freezing is enabled."""
        if not self.freezing:
            return
        
        # Batch freeze writes for efficiency
        for addr, value, size in self.freeze_list:
            self._poke_absolute(addr, value)
        
        self.after(100, self.update_freeze)

    def add_to_freeze_list(self):
        """Add the current address and value to the freeze list."""
        addr = self.calculate_address()
        value = self.value_entry.get().replace(" ", "")
        value_type = self.mem_value_type_combo.get()
        size = self._get_type_size(value_type)
        
        if addr is not None and value:
            self.freeze_list.append((addr, value, size))
            self.freeze_tree.insert("", tk.END, values=(hex(addr), value, value_type))
            self.output.insert(tk.END, f"Added freeze: {hex(addr)} = {value}\n")

    def remove_from_freeze_list(self):
        """Remove the selected item from the freeze list."""
        selection = self.freeze_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No item selected")
            return
        
        for item in selection:
            idx = self.freeze_tree.index(item)
            self.freeze_tree.delete(item)
            if idx < len(self.freeze_list):
                del self.freeze_list[idx]
        
        self.output.insert(tk.END, f"Removed {len(selection)} freeze(s)\n")

    def save_cheats(self):
        """Save the current list of cheats to a JSON file."""
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON Files", "*.json")])
        if not path:
            return
        
        try:
            with open(path, 'w') as f:
                json.dump(self.cheats, f, indent=2)
            self.output.insert(tk.END, f"Saved {len(self.cheats)} cheats to {path}\n")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save: {e}")

    def load_cheats(self):
        """Load cheats from a JSON file."""
        path = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")])
        if not path:
            return
        
        try:
            with open(path, 'r') as f:
                cheats = json.load(f)
            
            self.cheats = cheats
            self.cheat_tree.delete(*self.cheat_tree.get_children())
            
            for cheat in cheats:
                desc = cheat.get("description", "No description")
                addr = cheat.get("offset", "?")
                value = cheat.get("value", "?")
                self.cheat_tree.insert("", tk.END, values=(desc, addr, value))
            
            self.output.insert(tk.END, f"Loaded {len(cheats)} cheats from {path}\n")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load: {e}")

    def export_atmosphere(self):
        """Export cheats to Atmosphere format (.txt)."""
        if not self.cheats:
            messagebox.showwarning("Warning", "No cheats to export")
            return
        
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text Files", "*.txt")])
        if not path:
            return
        
        try:
            with open(path, 'w') as f:
                f.write("[CheatEngineNX Export]\n")
                for cheat in self.cheats:
                    desc = cheat.get("description", "Cheat")
                    offset = cheat.get("offset", "0x0")
                    value = cheat.get("value", "0")
                    f.write(f"[{desc}]\n")
                    f.write(f"04000000 {offset} {value}\n\n")
            
            self.output.insert(tk.END, f"Exported to Atmosphere format: {path}\n")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export: {e}")

    def apply_selected_cheat(self):
        """Apply the selected cheat."""
        selection = self.cheat_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No cheat selected")
            return
        
        for item in selection:
            idx = self.cheat_tree.index(item)
            if idx < len(self.cheats):
                cheat = self.cheats[idx]
                try:
                    addr_type = cheat["address_type"]
                    offset_val = int(cheat["offset"], 16)
                    value = cheat["value"]

                    if addr_type == "Absolute":
                        self._poke_absolute(offset_val, value)
                    elif addr_type == "Main NSO Relative":
                        self._poke_main(offset_val, value)
                    elif addr_type == "Heap Relative":
                        self._poke_heap(offset_val, value)
                    else:
                        raise ValueError(f"Unknown address type: {addr_type}")

                    self.output.insert(tk.END, f"Applied: {cheat['description']}\n")
                except Exception as e:
                    self.output.insert(tk.END, f"Failed to apply cheat: {e}\n")

    def remove_selected_cheat(self):
        """Remove the selected cheat."""
        selection = self.cheat_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No cheat selected")
            return
        
        for item in reversed(selection):
            idx = self.cheat_tree.index(item)
            self.cheat_tree.delete(item)
            if idx < len(self.cheats):
                del self.cheats[idx]

    def _sync_mb_from_end(self, event=None):
        """Sync the MB field when the end offset is changed."""
        try:
            start = int(self.scan_start_entry.get(), 16)
            end = int(self.scan_end_entry.get(), 16)
            mb = max(0, (end - start) // (1024 * 1024))
            if str(mb) != self.scan_mb_entry.get():
                self.scan_mb_entry.delete(0, tk.END)
                self.scan_mb_entry.insert(0, str(mb))
        except:
            pass

    def _sync_end_from_mb(self, event=None):
        """Sync the end offset field when the MB field is changed."""
        try:
            start = int(self.scan_start_entry.get(), 16)
            mb = int(self.scan_mb_entry.get())
            end = start + mb * 1024 * 1024
            if hex(end) != self.scan_end_entry.get():
                self.scan_end_entry.delete(0, tk.END)
                self.scan_end_entry.insert(0, hex(end))
        except:
            pass

    def first_scan(self):
        """Perform the first memory scan with improved algorithm."""
        if not self.connected:
            messagebox.showerror("Error", "Not connected to Switch")
            return
        
        self._scan_cancelled = False
        self.cancel_scan_btn.config(state=tk.NORMAL)
        self._scan_results = []
        self.scan_tree.delete(*self.scan_tree.get_children())
        
        comparison = self.scan_comparison_combo.get()
        value_size = self._get_scan_value_size()
        value_type = self._get_scan_value_type()
        
        # Handle unknown initial value scan
        if comparison == "Unknown Initial Value":
            self._is_unknown_scan = True
            value = None
        else:
            self._is_unknown_scan = False
            value_str = self.scan_value_entry.get().strip()
            value = self._parse_scan_value(value_str, value_size, value_type)
            if value is None and comparison not in ["Increased Value", "Decreased Value", "Changed Value", "Unchanged Value"]:
                messagebox.showerror("Error", "Invalid value to search")
                self.cancel_scan_btn.config(state=tk.DISABLED)
                return
        
        start_addr = self._get_scan_base() + int(self.scan_start_entry.get(), 16)
        end_addr = self._get_scan_base() + int(self.scan_end_entry.get(), 16)
        chunk_size = int(self.scan_chunk_entry.get(), 16)
        
        # Warn for large scans
        scan_size = end_addr - start_addr
        if scan_size > 64 * 1024 * 1024:  # 64MB
            if not messagebox.askyesno("Large Scan", f"Scanning {scan_size // (1024*1024)}MB may take several minutes. Continue?"):
                self.cancel_scan_btn.config(state=tk.DISABLED)
                return
        
        total_chunks = max(1, scan_size // chunk_size)
        
        def scan_worker():
            chunk_idx = 0
            start_time = threading.Event()
            
            def update_progress():
                if total_chunks > 0:
                    percent = int(100 * chunk_idx / total_chunks)
                    self.scan_progress['value'] = chunk_idx
                    
                    # Estimate time remaining
                    if chunk_idx > 0:
                        elapsed = threading.current_thread().elapsed if hasattr(threading.current_thread(), 'elapsed') else 0
                        if elapsed > 0:
                            eta = (elapsed / chunk_idx) * (total_chunks - chunk_idx)
                            self.scan_status_label.config(text=f"Scanning... {percent}% (ETA: {int(eta)}s)")
                        else:
                            self.scan_status_label.config(text=f"Scanning... {percent}%")
                    else:
                        self.scan_status_label.config(text=f"Scanning... {percent}%")
            
            self.scan_progress['maximum'] = total_chunks
            self.scan_progress['value'] = 0
            self.scan_status_label.config(text="Scanning... 0%")
            
            import time
            scan_start = time.time()
            
            # Parse value2 for 'Between'
            value2 = None
            if comparison == "Between":
                value2_str = self.scan_value2_entry.get().strip()
                value2 = self._parse_scan_value(value2_str, value_size, value_type)
                if value2 is None:
                    self.after(0, lambda: messagebox.showerror("Error", "Invalid second value for 'Between'"))
                    self.after(0, lambda: self.cancel_scan_btn.config(state=tk.DISABLED))
                    return
            
            for addr in range(start_addr, end_addr, chunk_size):
                if self._scan_cancelled:
                    self.after(0, lambda: self.scan_status_label.config(text="Scan cancelled"))
                    self.after(0, lambda: self.cancel_scan_btn.config(state=tk.DISABLED))
                    return
                
                read_size = min(chunk_size, end_addr - addr)
                data = self._peek_absolute(addr, read_size, timeout=15)
                
                if data:
                    matches = self._find_value_in_bytes(
                        data, value, value_size, value_type, addr, 
                        self._get_scan_base(), value2, comparison
                    )
                    
                    for m_addr, m_val, prev_val, rel_offset in matches:
                        self._scan_results.append((m_addr, m_val, prev_val, rel_offset))
                        
                        # Limit display to first 1000 results for performance
                        if len(self._scan_results) <= 1000:
                            self.after(0, lambda a=m_addr, r=rel_offset, v=m_val: 
                                      self.scan_tree.insert("", tk.END, values=(
                                          hex(a), hex(r), v, self.scan_size_combo.get()
                                      )))
                
                chunk_idx += 1
                threading.current_thread().elapsed = time.time() - scan_start
                self.after(0, update_progress)
            
            total_time = time.time() - scan_start
            result_msg = f"Found {len(self._scan_results)} matches in {total_time:.1f}s"
            if len(self._scan_results) > 1000:
                result_msg += " (showing first 1000)"
            
            self.after(0, lambda: self.scan_status_label.config(text=result_msg))
            self.after(0, lambda: self.cancel_scan_btn.config(state=tk.DISABLED))
            self.after(0, lambda: self.output.insert(tk.END, f"[Scanner] {result_msg}\n"))
        
        threading.Thread(target=scan_worker, daemon=True).start()

    def next_scan(self):
        """Refine scan results with improved comparison logic."""
        if not self._scan_results:
            messagebox.showwarning("Warning", "No previous scan results to refine")
            return
        
        comparison = self.scan_comparison_combo.get()
        value_size = self._get_scan_value_size()
        value_type = self._get_scan_value_type()
        
        # For change-based comparisons, we don't need a new value
        if comparison in ["Increased Value", "Decreased Value", "Changed Value", "Unchanged Value"]:
            new_value = None
        else:
            value_str = self.scan_value_entry.get().strip()
            new_value = self._parse_scan_value(value_str, value_size, value_type)
            if new_value is None:
                messagebox.showerror("Error", "Invalid value to search")
                return
        
        new_results = []
        self.scan_tree.delete(*self.scan_tree.get_children())
        
        for addr, old_val, prev_val, rel_offset in self._scan_results:
            data = self._peek_absolute(addr, value_size)
            if not data:
                continue
            
            try:
                data_bytes = binascii.unhexlify(data.replace(" ", "").replace("\n", ""))
                current_val = self._parse_value_from_bytes(data_bytes, value_size, value_type)
                
                # Apply comparison
                match = False
                if comparison == "Exact Value":
                    match = self._compare_values(current_val, new_value, value_type, "==")
                elif comparison == "Greater Than":
                    match = current_val > new_value
                elif comparison == "Less Than":
                    match = current_val < new_value
                elif comparison == "Increased Value":
                    match = current_val > old_val
                elif comparison == "Decreased Value":
                    match = current_val < old_val
                elif comparison == "Changed Value":
                    match = not self._compare_values(current_val, old_val, value_type, "==")
                elif comparison == "Unchanged Value":
                    match = self._compare_values(current_val, old_val, value_type, "==")
                
                if match:
                    new_results.append((addr, current_val, old_val, rel_offset))
                    if len(new_results) <= 1000:
                        self.scan_tree.insert("", tk.END, values=(
                            hex(addr), hex(rel_offset), current_val, self.scan_size_combo.get()
                        ))
            except:
                continue
        
        self._scan_results = new_results
        msg = f"Refined to {len(new_results)} matches"
        if len(new_results) > 1000:
            msg += " (showing first 1000)"
        self.output.insert(tk.END, f"[Scanner] {msg}\n")
        self.scan_status_label.config(text=msg)

    def pointer_scan(self):
        """Simple pointer scanner - finds addresses that point to the selected result."""
        selection = self.scan_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Select a scan result first")
            return
        
        item = selection[0]
        values = self.scan_tree.item(item)['values']
        target_addr = int(values[0], 16)
        
        if not messagebox.askyesno("Pointer Scan", 
            f"Scan for pointers to {hex(target_addr)}?\n"
            "This will search Main NSO region and may take time."):
            return
        
        self.output.insert(tk.END, f"[Pointer] Scanning for pointers to {hex(target_addr)}...\n")
        
        def pointer_worker():
            # Search in Main NSO region
            start = self.main_nso_base
            end = self.main_nso_base + 0x10000000  # 256MB
            chunk_size = 0x100000
            
            pointers = []
            for addr in range(start, end, chunk_size):
                if self._scan_cancelled:
                    return
                
                read_size = min(chunk_size, end - addr)
                data = self._peek_absolute(addr, read_size)
                
                if data:
                    try:
                        data_bytes = binascii.unhexlify(data.replace(" ", "").replace("\n", ""))
                        for i in range(0, len(data_bytes) - 8, 4):  # 4-byte aligned
                            ptr_val = int.from_bytes(data_bytes[i:i+8], byteorder='little', signed=False)
                            if ptr_val == target_addr:
                                ptr_addr = addr + i
                                offset = ptr_addr - self.main_nso_base
                                pointers.append((ptr_addr, offset))
                                self.after(0, lambda p=ptr_addr, o=offset: 
                                          self.output.insert(tk.END, 
                                              f"[Pointer] Found at {hex(p)} (offset {hex(o)})\n"))
                    except:
                        continue
            
            self.after(0, lambda: self.output.insert(tk.END, 
                f"[Pointer] Scan complete. Found {len(pointers)} pointer(s).\n"))
        
        threading.Thread(target=pointer_worker, daemon=True).start()

    def _get_scan_base(self) -> int:
        """Get the base address for scanning."""
        t = self.scan_addr_type.get()
        if t == "Absolute":
            return 0
        elif t == "Main NSO Relative":
            return self.main_nso_base
        elif t == "Heap Relative":
            return self.heap_base
        return 0

    def _get_scan_value_size(self) -> int:
        """Get the value size in bytes."""
        return self._get_type_size(self.scan_size_combo.get())

    def _get_scan_value_type(self) -> str:
        """Get the value type: 'float', 'signed', or 'unsigned'."""
        size_str = self.scan_size_combo.get()
        if "float" in size_str:
            return 'float'
        elif "signed" in size_str:
            return 'signed'
        return 'unsigned'

    def _parse_scan_value(self, value_str: str, value_size: int, value_type: str) -> Optional[float]:
        """Parse the value to search for."""
        try:
            if value_type == 'float':
                if value_str.lower().startswith("0x"):
                    as_int = int(value_str, 16)
                    if value_size == 4:
                        return struct.unpack('<f', as_int.to_bytes(4, 'little'))[0]
                    elif value_size == 8:
                        return struct.unpack('<d', as_int.to_bytes(8, 'little'))[0]
                return float(value_str)
            else:
                if value_str.lower().startswith("0x"):
                    return int(value_str, 16)
                return int(value_str)
        except:
            return None

    def _parse_value_from_bytes(self, data_bytes: bytes, value_size: int, value_type: str) -> float:
        """Parse a value from bytes."""
        if value_type == 'float':
            if value_size == 4:
                return struct.unpack('<f', data_bytes[:4])[0]
            elif value_size == 8:
                return struct.unpack('<d', data_bytes[:8])[0]
        elif value_type == 'signed':
            return int.from_bytes(data_bytes[:value_size], byteorder='little', signed=True)
        else:
            return int.from_bytes(data_bytes[:value_size], byteorder='little', signed=False)

    def _compare_values(self, val1: float, val2: float, value_type: str, op: str) -> bool:
        """Compare two values with appropriate epsilon for floats."""
        if value_type == 'float':
            epsilon = 1e-6
            if op == "==":
                return abs(val1 - val2) < epsilon
        else:
            if op == "==":
                return val1 == val2
        return False

    def _find_value_in_bytes(self, data: str, value: Optional[float], value_size: int, 
                            value_type: str, base_addr: int, scan_base: int,
                            value2: Optional[float] = None, comparison: str = "Exact Value") -> List[Tuple[int, float, float, int]]:
        """
        Find all occurrences matching the comparison criteria.
        Returns list of (address, current_value, prev_value, relative_offset) tuples.
        """
        try:
            data_bytes = binascii.unhexlify(data.replace(" ", "").replace("\n", ""))
        except:
            return []
        
        matches = []
        
        for i in range(0, len(data_bytes) - value_size + 1):
            chunk = data_bytes[i:i+value_size]
            
            try:
                chunk_val = self._parse_value_from_bytes(chunk, value_size, value_type)
            except:
                continue
            
            # Comparison logic
            match = False
            
            if comparison == "Unknown Initial Value":
                # Store all values for first unknown scan
                match = True
            elif comparison == "Exact Value":
                match = self._compare_values(chunk_val, value, value_type, "==")
            elif comparison == "Greater Than":
                match = chunk_val > value
            elif comparison == "Less Than":
                match = chunk_val < value
            elif comparison == "Between" and value2 is not None:
                match = (value <= chunk_val <= value2) or (value2 <= chunk_val <= value)
            
            if match:
                abs_addr = base_addr + i
                rel_offset = abs_addr - scan_base
                # For first scan, prev_value = current_value
                matches.append((abs_addr, chunk_val, chunk_val, rel_offset))
        
        return matches

    def add_scan_result_to_cheat(self):
        """Add the selected scan result to the cheat list and populate memory section."""
        selection = self.scan_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No scan result selected")
            return
        
        item = selection[0]
        values = self.scan_tree.item(item)['values']
        
        addr = int(values[0], 16)
        offset = int(values[1], 16)
        value = values[2]
        value_type_str = values[3]
        
        # Determine address type
        addr_type = self.scan_addr_type.get()
        base = self._get_scan_base()
        
        value_type = self._get_scan_value_type()
        value_size = self._get_scan_value_size()
        
        # Convert value to hex
        if value_type == 'float':
            if value_size == 4:
                value_bytes = struct.pack('<f', float(value))
            elif value_size == 8:
                value_bytes = struct.pack('<d', float(value))
            else:
                value_bytes = b''
            value_hex = value_bytes.hex()
        else:
            value_hex = hex(int(value))[2:].zfill(value_size * 2)
        
        cheat = {
            "description": f"Scan_{hex(addr)}",
            "address_type": addr_type,
            "offset": hex(offset),
            "value": value_hex
        }
        
        self.cheats.append(cheat)
        self.cheat_tree.insert("", tk.END, values=(cheat["description"], hex(offset), value_hex))
        self.output.insert(tk.END, f"[Scanner] Added {hex(addr)} to cheats.\n")
        
        # Auto-populate Memory Access section
        self.addr_type.set(addr_type)
        self.addr_entry.delete(0, tk.END)
        self.addr_entry.insert(0, hex(offset))
        self.mem_value_type_combo.set(value_type_str)
        self.value_entry.delete(0, tk.END)
        self.value_entry.insert(0, str(value))

    def cancel_scan(self):
        """Cancel an ongoing scan."""
        self._scan_cancelled = True
        self.scan_status_label.config(text="Cancelling...")

    def _add_hex_validation(self, entry_widget):
        """Add regex validation for hex input."""
        def validate_hex(event):
            text = entry_widget.get()
            # Allow 0x prefix and hex characters
            if text and not all(c in '0123456789abcdefABCDEFx' for c in text):
                entry_widget.delete(0, tk.END)
                entry_widget.insert(0, ''.join(c for c in text if c in '0123456789abcdefABCDEFx'))
        
        entry_widget.bind('<KeyRelease>', validate_hex)

    def _add_addr_type_tooltip(self, combobox):
        """Attach tooltips to address type combobox."""
        tooltip_texts = {
            "Absolute": "Fixed memory address in Switch RAM (e.g., 0x65ffc01234)",
            "Main NSO Relative": "Offset from Main NSO Base (game executable)",
            "Heap Relative": "Offset from Heap Base (dynamic allocations)"
        }
        
        class ToolTip:
            def __init__(self, widget, text):
                self.widget = widget
                self.text = text
                self.tipwindow = None
                self.widget.bind("<Enter>", self.show_tip)
                self.widget.bind("<Leave>", self.hide_tip)
            
            def show_tip(self, event=None):
                if self.tipwindow or not self.text:
                    return
                x = self.widget.winfo_rootx() + 30
                y = self.widget.winfo_rooty() + 20
                self.tipwindow = tw = tk.Toplevel(self.widget)
                tw.wm_overrideredirect(True)
                tw.wm_geometry(f"+{x}+{y}")
                label = tk.Label(tw, text=self.text, justify=tk.LEFT, 
                               background="#ffffe0", relief=tk.SOLID, 
                               borderwidth=1, font=(None, 9))
                label.pack(ipadx=1)
            
            def hide_tip(self, event=None):
                tw = self.tipwindow
                self.tipwindow = None
                if tw:
                    tw.destroy()
        
        summary = "Address Type:\n" + "\n".join(f"• {k}: {v}" for k, v in tooltip_texts.items())
        ToolTip(combobox, summary)


# Standalone execution
if __name__ == "__main__":
    root = tk.Tk()
    root.title("CheatEngineNX Enhanced - Standalone Memory Editor")
    root.geometry("1000x800")
    
    # Apply theme
    style = ttk.Style()
    style.theme_use('clam')
    
    notebook = ttk.Notebook(root)
    cheat_tab = CheatEngineTab(notebook)
    notebook.add(cheat_tab, text="Cheat Engine")
    notebook.pack(fill="both", expand=True)
    
    root.mainloop()
