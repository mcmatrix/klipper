﻿# Basic LCD menu support
#
# Based on the RaspberryPiLcdMenu from Alan Aufderheide, February 2013
# Copyright (C) 2018  Janar Sööt <janar.soot@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, sys, ast

class error(Exception):
    pass

class MenuItemBase:
    def __init__(self, menu, config):
        self.menu = menu
        self.name = ''
        self.enable = config.get('enable', repr(True))
    
    def _get_name(self):
        return self.name

    def is_enabled(self):
        enabled = False
        if type(self.enable) == str and len(self.enable) > 0:
            try:
                enabled = not not ast.literal_eval(self.enable)
            except:
                if self.enable[0] == '!': # negation
                    enabled = not (not not self.menu.lookup_value(self.enable[1:]))
                else:
                    enabled = not not self.menu.lookup_value(self.enable)                    
        return enabled

    def __str__(self):
        return str(self._get_name())

class MenuItemCommand(MenuItemBase):
    def __init__(self, menu, config):
        MenuItemBase.__init__(self, menu, config)
        self.name = config.get('name')
        self.gcode = config.get('gcode', None)        
        self.parameter, self.options, self.typecast = self.parse_parameter(config.get('parameter', ''))

    def parse_parameter(self, str = ''):
        # endstop.xmax:f['OFF','ON']
        conv = {'f': float, 'i': int, 'b': bool, 's': str}
        t = str.split(':', 1)
        p = t[0] if t[0] else None
        o = None
        c = None
        if len(t) > 1 and t[1] and t[1][0] in conv:
            try:
                o = ast.literal_eval(t[1][1:])
                c = conv[t[1][0]]
            except:
                pass
        return [p, o, c]

    def get_format_args(self, value = None):
        option = None
        if self.parameter:            
            if value is None:
                value = self.menu.lookup_value(self.parameter)
            if self.options is not None:
                try:                    
                    if callable(self.typecast):
                        option = self.options[self.typecast(value)]
                    else:
                        option = self.options[value]
                except:
                    pass
        return [value, option]

    def _get_formatted(self, literal, value = None):
        args = self.get_format_args(value)
        if type(literal) == str and len(args) > 0:
            try:
                literal = literal.format(*args)
            except:
                pass
        return literal

    def _get_name(self):
        return self._get_formatted(self.name)

    def get_gcode(self):
        return self._get_formatted(self.gcode)

class MenuItemInput(MenuItemCommand):
    def __init__(self, menu, config):
        MenuItemCommand.__init__(self, menu, config)
        self.input_value = None
        self.input_min = config.getfloat('input_min', sys.float_info.min)
        self.input_max = config.getfloat('input_max', sys.float_info.max)
        self.input_step = config.getfloat('input_step', above=0.)
    
    def _get_name(self):        
        return self._get_formatted(self.name, self.input_value)

    def get_gcode(self):
        return self._get_formatted(self.gcode, self.input_value)
    
    def is_editing(self):
        return self.input_value is not None

    def init_value(self):
        args = self.get_format_args()
        if len(args) > 0:
            try:
                self.input_value = float(args[0])
            except:
                self.input_value = None
    
    def reset_value(self):
        self.input_value = None

    def inc_value(self):
        self.input_value += abs(self.input_step) 
        self.input_value = min(self.input_max, max(self.input_min, self.input_value))

    def dec_value(self):
        self.input_value -= abs(self.input_step) 
        self.input_value = min(self.input_max, max(self.input_min, self.input_value))

class MenuItemGroup(MenuItemBase):
    def __init__(self, menu, config):
        MenuItemBase.__init__(self, menu, config)
        self.name = config.get('name')
        self.items = []
        self._items = config.get('items')
        self.enter_gcode = config.get('enter_gcode', None)
        self.leave_gcode = config.get('leave_gcode', None)

    def populate_items(self):
        self.items = [] # empty list
        self.items.append('..') # always add back as first item
        for name in self._items.split(','):
            item = self.menu.lookup_menuitem(name.strip())
            if item.is_enabled():
                self.items.append(item)

    def get_enter_gcode(self):
        return self.enter_gcode

    def get_leave_gcode(self):
        return self.leave_gcode

class MenuItemRow(MenuItemBase):
    def __init__(self, menu, config):
        MenuItemBase.__init__(self, menu, config)
        self.items = []
        self.selected = None
        self._items = config.get('items')

    def populate_items(self):
        self.items = [] # empty list
        for name in self._items.split(','):
            item = self.menu.lookup_menuitem(name.strip())
            if not isinstance(item, (MenuItemInput, MenuItemCommand)):
                raise error("Not allowed menuitem type has been specified!")
            if item.is_enabled():
                self.items.append(item)

    def _get_name(self):
        str = ""
        for i, item in enumerate(self.items):
            name = "%s" % item
            if i == self.selected and self.menu.blink_state:
                str += ' '*len(name)
            else:
                str += name
        return str

    def _call_current(self, method = None):
        res = None
        try:
            res = (getattr(self.items[self.selected], method)() if method is not None else self.items[self.selected])
        except:
            pass
        return res

    def is_editing(self):
        return self._call_current('is_editing')

    def inc_value(self):
        self._call_current('inc_value')

    def dec_value(self):
        self._call_current('dec_value')

    def curr_item(self):
        return self._call_current()

    def next_item(self):
        if self.selected is None:
            self.selected = 0
        elif self.selected < len(self.items) - 1:
            self.selected += 1
        else: 
            self.selected = None
        return self.selected

    def prev_item(self):
        if self.selected is None:
            self.selected = len(self.items) - 1
        elif self.selected > 0:
            self.selected -= 1
        else: 
            self.selected = None
        return self.selected


