# Basic LCD menu support
#
# Based on the RaspberryPiLcdMenu from Alan Aufderheide, February 2013
# Copyright (C) 2018  Janar Sööt <janar.soot@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, sys, ast

class error(Exception):
    pass

class MenuItemBack:
    def __init__(self, name):
        self.name = name
    
    def get_name(self):
        return self.name

class MenuItemClass:
    def __init__(self, config):
        self.manager = config.get_printer().lookup_object("menu")
        self.name = config.get('name')
        self.enable = config.get('enable', repr(True))
    
    def get_name(self):
        return self.name

    def is_enabled(self):
        enabled = False
        try:
            enabled = not not ast.literal_eval(self.enable)
        except:
            value = self.manager.get_value(self.enable)
            enabled = not not value
        return enabled
         

class MenuCommand(MenuItemClass):
    def __init__(self, config):
        MenuItemClass.__init__(self, config)
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
                value = self.manager.get_value(self.parameter)
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

    def get_name(self):
        return self._get_formatted(self.name)

    def get_gcode(self):
        return self._get_formatted(self.gcode)

class MenuInput(MenuCommand):
    def __init__(self, config):
        MenuCommand.__init__(self, config)
        self.input_value = None
        self.input_min = config.getfloat('input_min', sys.float_info.min)
        self.input_max = config.getfloat('input_max', sys.float_info.max)
        self.input_step = config.getfloat('input_step', above=0.)
    
    def get_name(self):        
        return self._get_formatted(self.name, self.input_value)

    def get_gcode(self):
        return self._get_formatted(self.gcode, self.input_value)
    
    def is_editing(self):
        return self.input_value is not None

    def init_value(self):
        args = self.get_format_args()
        if len(args) > 0:
            try:
                logging.info("args0 type: %s", type(args[0]))
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

class MenuGroup(MenuItemClass):
    def __init__(self, config):
        MenuItemClass.__init__(self, config)
        self.items = []
        self._items = config.get('items', '')
        self.enter_gcode = config.get('enter_gcode', None)
        self.leave_gcode = config.get('leave_gcode', None)

    def populate_items(self):
        self.items = [] # empty list
        self.items.append(MenuItemBack('..')) # always add back as first item
        for name in self._items.split(','):
            item = self.manager.lookup_menuitem(name.strip())
            if item.is_enabled():
                self.items.append(item)

    def get_enter_gcode(self):
        return self.enter_gcode

    def get_leave_gcode(self):
        return self.leave_gcode

menu_items = { 'command': MenuCommand, 'input': MenuInput, 'group': MenuGroup }

