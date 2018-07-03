# Basic LCD menu support
#
# Based on the RaspberryPiLcdMenu from Alan Aufderheide, February 2013
# Copyright (C) 2018  Janar Sööt <janar.soot@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, sys, ast

class error(Exception):
    pass

class MenuItemBase(object):
    def __init__(self, menu, config):
        self.menu = menu
        self.name = ''
        self.enable = config.get('enable', repr(True))

    def _remove_quotes(self, name):
        if name.startswith(('"', "'")):
            name = name[1:]
        if name.endswith(('"', "'")):
            name = name[:-1]
        return name

    def _get_name(self):
        return self.name

    def is_enabled(self):
        enabled = False
        if type(self.enable) == str and len(self.enable) > 0:
            try:
                enabled = not not ast.literal_eval(self.enable)
            except:
                if self.enable[0] == '!': # negation
                    enabled = not (not not self.menu.lookup_parameter(self.enable[1:]))
                else:
                    enabled = not not self.menu.lookup_parameter(self.enable)                    
        return enabled

    def __str__(self):
        return str(self._get_name())

class MenuItemCommand(MenuItemBase):
    def __init__(self, menu, config):
        super(MenuItemCommand, self).__init__(menu, config)
        self.name = self._remove_quotes(config.get('name'))
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
        return (p, o, c)

    def get_format_args(self, value = None):
        option = None
        if self.parameter:            
            if value is None:
                value = self.menu.lookup_parameter(self.parameter)
            if self.options is not None and value is not None:
                try:                    
                    if callable(self.typecast):
                        if type(self.options) in (float, int):
                            option = self.typecast(self.options * value)
                        else:
                            option = self.options[self.typecast(value)]
                    else:
                        if type(self.options) in (float, int):
                            option = self.options * value
                        else:
                            option = self.options[value]
                except Exception as e:
                    logging.error('Parameter mapping exception: '+ str(e))
            elif value is None:
                logging.error("Parameter '%s' not found" % str(self.parameter))
        return (value, option)

    def _get_formatted(self, literal, value = None):
        args = self.get_format_args(value)
        if type(literal) == str and len(args) > 0:
            try:
                literal = literal.format(*args)
            except Exception as e:
                logging.error('Format exception: '+ str(e))
        return literal

    def _get_name(self):
        return self._get_formatted(self.name)

    def get_gcode(self):
        return self._get_formatted(self.gcode)

class MenuItemInput(MenuItemCommand):
    def __init__(self, menu, config):
        super(MenuItemInput, self).__init__(menu, config)
        self.reverse = not not config.getboolean('reverse', False)
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
        if(self.reverse is True):
            self.input_value -= abs(self.input_step) 
        else:
            self.input_value += abs(self.input_step) 
        self.input_value = min(self.input_max, max(self.input_min, self.input_value))

    def dec_value(self):
        if(self.reverse is True):
            self.input_value += abs(self.input_step) 
        else:
            self.input_value -= abs(self.input_step) 
        self.input_value = min(self.input_max, max(self.input_min, self.input_value))

class MenuItemGroup(MenuItemBase):
    def __init__(self, menu, config):
        super(MenuItemGroup, self).__init__(menu, config)
        self.name = self._remove_quotes(config.get('name'))
        self.items = []
        self._items = config.get('items', None)
        self.enter_gcode = config.get('enter_gcode', None)
        self.leave_gcode = config.get('leave_gcode', None)

    def populate_items(self):
        self.items = [] # empty list        
        self.items.append('[..] %s' % (self.name)) # always add back as first item
        if self._items:
            for name in self._items.split(','):
                item = self.menu.lookup_menuitem(name.strip())
                if item.is_enabled():
                    self.items.append(item)

    def get_enter_gcode(self):
        return self.enter_gcode

    def get_leave_gcode(self):
        return self.leave_gcode

