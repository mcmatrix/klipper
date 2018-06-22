# Test code for button reading
#
# Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
import Queue
from collections import deque

QUERY_TIME = .005

class error(Exception):
    pass

class PrinterButtons:
    def __init__(self, config):
        ppins = config.get_printer().lookup_object('pins')
        mcu = None
        self.button_list = {}
        self.pin_list = []
        self.encoder_a_pin = None
        self.encoder_b_pin = None
        self.encoder_decode_tbl = (
            (0b00, 0b10, 0b01, 0b11),
            (0b01, 0b00, 0b11, 0b10),
            (0b10, 0b11, 0b00, 0b01),
            (0b11, 0b01, 0b10, 0b00))
        self.encoder_pos = 0
        self.encoder_last_bits = 0
        self.encoder_last_pos = 0
        self.encoder_steps = Queue.Queue(1)
        self.encoder_resolution = 1
        # running average test, keep track of seen values
        self.encoder_pos_cache = deque(maxlen=5)
        # setup
        for pin in config.get('pins').split(','):
            pin_params = ppins.lookup_pin('digital_in', pin.strip())
            if mcu is not None and pin_params['chip'] != mcu:
                raise ppins.error("All buttons must be on same mcu")
            mcu = pin_params['chip']
            self.pin_list.append((pin_params['pin'], pin_params['pullup'], pin_params['invert']))
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
    def handle_encoder_state(self, encoder_a, encoder_b):
        # 0b00 for no change
        # 0b01 for rotated right (CW)
        # 0b10 for rotated left (CCW)
        # 0b11 for invalid transistion        
        encoder_bits = 0
        if encoder_a:
            encoder_bits |= 0b01
        if encoder_b:
            encoder_bits |= 0b10        
        state = self.encoder_decode_tbl[encoder_bits][self.encoder_last_bits]
        self.encoder_last_bits = encoder_bits
        if state == 0b01: # cw
            self.encoder_pos += 1
        if state == 0b10: # ccw
            self.encoder_pos -= 1
        # use running average to smooth encoder jitter
        self.encoder_pos_cache.append(self.encoder_pos)
        return int(sum(self.encoder_pos_cache) / len(self.encoder_pos_cache))

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
            # handle encoder
            if self.encoder_a_pin and self.encoder_b_pin:
                pos = self.handle_encoder_state(self.encoder_a_pin in pressed_pins, self.encoder_b_pin in pressed_pins)
                diff = pos - self.encoder_last_pos
                if abs(diff) >= self.encoder_resolution:
                    try:
                        self.encoder_steps.put(int(diff / self.encoder_resolution), False)                        
                    except:
                        pass
                    self.encoder_last_pos = pos
            # handle buttons
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
    
    def get_encoder_steps(self):
        steps = 0
        try:
            steps = self.encoder_steps.get(False)
            self.encoder_steps.task_done()
        except:
            pass
        return steps

    def setup_encoder(self, pin_a, pin_b, resolution=1):
        if not self.pin_exists(pin_a):
            raise error("Pin '%s' is not defined as button" % (pin_a,))
        if not self.pin_exists(pin_b):
            raise error("Pin '%s' is not defined as button" % (pin_b,))        
        self.encoder_a_pin = pin_a
        self.encoder_b_pin = pin_b
        self.encoder_resolution = resolution
        self.encoder_dir = Queue.Queue(1)

    def pin_exists(self, p):
        out = False
        for pin, pull_up, invert in self.pin_list:
            if pin == p:
                out = True
        return out

    def register_button(self, name, pin):
        if name in self.button_list:
            raise error("Button '%s' is already registred" % (name,))        

        if self.pin_exists(pin):
            self.button_list[name] = (pin, Queue.Queue(1))
        else:
            raise error("Pin '%s' is not defined as button" % (pin,))

def load_config(config):
    return PrinterButtons(config)
