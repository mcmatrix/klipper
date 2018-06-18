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
    
    def get_name(self):
        return self.name

class MenuCommand(MenuItemClass):
    def __init__(self, config):
        MenuItemClass.__init__(self, config)
        self.gcode = config.get('gcode', None)
        self.parameter = config.get('parameter', None)
        self.parameter_choice = config.get('parameter_choice', None)
        
    def get_format_args(self, value = None):
        args = []
        if self.parameter:            
            if value is None:
                value = self.manager.parse_parameter(self.parameter)
            args.append(value)
            if self.parameter_choice is not None:
                list = []
                try:
                    list = ast.literal_eval(self.parameter_choice)
                except:
                    pass
                if value in list:
                    args.append(list[value])

        return args

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
        self.input_step = config.getfloat('input_step', 0.)
    
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
        self.items = config.get('items', '')
        self.enter_gcode = config.get('enter_gcode', None)
        self.leave_gcode = config.get('leave_gcode', None)

    def get_items(self):
        list = [ MenuItemBack('..') ] # always add back as first item
        for name in self.items.split(','):
            list.append(self.manager.lookup_menuitem(name.strip()))
        return list

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
        self.info = {}
        self.current_top = 0
        self.current_selected = 0
        self.current_group = None
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.root = config.get('root')
        self.rows = config.getint('rows', 4)
        self.cols = config.getint('cols', 20)

        self.gcode.register_command('MENU_PRINT', self.cmd_MENU_PRINT, desc=self.cmd_MENU_PRINT_help)        
        self.gcode.register_command('MENU_UP', self.cmd_MENU_UP, desc=self.cmd_MENU_UP_help)        
        self.gcode.register_command('MENU_DOWN', self.cmd_MENU_DOWN, desc=self.cmd_MENU_DOWN_help)        
        self.gcode.register_command('MENU_SELECT', self.cmd_MENU_SELECT, desc=self.cmd_MENU_SELECT_help)        
        self.gcode.register_command('MENU_BEGIN', self.cmd_MENU_BEGIN, desc=self.cmd_MENU_BEGIN_help)        

    def is_running(self):
        return self.running

    def begin(self):
        self.first = True
        self.running = True
        self.groupstack = []        
        self.current_top = 0
        self.current_selected = 0
        self.push_groupstack(self.lookup_menuitem(self.root))

    def update_info(self, eventtime):
        self.info = {}     
        # Load printer objects
        for m in ['gcode', 'toolhead', 'fan', 'extruder0', 'extruder1', 'heater_bed']:
            obj = self.printer.lookup_object(m)
            if obj is not None:
                self.info[m] = obj.get_status(eventtime)
                if m == 'toolhead':
                    pos = obj.toolhead.get_position()
                    self.info[m].update({'xpos':pos[0], 'ypos':pos[1], 'zpos':pos[2]})

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

            items = self.current_group.get_items()

            if self.current_top > len(items) - self.rows:
                self.current_top = len(items) - self.rows
            if self.current_top < 0:
                self.current_top = 0

            for row in range(self.current_top, self.current_top + self.rows):
                str = ""
                if row < len(items):
                    if row == self.current_selected:
                        if isinstance(items[row], MenuInput) and items[row].is_editing():
                            str += '*'
                        else:
                            str += '>'
                    else:
                        str += ' '
                    
                    str += items[row].get_name()[:self.cols-2].ljust(self.cols-2)
                                
                    if isinstance(items[row], MenuGroup):
                        str += '>'
                    else:
                        str += ' '

                lines.append(str.ljust(self.cols))
        return lines

    def up(self):
        if self.running and isinstance(self.current_group, MenuGroup):
            item = self.current_group.get_items()[self.current_selected]
            if isinstance(item, MenuInput) and item.is_editing():
                item.inc_value()
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
            items = self.current_group.get_items()
            if isinstance(items[self.current_selected], MenuInput) and items[self.current_selected].is_editing():
                items[self.current_selected].dec_value()
            else:
                if self.current_selected + 1 == len(items):
                    return
                elif self.current_selected < self.current_top + self.rows - 1:
                    self.current_selected += 1
                else:
                    self.current_top += 1
                    self.current_selected += 1

    def back(self):
        if self.running and isinstance(self.current_group, MenuGroup):
            items = self.current_group.get_items()
            if isinstance(items[self.current_selected], MenuInput) and items[self.current_selected].is_editing():
                return

            parent = self.peek_groupstack()
            if isinstance(parent, MenuGroup):
                # find the current in the parent
                itemno = 0
                index = 0
                items = parent.get_items()
                for item in items:
                    if self.current_group == item:
                        index = itemno
                    else:
                        itemno += 1

                self.run_script(self.current_group.get_leave_gcode())
                self.pop_groupstack()
                if index < len(items):
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
            items = self.current_group.get_items()
            if isinstance(items[self.current_selected], MenuGroup):
                self.run_script(self.current_group.get_leave_gcode())
                self.push_groupstack(items[self.current_selected])
                self.current_top = 0
                self.current_selected = 0
                self.run_script(self.current_group.get_enter_gcode())

            elif isinstance(items[self.current_selected], MenuInput):
                if items[self.current_selected].is_editing():
                    self.run_script(items[self.current_selected].get_gcode())
                    items[self.current_selected].reset_value()
                else:
                    items[self.current_selected].init_value()

            elif isinstance(items[self.current_selected], MenuCommand):
                self.run_script(items[self.current_selected].get_gcode())

            elif isinstance(items[self.current_selected], MenuItemBack):
                self.back()

    def run_script(self, script):
        if script is not None:        
            try:
                self.gcode.run_script(script)
            except:
                pass

    def parse_parameter(self, parameter):
        value = None
        if parameter:
            try:
                value = float(parameter)
            except ValueError:
                key1, key2 = parameter.split('.')[:2]
                if key1 and key2 and self.info and key1 in self.info:
                    value = self.info[key1].get(key2)
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

    cmd_MENU_PRINT_help = "menu print screen"
    def cmd_MENU_PRINT(self, params):
        for line in self.update():
            self.gcode.respond_info(line)

    cmd_MENU_BEGIN_help = "menu begin"
    def cmd_MENU_BEGIN(self, params):
        self.begin()

    cmd_MENU_UP_help = "menu up"
    def cmd_MENU_UP(self, params):
        self.up()

    cmd_MENU_DOWN_help = "menu_down"
    def cmd_MENU_DOWN(self, params):
        self.down()

    cmd_MENU_SELECT_help = "menu select"
    def cmd_MENU_SELECT(self, params):
        self.select()

def load_config_prefix(config):
    name = " ".join(config.get_name().split()[1:])
    item = config.getchoice('type', menu_items)(config)
    menu = config.get_printer().lookup_object("menu")
    menu.add_menuitem(name, item)

def load_config(config):
    return Menu(config)