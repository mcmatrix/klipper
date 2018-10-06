# -*- coding: utf-8 -*-
# Menu based probing wizard
#
# Copyright (C) 2018  Eric Callahan <arksine.code@gmail.com>
# Copyright (C) 2018  Janar Sööt <janar.soot@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, os


class ProbeHelperMenu:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.toolhead = self.menu = None
        # Load menu system
        if(config.has_section('display')
                and self.printer.try_load_module(config, 'display')):
            self.menu = self.printer.try_load_module(config, 'menu')
        # Load probe menu
        if self.menu:
            self.menu.load_config(os.path.join(
                os.path.dirname(__file__), 'probe_menu.cfg'))
        # Probing context
        self._wait_for_input = False
        self._wizard_running = False

    def printer_state(self, state):
        if state == 'ready':
            self.toolhead = self.printer.lookup_object('toolhead')

    def printer_event(self, event, *args):
        if event == "probe:start_manual_probe":
            self.start_manual_probe(*args)
        elif event == "probe:end_manual_probe":
            self.end_manual_probe(*args)
        elif event == "probe:finalize_probe":
            self.finalize_probe(*args)

    def get_status(self, eventtime):
        return {
            'input': self._wait_for_input,
            'running': self._wizard_running
        }

    def start_probe_wizard(self):
        if self.menu:
            # self.menu.register_object(self, 'probe_menu', override=True)
            self._wizard_running = True
            try:
                self.menu.restart_root('__probe_helper')
            except (self.menu.error, self.printer.config_error) as e:
                msg = "Could not load probe menu.\n%s" % (e.message,)
                logging.exception(msg)
                self.gcode.respond_info(msg)
                # self.menu.unregister_object('probe_menu')
                self.menu.restart_root()
                self.menu = None
                self._wizard_running = False

    def close_probe_wizard(self):
        self._wizard_running = False
        if self.menu:
            self.menu.restart_root()
            # self.menu.unregister_object('probe_menu')

    # probe event methotds
    def start_manual_probe(self, print_time):
        self._wait_for_input = False
        if not self._wizard_running:
            self.start_probe_wizard()
        self.toolhead.wait_moves()
        self._wait_for_input = True

    def end_manual_probe(self, print_time):
        self._wait_for_input = False

    def finalize_probe(self, success):
        self._wait_for_input = False
        self.close_probe_wizard()


def load_config_prefix(config):
    return ProbeHelperMenu(config)