class Menu:
    def __init__(self, config):
        self.first = True
        self.running = False
        self.menuitems = {}
        self.groupstack = []
        self.info_objs = {}
        self.info_dict = {}
        self.current_top = 0
        self.current_selected = 0
        self.current_group = None
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.root = config.get('root')
        self.rows = config.getint('rows', 4)
        self.cols = config.getint('cols', 20)
    
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
        self.push_groupstack(self.lookup_menuitem(self.root))
        self.update_info(eventtime)
        self.populate_menu()

    def populate_menu(self):
        for name, item in self.menuitems.items():
            if isinstance(item, MenuGroup):
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
            elif name == 'extruder0':
                info = obj.get_heater().get_status(eventtime)
                self.info_dict[name].update(info)
            elif name == 'extruder1':
                info =  obj.get_heater().get_status(eventtime)
                self.info_dict[name].update(info)
            elif name == 'heater_bed':
                info =  obj.get_heater().get_status(eventtime)
                self.info_dict[name].update(info)                

    def push_groupstack(self, group):
        if not isinstance(group, MenuGroup):
            raise error("Wrong menuitem type for group, expected MenuGroup")
        self.groupstack.append(group)            
        self.current_group = group

    def pop_groupstack(self):
        if len(self.groupstack) > 0:
            group = self.groupstack.pop()
            if not isinstance(group, MenuGroup):
                raise error("Wrong menuitem type for group, expected MenuGroup")
            self.current_group = group
        else:
            group = None
        return group

    def peek_groupstack(self):
        if len(self.groupstack) > 0:
            return self.groupstack[len(self.groupstack)-1]
        return None

    def update(self):
        lines = []
        if self.running and isinstance(self.current_group, MenuGroup):
            if self.first:
                self.run_script(self.current_group.get_enter_gcode())
                self.first = False

            if self.current_top > len(self.current_group.items) - self.rows:
                self.current_top = len(self.current_group.items) - self.rows
            if self.current_top < 0:
                self.current_top = 0

            for row in range(self.current_top, self.current_top + self.rows):
                str = ""
                if row < len(self.current_group.items):
                    if row == self.current_selected:
                        if isinstance(self.current_group.items[row], MenuInput) and self.current_group.items[row].is_editing():
                            str += '*'
                        else:
                            str += '>'
                    else:
                        str += ' '
                    
                    str += self.current_group.items[row].get_name()[:self.cols-2].ljust(self.cols-2)
                                
                    if isinstance(self.current_group.items[row], MenuGroup):
                        str += '>'
                    else:
                        str += ' '

                lines.append(str.ljust(self.cols))
        return lines

    def up(self):
        if self.running and isinstance(self.current_group, MenuGroup):            
            if isinstance(self.current_group.items[self.current_selected], MenuInput) and self.current_group.items[self.current_selected].is_editing():
                self.current_group.items[self.current_selected].inc_value()
            else:
                if self.current_selected == 0:
                    return
                elif self.current_selected > self.current_top:
                    self.current_selected -= 1
                else:
                    self.current_top -= 1
                    self.current_selected -= 1

    def down(self):
        if self.running and isinstance(self.current_group, MenuGroup):            
            if isinstance(self.current_group.items[self.current_selected], MenuInput) and self.current_group.items[self.current_selected].is_editing():
                self.current_group.items[self.current_selected].dec_value()
            else:
                if self.current_selected + 1 == len(self.current_group.items):
                    return
                elif self.current_selected < self.current_top + self.rows - 1:
                    self.current_selected += 1
                else:
                    self.current_top += 1
                    self.current_selected += 1

    def back(self):
        if self.running and isinstance(self.current_group, MenuGroup):
            if isinstance(self.current_group.items[self.current_selected], MenuInput) and self.current_group.items[self.current_selected].is_editing():
                return

            parent = self.peek_groupstack()
            if isinstance(parent, MenuGroup):
                # find the current in the parent
                itemno = 0
                index = 0
                for item in parent.items:
                    if self.current_group == item:
                        index = itemno
                    else:
                        itemno += 1

                self.run_script(self.current_group.get_leave_gcode())
                self.pop_groupstack()
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
        if self.running and isinstance(self.current_group, MenuGroup):
            if isinstance(self.current_group.items[self.current_selected], MenuGroup):
                self.run_script(self.current_group.get_leave_gcode())
                self.push_groupstack(self.current_group.items[self.current_selected])
                self.current_top = 0
                self.current_selected = 0
                self.run_script(self.current_group.get_enter_gcode())

            elif isinstance(self.current_group.items[self.current_selected], MenuInput):
                if self.current_group.items[self.current_selected].is_editing():
                    self.run_script(self.current_group.items[self.current_selected].get_gcode())
                    self.current_group.items[self.current_selected].reset_value()
                else:
                    self.current_group.items[self.current_selected].init_value()

            elif isinstance(self.current_group.items[self.current_selected], MenuCommand):
                self.run_script(self.current_group.items[self.current_selected].get_gcode())

            elif isinstance(self.current_group.items[self.current_selected], MenuItemBack):
                self.back()

    def run_script(self, script):
        if script is not None:        
            try:
                self.gcode.run_script(script)
            except:
                pass

    def get_value(self, literal):
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

def load_config_prefix(config):
    name = " ".join(config.get_name().split()[1:])
    item = config.getchoice('type', menu_items)(config)
    menu = config.get_printer().lookup_object("menu")
    menu.add_menuitem(name, item)

def load_config(config):
    return Menu(config)
