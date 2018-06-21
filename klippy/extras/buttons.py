# Test code for button reading
#
# Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
import Queue

QUERY_TIME = .005

class error(Exception):
    pass

class PrinterButtons:
    def __init__(self, config):
        ppins = config.get_printer().lookup_object('pins')
        mcu = None
        self.button_list = {}
        self.pin_list = []
        for pin in config.get('pins').split(','):
            pin_params = ppins.lookup_pin('digital_in', pin.strip())
            if mcu is not None and pin_params['chip'] != mcu:
                raise ppins.error("All buttons must be on same mcu")
            mcu = pin_params['chip']
            self.pin_list.append((pin_params['pin'], pin_params['pullup'],
                                  pin_params['invert']))
        self.mcu = mcu
        self.oid = mcu.create_oid()
        mcu.add_config_cmd("config_buttons oid=%d button_count=%d" % (
            self.oid, len(self.pin_list)))
        mcu.add_config_cmd("buttons_query clock=0 rest_ticks=0", is_init=True)
        for i, (pin, pull_up, invert) in enumerate(self.pin_list):
            mcu.add_config_cmd("buttons_add pos=%d pin=%s pull_up=%d" % (
                i, pin, pull_up), is_init=True)
        mcu.add_config_object(self)
        self.ack_cmd = None
        self.ack_count = 0
    def build_config(self):
        cmd_queue = self.mcu.alloc_command_queue()
        self.ack_cmd = self.mcu.lookup_command(
            "buttons_ack count=%c", cq=cmd_queue)
        clock = self.mcu.get_query_slot(self.oid)
        rest_ticks = self.mcu.seconds_to_clock(QUERY_TIME)
        self.mcu.add_config_cmd("buttons_query clock=%d rest_ticks=%d" % (
            clock, rest_ticks), is_init=True)
        self.mcu.register_msg(self.handle_buttons_state, "buttons_state")
    def handle_buttons_state(self, params):
        # Expand the message ack_count from 8-bit
        ack_count = self.ack_count
        ack_diff = (ack_count - params['ack_count']) & 0xff
        if ack_diff & 0x80:
            ack_diff -= 0x100
        msg_ack_count = ack_count - ack_diff
        # Determine new buttons
        buttons = params['state']
        new_count = msg_ack_count + len(buttons) - self.ack_count
        if new_count > 0:
            new_buttons = buttons[-new_count:]
            self.ack_cmd.send([new_count])
            self.ack_count += new_count
        else:
            new_buttons = ""
        # Report via log..
        logging.debug("state: %d: %s (%d %d: %s)", new_count, repr(new_buttons),
                      self.ack_count, params['ack_count'], repr(buttons))
        out_pins = []
        out_btns = []
        for b in new_buttons:
            b = ord(b)
            pressed_pins = [pin for i, (pin, pull_up, invert) in enumerate(self.pin_list) if ((b>>i) & 1) ^ invert]
            pressed_buttons = []
            for name, (pin, q) in self.button_list.items():        
                if pin in pressed_pins:
                    pressed_buttons.append(name)
                    try:
                        q.put(name, False)
                    except:
                        pass
            out_pins.append(','.join(pressed_pins))
            out_btns.append(','.join(pressed_buttons))
        logging.info("buttons_pins=%s", ' '.join(out_pins))
        logging.info("buttons_btns=%s", ' '.join(out_btns))

    def check_button(self, name):
        press = None
        if name in self.button_list:            
            try:
                press = not not self.button_list[name][1].get(False)
                self.button_list[name][1].task_done()
            except:
                press = False
        return press
                        
    def register_button(self, name, btnpin):
        if name in self.button_list:
            raise error("Button '%s' is already registred" % (name,))        
        if any(btnpin in pin for (pin, pull_up, invert) in self.pin_list):
            raise error("Pin '%s' is not defined as button" % (btnpin,))        
        self.button_list[name] = (btnpin, Queue.Queue(1))

def load_config(config):
    return PrinterButtons(config)
