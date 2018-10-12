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
        self._end_status = 0
        self._points_current = 0
        self._points_count = 0
        # register itself for a printer_state callback
        self.printer.add_object('probe_menu', self)
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
            'length': self._points_count,
            'end_status': self._end_status,
            'remaining': max(0, self._points_count-(self._points_current+1))
        }

    def start_probe_wizard(self):
        if self.menu:
            self._wizard_running = True
            self.menu.restart_root(self.probe_menuroot)

    def close_probe_wizard(self, eventtime):
        self._wait_for_input = False
        self._wizard_running = False
        self._end_status = 0
        self._points_current = 0
        self._points_count = 0
        if self.menu:
            self.menu.restart_root()

    def wait_toolhead_moves(self, eventtime, print_time):
        est_print_time = self.toolhead.get_status(
            eventtime)['estimated_print_time']
        if est_print_time >= print_time:
            self._wait_for_input = True
        else:
            self.menu.after(0.5, self.wait_toolhead_moves, print_time)

    # probe event methods
    def handle_probe_start(self, print_time, points, results):
        self._wait_for_input = False
        self._points_current = len(results)
        self._points_count = len(points)
        if not self._wizard_running:
            self.start_probe_wizard()
        self.menu.after(0, self.wait_toolhead_moves, print_time)

    def handle_probe_end(self, print_time):
        self._wait_for_input = False

    def handle_probe_finalize(self, print_time, success):
        self._wait_for_input = False
        self._wizard_running = False
        self._end_status = success
        self.menu.after(2., self.close_probe_wizard)


def load_config(config):
    return ProbeHelperMenu(config)
