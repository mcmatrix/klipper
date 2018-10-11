# -*- coding: utf-8 -*-
# Menu based probing wizard
#
# Copyright (C) 2018  Janar Sööt <janar.soot@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import os


class ProbeHelperMenu:
    def __init__(self, config, menu):
        self.printer = config.get_printer()
        self.toolhead = None
        # Load menu
        self.probe_menuroot = "__probe_helper"
        self.menu = menu
        self.menu.load_config(os.path.dirname(__file__), 'probe_menu.cfg')
        # check menuitem
        self.menu.lookup_menuitem(self.probe_menuroot)
        # Probing context
        self._wait_for_input = False
        self._wizard_running = False
        self._points_current = 0
        self._points_count = 0
        # Register event handler
        self.printer.register_event_handler("probe:start_manual_probe",
                                            self.handle_probe_start)
        self.printer.register_event_handler("probe:end_manual_probe",
                                            self.handle_probe_end)
        self.printer.register_event_handler("probe:finalize_probe",
                                            self.handle_probe_finalize)

    def printer_state(self, state):
        if state == 'ready':
            self.toolhead = self.printer.lookup_object('toolhead')

    def get_status(self, eventtime):
        return {
            'input': self._wait_for_input,
            'running': self._wizard_running,
            'index': (self._points_current+1),
            'length': (self._points_count),
            'remaining': max(0, self._points_count-(self._points_current+1))
        }

    def start_probe_wizard(self):
        if self.menu:
            self.menu.register_object(self, 'probe_menu', override=True)
            self._wizard_running = True
            self.menu.restart_root(self.probe_menuroot)

    def close_probe_wizard(self, eventtime):
        self._wizard_running = False
        if self.menu:
            self.menu.restart_root()
            self.menu.unregister_object('probe_menu')

    def wait_toolhead_moves(self, eventtime, print_time):
        est_print_time = self.toolhead.get_status(
            eventtime)['estimated_print_time']
        if est_print_time >= print_time:
            self._wait_for_input = True
        else:
            self.menu.after(500, self.wait_toolhead_moves, print_time)

    # probe event methods
    def handle_probe_start(self, print_time):
        self._wait_for_input = False
        if not self._wizard_running:
            self.start_probe_wizard()
        reactor = self.printer.get_reactor()
        self.wait_toolhead_moves(reactor.monotonic(), print_time)

    def handle_probe_end(self, print_time):
        self._wait_for_input = False

    def next_position(self, print_time, curpos, index, length):
        self._points_current = index
        self._points_count = length

    def handle_probe_finalize(self, print_time, success):
        self._wait_for_input = False
        self.menu.after(2000, self.close_probe_wizard)


def load_config(config):
    return ProbeHelperMenu(config)