class MenuItemGroupSDCard(MenuItemGroup):
    def __init__(self, menu, config):
        super(MenuItemGroupSDCard, self).__init__(menu, config)        

    def populate_items(self):
        super(MenuItemGroupSDCard, self).populate_items()
        sdcard = self.menu.objs['virtual_sdcard']
        if sdcard is not None:
            files = sdcard.get_file_list()
            for fname, fsize in files:
                gcode = [
                    'M23 /%s' % fname
                ]
                item = MenuItemCommand(self.menu, {'name': '%s' % (fname), 'gcode': "\n".join(gcode)})
                self.items.append(item)

class MenuItemRow(MenuItemBase):
    def __init__(self, menu, config):
        super(MenuItemRow, self).__init__(menu, config)
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


menu_items = { 'command': MenuItemCommand, 'input': MenuItemInput, 'group': MenuItemGroup, 'row':MenuItemRow, 'vsdcard':MenuItemGroupSDCard }
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
        self.current_top = 0
        self.current_selected = 0
        self.blink_state = True
        self.current_group = None
        self.config = config
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.parameters = {}
        self.objs = {
            'gcode': None, 
            'toolhead': None, 
            'fan': None, 
            'extruder0': None, 
            'extruder1': None, 
            'heater_bed': None, 
            'virtual_sdcard': None,
            'output_pin': {},
            'servo': {}
        }
        # try to load printer objects in this state
        for name in self.objs.keys():
            if self.objs[name] is None:
                self.objs[name] = self.printer.lookup_object(name, None)
        self.root = config.get('menu_root', None)
        dims = config.getchoice('lcd_type', LCD_dims)
        self.rows = config.getint('rows', dims[0])
        self.cols = config.getint('cols', dims[1])
        self.timeout = config.getint('menu_timeout', 0)
        self.timer = 0
        # Add MENU commands
        self.gcode.register_mux_command("MENU", "DO", 'dump', self.cmd_MENUDO_DUMP, desc=self.cmd_MENUDO_help)
        self.gcode.register_mux_command("MENU", "DO", 'exit', self.cmd_MENUDO_EXIT, desc=self.cmd_MENUDO_help)
        self.gcode.register_mux_command("MENU", "DO", 'up', self.cmd_MENUDO_UP, desc=self.cmd_MENUDO_help)
        self.gcode.register_mux_command("MENU", "DO", 'down', self.cmd_MENUDO_DOWN, desc=self.cmd_MENUDO_help)
        self.gcode.register_mux_command("MENU", "DO", 'select', self.cmd_MENUDO_SELECT, desc=self.cmd_MENUDO_help)
        self.gcode.register_mux_command("MENU", "DO", 'back', self.cmd_MENUDO_BACK, desc=self.cmd_MENUDO_help)
        # load items
        self.load_menuitems(config)
    
    def printer_state(self, state):
        if state == 'ready':
            # Load printer objects available in ready state
            for name in self.objs.keys():
                if self.objs[name] is None:
                    self.objs[name] = self.printer.lookup_object(name, None)
            # load servo name & output_pin names
            self.lookup_section_names(self.config, 'output_pin')
            self.lookup_section_names(self.config, 'servo')
            # start timer
            reactor = self.printer.get_reactor()
            reactor.register_timer(self.timeout_event, reactor.NOW)
            reactor.register_timer(self.blink_event, reactor.NOW)

    def timeout_event(self, eventtime):
        # check timeout
        if self.is_running() and self.timeout > 0:
            if self.timer >= self.timeout:
                self.exit()
            self.timer += 1
        else:
            self.timer = 0

        return eventtime + 1.
    
    def is_running(self):
        return self.running

    def begin(self, eventtime):
        self.first = True
        self.groupstack = []        
        self.current_top = 0
        self.current_selected = 0
        if self.root is not None:
            self.running = True
            self.update_parameters(eventtime)
            self.populate_menu()
            self.current_group = self.lookup_menuitem(self.root)
        else:
            self.running = False

    def populate_menu(self):
        for name, item in self.menuitems.items():
            if isinstance(item, (MenuItemGroup,MenuItemRow)):
                item.populate_items()

    def update_parameters(self, eventtime):
        self.parameters = {}        
        for name in self.objs.keys():            
            if self.objs[name] is not None and type(self.objs[name]) != dict:
                try:
                    self.parameters[name] = self.objs[name].get_status(eventtime)
                except:
                    self.parameters[name] = {}                
                self.parameters[name].update({'is_enabled': True})
                # get additional info
                if name == 'toolhead':
                    pos = self.objs[name].get_position()
                    self.parameters[name].update({'xpos':pos[0], 'ypos':pos[1], 'zpos':pos[2]})
                    self.parameters[name].update({
                        'is_printing': (self.parameters[name]['status'] == "Printing"),
                        'is_ready': (self.parameters[name]['status'] == "Ready"),
                        'is_idle': (self.parameters[name]['status'] == "Idle")
                    })
                elif name == 'extruder0':
                    info = self.objs[name].get_heater().get_status(eventtime)
                    self.parameters[name].update(info)
                elif name == 'extruder1':
                    info = self.objs[name].get_heater().get_status(eventtime)
                    self.parameters[name].update(info)
            elif type(self.objs[name]) == dict:
                if name == 'output_pin' or name == 'servo':
                    self.parameters[name] = {}
                    for key, obj in self.objs[name].items():
                        try:
                            self.parameters[name].update({key: obj.last_value})
                        except:
                            self.parameters[name].update({'is_enabled': False})
            else:
                self.parameters[name] = {'is_enabled': False}

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
    
    def blink_event(self, eventtime):
        self.blink_state = not self.blink_state
        return eventtime + (BLINK_OFF_TIME if self.blink_state else BLINK_ON_TIME)

    def update(self, eventtime):        
        lines = []
        self.update_parameters(eventtime)
        if self.running and isinstance(self.current_group, MenuItemGroup):
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
                    current = self.current_group.items[row]
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
        return lines

    def up(self):
        if self.running and isinstance(self.current_group, MenuItemGroup):
            self.timer = 0
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
            self.timer = 0
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
            self.timer = 0
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
            self.timer = 0
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

    def exit(self):
        if self.running and isinstance(self.current_group, MenuItemGroup):
            self.run_script(self.current_group.get_leave_gcode())
            self.running = False

    def run_script(self, script):
        if script is not None:
            try:
                self.gcode.run_script(script)
            except:
                pass

    def lookup_parameter(self, literal):
        value = None
        if literal:
            try:
                value = float(literal)
            except ValueError:
                key1, key2 = literal.split('.')[:2]
                if(type(self.parameters) == dict and key1 and key2 and
                   key1 in self.parameters and type(self.parameters[key1]) == dict):
                    value = self.parameters[key1].get(key2)
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

    def lookup_section_names(self, config, section):
        for cfg in config.get_prefix_sections('%s ' % section):
            name = " ".join(cfg.get_name().split()[1:])
            self.objs[section][name] = self.printer.lookup_object(cfg.get_name(), None)

    def load_menuitems(self, config):
        for cfg in config.get_prefix_sections('menu '):
            name = " ".join(cfg.get_name().split()[1:])
            item = cfg.getchoice('type', menu_items)(self, cfg)
            self.add_menuitem(name, item)
    
    cmd_MENUDO_help = "Menu do things (dump, exit, up, down, select, back)"
    def cmd_MENUDO_DUMP(self, params):        
        for key1 in self.parameters:
            if type(self.parameters[key1]) == dict:
                for key2 in self.parameters[key1]:
                    msg = "{0}.{1} = {2}".format(key1, key2, self.parameters[key1].get(key2))
                    logging.info(msg)
                    self.gcode.respond_info(msg)
            else:
                msg = "{0} = {1}".format(key1, self.parameters.get(key1))
                logging.info(msg)
                self.gcode.respond_info(msg)

    def cmd_MENUDO_EXIT(self, params):        
        self.exit()

    def cmd_MENUDO_UP(self, params):        
        self.up()

    def cmd_MENUDO_DOWN(self, params):        
        self.down()

    def cmd_MENUDO_SELECT(self, params):        
        self.select()

    def cmd_MENUDO_BACK(self, params):
        self.back()