menu_items = { 'command': MenuItemCommand, 'input': MenuItemInput, 'group': MenuItemGroup, 'row':MenuItemRow }
# Default dimensions for lcds (rows, cols)
LCD_dims = { 'st7920': (4,16), 'hd44780': (4,20), 'uc1701' : (4,16) }

BLINK_ON_TIME   = 0.500
BLINK_OFF_TIME  = 0.200

class MenuManager:
    def __init__(self, config):
        self.first = True
        self.running = False
        self.menuitems = {}
        self.groupstack = []
        self.info_objs = {}
        self.info_dict = {}
        self.current_top = 0
        self.current_selected = 0
        self.next_blinktime = 0
        self.blink_state = True
        self.current_group = None
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.root = config.get('root')
        dims = config.getchoice('lcd_type', LCD_dims)
        self.rows = config.getint('rows', dims[0])
        self.cols = config.getint('cols', dims[1])
        # load items
        self.load_menuitems(config)
    
    def printer_state(self, state):
        if state == 'ready':
            # Load printer objects
            self.info_objs = {}
            for name in ['gcode', 'toolhead', 'fan', 'extruder0', 'extruder1', 'heater_bed', 'virtual_sdcard']:
                obj = self.printer.lookup_object(name, None)
                if obj is not None:
                    self.info_objs[name] = obj

    def is_running(self):
        return self.running

    def begin(self, eventtime):
        self.first = True
        self.running = True
        self.groupstack = []        
        self.current_top = 0
        self.current_selected = 0
        self.update_info(eventtime)
        self.populate_menu()
        self.current_group = self.lookup_menuitem(self.root)

    def populate_menu(self):
        for name, item in self.menuitems.items():
            if isinstance(item, (MenuItemGroup,MenuItemRow)):
                item.populate_items()

    def update_info(self, eventtime):
        self.info_dict = {}        
        # get info
        
        for name, obj in self.info_objs.items():
            try:
                self.info_dict[name] = obj.get_status(eventtime)
            except:
               self.info_dict[name] = {}
            # get additional info
            if name == 'toolhead':
                pos = obj.get_position()
                self.info_dict[name].update({'xpos':pos[0], 'ypos':pos[1], 'zpos':pos[2]})
                self.info_dict[name].update({
                    'is_printing': (self.info_dict[name]['status'] == "Printing"),
                    'is_ready': (self.info_dict[name]['status'] == "Ready"),
                    'is_idle': (self.info_dict[name]['status'] == "Idle")
                })
            elif name == 'extruder0':
                info = obj.get_heater().get_status(eventtime)
                self.info_dict[name].update(info)
            elif name == 'extruder1':
                info =  obj.get_heater().get_status(eventtime)
                self.info_dict[name].update(info)

    def push_groupstack(self, group):
        if not isinstance(group, MenuItemGroup):
            raise error("Wrong menuitem type for group, expected MenuGroup")
        self.groupstack.append(group)

    def pop_groupstack(self):
        if len(self.groupstack) > 0:
            group = self.groupstack.pop()
            if not isinstance(group, MenuItemGroup):
                raise error("Wrong menuitem type for group, expected MenuGroup")
        else:
            group = None
        return group

    def peek_groupstack(self):
        if len(self.groupstack) > 0:
            return self.groupstack[len(self.groupstack)-1]
        return None
    
    # toggle blink
    def update_blink(self, eventtime):
        if eventtime > self.next_blinktime:
            self.blink_state = not self.blink_state
            self.next_blinktime = eventtime + (BLINK_OFF_TIME if self.blink_state else BLINK_ON_TIME)

    def update(self, eventtime):
        lines = []
        if self.running and isinstance(self.current_group, MenuItemGroup):
            if self.first:
                self.run_script(self.current_group.get_enter_gcode())
                self.first = False

            if self.current_top > len(self.current_group.items) - self.rows:
                self.current_top = len(self.current_group.items) - self.rows
            if self.current_top < 0:
                self.current_top = 0

            for row in range(self.current_top, self.current_top + self.rows):
                current = self.current_group.items[row]
                str = ""
                if row < len(self.current_group.items):
                    if row == self.current_selected:
                        if isinstance(current, (MenuItemInput, MenuItemRow)) and current.is_editing():
                            str += '*'
                        else:
                            str += '>'
                    else:
                        str += ' '                                    

                    name = "%s" % current
                    if isinstance(current, MenuItemGroup):                        
                        str += name[:self.cols-2].ljust(self.cols-2) + '>'
                    else:
                        str += name[:self.cols-1].ljust(self.cols-1)

                lines.append(str.ljust(self.cols))
        self.update_blink(eventtime)
        return lines

    def up(self):
        if self.running and isinstance(self.current_group, MenuItemGroup):
            current = self.current_group.items[self.current_selected]
            if isinstance(current, (MenuItemInput, MenuItemRow)) and current.is_editing():
                current.dec_value()
            elif isinstance(current, MenuItemRow) and current.prev_item() is not None:
                pass
            else:
                if self.current_selected == 0:
                    pass
                elif self.current_selected > self.current_top:
                    self.current_selected -= 1
                else:
                    self.current_top -= 1
                    self.current_selected -= 1
                # wind up row last item
                if isinstance(self.current_group.items[self.current_selected], MenuItemRow):
                    self.current_group.items[self.current_selected].prev_item()

    def down(self):
        if self.running and isinstance(self.current_group, MenuItemGroup):
            current = self.current_group.items[self.current_selected]
            if isinstance(current, (MenuItemInput, MenuItemRow)) and current.is_editing():
                current.inc_value()
            elif isinstance(current, MenuItemRow) and current.next_item() is not None:
                pass
            else:
                if self.current_selected + 1 == len(self.current_group.items):
                    pass
                elif self.current_selected < self.current_top + self.rows - 1:
                    self.current_selected += 1
                else:
                    self.current_top += 1
                    self.current_selected += 1
                # wind up row first item
                if isinstance(self.current_group.items[self.current_selected], MenuItemRow):
                    self.current_group.items[self.current_selected].next_item()

    def back(self):
        if self.running and isinstance(self.current_group, MenuItemGroup):
            current = self.current_group.items[self.current_selected]
            if isinstance(current, (MenuItemInput, MenuItemRow)) and current.is_editing():
                return

            parent = self.peek_groupstack()
            if isinstance(parent, MenuItemGroup):
                # find the current in the parent
                itemno = 0
                index = 0
                for item in parent.items:
                    if self.current_group == item:
                        index = itemno
                    else:
                        itemno += 1

                self.run_script(self.current_group.get_leave_gcode())
                self.current_group = self.pop_groupstack()
                if index < len(self.current_group.items):
                    self.current_top = index
                    self.current_selected = index
                else:
                    self.current_top = 0
                    self.current_selected = 0
                
                self.run_script(self.current_group.get_enter_gcode())
            else:
                self.run_script(self.current_group.get_leave_gcode())
                self.running = False

    def select(self):
        if self.running and isinstance(self.current_group, MenuItemGroup):
            current = self.current_group.items[self.current_selected]
            if isinstance(current, MenuItemRow):
                current = current.curr_item()
            if isinstance(current, MenuItemGroup):
                self.run_script(self.current_group.get_leave_gcode())
                self.push_groupstack(self.current_group)
                self.current_group = current
                self.current_top = 0
                self.current_selected = 0
                self.run_script(self.current_group.get_enter_gcode())
            elif isinstance(current, MenuItemInput):
                if current.is_editing():
                    self.run_script(current.get_gcode())
                    current.reset_value()
                else:
                    current.init_value()
            elif isinstance(current, MenuItemCommand):
                self.run_script(current.get_gcode())
            else:
                self.back()

    def run_script(self, script):
        if script is not None:        
            for line in script.split('\n'):
                while 1:
                    try:
                        res = self.gcode.process_batch(line)
                    except self.gcode.error as e:
                        break
                    except:
                        logging.exception("menu dispatch")
                        break                        
                    if res:
                        break
                    self.reactor.pause(self.reactor.monotonic() + 0.100)

    def lookup_value(self, literal):
        value = None
        if literal:
            try:
                value = float(literal)
            except ValueError:
                key1, key2 = literal.split('.')[:2]
                if(type(self.info_dict) == dict and key1 and key2 and
                   key1 in self.info_dict and type(self.info_dict[key1]) == dict):
                    value = self.info_dict[key1].get(key2)
        return value

    def add_menuitem(self, name, menu):
        if name in self.menuitems:
            raise self.printer.config_error(
                "Menu object '%s' already created" % (name,))        
        self.menuitems[name] = menu

    def lookup_menuitem(self, name):
        if name not in self.menuitems:
            raise self.printer.config_error(
                "Unknown menuitem '%s'" % (name,))
        return self.menuitems[name]
    
    def load_menuitems(self, config):
        for cfg in config.get_prefix_sections('menu '):
            name = " ".join(cfg.get_name().split()[1:])
            item = cfg.getchoice('type', menu_items)(self, cfg)
            self.add_menuitem(name, item)
