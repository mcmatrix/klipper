# Basic LCD menu support
#
# Based on the RaspberryPiLcdMenu from Alan Aufderheide, February 2013
# Copyright (C) 2018  Janar Sööt <janar.soot@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, sys, ast

class error(Exception):
    pass

# Menu element baseclass
class MenuElement(object):
    def __init__(self, menu, config):
        self.menu = menu
        self.cursors = config.get('cursors', ">*") # selected, edit
        self.width = self._asint(config.get('width', '0'))
        self.enable_any = self._asbool(config.get('enable_any', 'false'))
        #self.enable = filter(None, list(e.strip() for e in config.get('enable', 'true').split(',')))
        self.enable = self._aslist(config.get('enable', 'true'))
        self.name = self._strip_quotes(config.get('name'))
        self.__last_state = True
        if len(self.cursors) < 2:
            raise error("Unexpected cursors size!")

    # overload
    def _render(self):
        return self.name
    
    # overload
    # 1 second event
    def tick_event(self, eventtime):
        pass

    # overload
    def is_editing(self):
        return False

    # overload
    def is_readonly(self):
        return True

    # overload
    def is_enabled(self):
        logical_fn = (all,any)
        return logical_fn[int(self.enable_any)]([self._lookup_bool(enable) for enable in self.enable])

    def update_eventtime(self, eventtime):
        state = bool(int(eventtime) & 1)
        if self.__last_state ^ state:
            self.__last_state = state
            self.tick_event(eventtime)

    def render(self):
        if self.width > 0:
            return str(self._render())[:self.width].ljust(self.width)
        else:
            return str(self._render())

    def _lookup_bool(self, b):
        if not self._asbool(b):
            if b[0] == '!': # negation:
                return not (not not self.menu.lookup_parameter(b[1:]))
            else:
                return not not self.menu.lookup_parameter(b)
        return True

    def _strip_quotes(self, s):
        if isinstance(s, str):
            s = str(s).strip()
            if s.startswith(('"', "'")):
                s = s[1:]
            if s.endswith(('"', "'")):
                s = s[:-1]
        return s

    def _asbool(self, s, default=False):
        if s is None:
            return default
        if isinstance(s, bool):
            return s
        s = str(s).strip()
        return s.lower() in ('y','yes', 't', 'true', 'on', '1')

    def _asint(self, s, default=0):
        if s is None:
            return default
        if isinstance(s, (int, float)):
            return int(s)
        s = str(s).strip()
        try:
            return int(float(s))
        except:
            return default

    def _asfloat(self, s, default=0.0):
        if s is None:
            return default
        if isinstance(s, (int, float)):
            return float(s)
        s = str(s).strip()
        try:
            return float(s)
        except:
            return default

    def _aslist_splitlines(self, value, default=[]):
        if isinstance(value, str):
            value = filter(None, [x.strip() for x in value.splitlines()])
        try:
            return list(value)
        except:
            return default

    def _aslist_split(self, value, sep=',', default=[]):
        if isinstance(value, str):
            value = filter(None, [x.strip() for x in value.split(sep)])
        try:
            return list(value)
        except:
            return default

    def _aslist(self, value, flatten=True, default=[]):
        values = self._aslist_splitlines(value)
        if not flatten:
            return values
        result = []
        for value in values:
            subvalues = self._aslist_split(value, sep = ',')
            result.extend(subvalues)
        return result

    def __str__(self):
        self.render()


# menu container baseclass
class MenuContainer(MenuElement):
    def __init__(self, menu, config):
        super(MenuContainer, self).__init__(menu, config)
        self._show_back = self._asbool(config.get('show_back', 'true'))
        self._show_title = self._asbool(config.get('show_title', 'true'))
        self._allitems = []
        self._items = []

    # overload
    def names_aslist(self):
        return []    
    
    # overload
    def is_accepted(self, item):
        return isinstance(item, MenuElement)

    def is_readonly(self):
        return False

    def is_editing(self):
        return any([item.is_editing() for item in self._items])

    def lookup_item(self, s):
        if isinstance(s, str):
            s = self.menu.lookup_menuitem(s.strip())        
        return s

    def find_item(self, item):
        return self._items.index(item)

    def append_item(self, s):  
        item = self.lookup_item(s)
        if item is not None:
            if not self.is_accepted(item):
                raise error("Menu item '%s'is not accepted!" % str(type(item)))
            self._allitems.append(item)

    def populate_items(self):
        self._allitems = [] # empty list
        if self._show_back is True:
            name = '[..]'
            if self._show_title:
                name += ' %s' % (self.name)
            self.append_item(MenuCommand(self.menu, {'name':name, 'gcode':'', 'action': 'back'}))
        for name in self.names_aslist():
            self.append_item(name)        
        self.update_items()

    def update_items(self):
        self._items = [item for item in self._allitems if item.is_enabled()]

    def update_eventtime(self, eventtime):
        super(MenuContainer, self).update_eventtime(eventtime)
        for item in self._items:
            item.update_eventtime(eventtime)

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

    def __getitem__(self, key):
        return self._items[key]

class MenuItem(MenuElement):
    def __init__(self, menu, config):
        super(MenuItem, self).__init__(menu, config)
        self.parameter = config.get('parameter', '')
        self.transform = config.get('transform', '')

    def _parse_transform(self, t):
        def mapper(left_min, left_max, right_min, right_max, cast_fn): 
            # interpolate
            left_span = left_max - left_min  
            right_span = right_max - right_min  
            scale_factor = float(right_span) / float(left_span) 
            def map_fn(value):
                return cast_fn(right_min + (value-left_min)*scale_factor)
            return map_fn

        def scaler(scale_factor, cast_fn): 
            def scale_fn(value):
                return cast_fn(value*scale_factor)
            return scale_fn    
        
        def chooser(choices, cast_fn): 
            def choose_fn(value):
                return choices[cast_fn(value)]
            return choose_fn

        def timerizer(key):
            time = {}
            def time_fn(value):
                try:
                    seconds = int(value)
                except:
                    seconds = 0
                time['days'], time['seconds'] = divmod(seconds, 86400)
                time['hours'], time['seconds'] = divmod(time['seconds'], 3600)
                time['minutes'], time['seconds'] = divmod(time['seconds'], 60)

                if key in time:
                    return time[key]
                else:
                    return 0
            return time_fn

        funs = {'int':int, 'float':float, 'bool':bool, 'str':str, 'abs':abs, 'bin':bin, 'hex':hex, 'oct':oct}
        fn = None
        t = str(t).strip()
        try:
            o = ast.literal_eval(t)                
            if isinstance(o, tuple) and len(o) == 4 and isinstance(o[3], (float, int)):
                # mapper (interpolate), cast type by last parameter type
                fn = mapper(o[0], o[1], o[2], o[3], type(o[3]))
            elif isinstance(o, tuple) and len(o) == 2:
                # boolean chooser for 2 size tuple
                fn = chooser(o, bool)
            elif isinstance(o, list) and o:
                # int chooser for list
                fn = chooser(o, int)
            elif isinstance(o, str) and o:
                key = o.strip().lower()
                if key in funs:
                    fn = funs[key]
                elif key in ('days','hours','minutes','seconds'):
                    fn = timerizer(key)
                else:
                    logging.error("Unknown function: '%s'" % str(key))                        
            elif isinstance(o, (float, int)):
                # scaler, cast type depends from scale factor type
                fn = scaler(o, type(o))
            elif isinstance(o, dict) and o.keys() and isinstance(o.keys()[0], (int, float, str)):
                # chooser, cast type by first key type
                fn = chooser(o, type(o.keys()[0]))
            else:
                logging.error("Invalid transform parameter: '%s'" % (t,))
        except Exception as e:
            logging.error('Transform parsing exception: '+ str(e))
        return fn

    def aslist_transform(self):
        return list(filter(None, (self._parse_transform(t) for t in self._aslist(self.transform, flatten=False))))
        
    def prepare_values(self, value = None):
        values = []
        if self.parameter:
            value = self.menu.lookup_parameter(self.parameter) if value is None else value
            if value is not None:
                values += [value]
                try:
                    values += [t(value) for t in self.aslist_transform() if callable(t)]
                except Exception as e:
                    logging.error('Transformation exception: '+ str(e))
            else:
                logging.error("Parameter '%s' not found" % str(self.parameter))
        return tuple(values)

    def _get_formatted(self, literal, val = None):
        values = self.prepare_values(val)
        if isinstance(literal, str) and len(values) > 0:
            try:
                literal = literal.format(*values)
            except Exception as e:
                logging.error('Format exception: '+ str(e))
        return literal

    def _render(self):
        return self._get_formatted(self.name)

class MenuCommand(MenuItem):
    def __init__(self, menu, config):
        super(MenuCommand, self).__init__(menu, config)
        self.gcode = config.get('gcode')
        self.action = config.get('action', None)

    def is_readonly(self):
        return False

    def get_gcode(self):
        return self._get_formatted(self.gcode)

    def get_action(self):
        fn = None
        def back_fn():
            self.menu.back()
        
        def exit_fn():
            self.menu.exit()

        _actions = {
            'back': back_fn, 
            'exit': exit_fn
        }
        try:
            s = str(self.action).strip()
            fn = _actions.get(s)
        except:
            logging.error("Unknown action %s" % (self.action))
        return fn

    def __call__(self):
        if self.action is not None:
            action = self.get_action()
            if callable(action):
                action()

class MenuInput(MenuCommand):
    def __init__(self, menu, config):
        super(MenuInput, self).__init__(menu, config)
        self.reverse = self._asbool(config.get('reverse', 'false'))
        #self.readonly = filter(None, list(e.strip() for e in config.get('readonly', 'false').split(',')))
        self.readonly = self._aslist(config.get('readonly', 'false'))
        self.input_value = None
        self.input_min = config.getfloat('input_min', sys.float_info.min)
        self.input_max = config.getfloat('input_max', sys.float_info.max)
        self.input_step = config.getfloat('input_step', above=0.)

    def is_readonly(self):
        return all([self._lookup_bool(readonly) for readonly in self.readonly])

    def _render(self):
        return self._get_formatted(self.name, self.input_value)

    def get_gcode(self):
        return self._get_formatted(self.gcode, self.input_value)
    
    def is_editing(self):
        return self.input_value is not None

    def init_value(self):
        if not self.is_readonly():
            args = self.prepare_values()
            if len(args) > 0:
                try:
                    self.input_value = float(args[0])
                except:
                    self.input_value = None
        else:
            self.input_value = None
    
    def reset_value(self):
        self.input_value = None

    def inc_value(self):
        if self.input_value is None:
            return
        if(self.reverse is True):
            self.input_value -= abs(self.input_step) 
        else:
            self.input_value += abs(self.input_step) 
        self.input_value = min(self.input_max, max(self.input_min, self.input_value))

    def dec_value(self):
        if self.input_value is None:
            return
        if(self.reverse is True):
            self.input_value += abs(self.input_step) 
        else:
            self.input_value -= abs(self.input_step) 
        self.input_value = min(self.input_max, max(self.input_min, self.input_value))

class MenuGroup(MenuContainer):
    def __init__(self, menu, config, sep = ','):
        super(MenuGroup, self).__init__(menu, config)
        self._sep = sep
        self._show_back = False
        self.selected = None
        self.items = config.get('items')

    def is_enabled(self):        
        return not not len(self)

    def is_readonly(self):
        return all([item.is_readonly() for item in self._items])

    def names_aslist(self):
        return self._aslist_split(self.items, sep=self._sep)

    def _render_item(self, item, i):
        name = "%s" % item
        if i == self.selected and not self.is_editing():
            name = name if self.menu.blink_slow_state else ' '*len(name)
        elif i == self.selected and self.is_editing():
            name = name if self.menu.blink_fast_state else ' '*len(name)
        return name

    def _render(self):
        s = ""
        if not self.is_editing():            
            self.update_items()
        if self.selected is not None:
            self.selected = (self.selected % len(self)) if len(self) > 0 else None

        for i, item in enumerate(self):
            s += self._render_item(item, i)
        return s

    def _call_selected(self, method = None):
        res = None
        try:
            res = (getattr(self[self.selected], method)() if method is not None else self[self.selected])
        except:
            pass
        return res

    def is_editing(self):
        return self._call_selected('is_editing')

    def inc_value(self):
        self._call_selected('inc_value')

    def dec_value(self):
        self._call_selected('dec_value')

    def selected_item(self):
        return self._call_selected()

    def find_next_item(self):
        if self.selected is None:
            self.selected = 0
        elif self.selected < len(self) - 1:
            self.selected += 1
        else: 
            self.selected = None
        # skip readonly
        while self.selected is not None and self.selected < len(self) and self._call_selected('is_readonly'):
            self.selected = (self.selected + 1) if self.selected < len(self) - 1 else None
        return self.selected

    def find_prev_item(self):
        if self.selected is None:
            self.selected = len(self) - 1
        elif self.selected > 0:
            self.selected -= 1
        else: 
            self.selected = None        
        # skip readonly
        while self.selected is not None and self.selected >= 0 and self._call_selected('is_readonly'):
            self.selected = (self.selected - 1) if self.selected > 0 else None
        return self.selected

class MenuItemGroup(MenuGroup):
    def __init__(self, menu, config, sep):
        super(MenuItemGroup, self).__init__(menu, config, sep)

    def is_readonly(self):
        return True

    def is_accepted(self, item):
        return type(item) is MenuItem

class MenuCycler(MenuGroup):
    def __init__(self, menu, config, sep):
        super(MenuCycler, self).__init__(menu, config, sep)
        self._interval = 0
        self.__interval_cnt = 0
        self.__alllen = 0
        self._curr_idx = 0

    def is_readonly(self):
        return True

    def is_accepted(self, item):
        return type(item) in (MenuItem, MenuItemGroup)

    def lookup_item(self, item):        
        if isinstance(item, str) and '|' in item:
            item = MenuItemGroup(self.menu, {'name':'Span', 'items': item}, '|')
            item.populate_items()
        elif isinstance(item, int):
            self._interval = max(0, int(item))
            item = None
        return super(MenuCycler, self).lookup_item(item)

    def tick_event(self, eventtime):
        super(MenuCycler, self).tick_event(eventtime)
        if self._interval > 0:
            self.__interval_cnt = (self.__interval_cnt+1) % self._interval
            if self.__interval_cnt == 0 and self.__alllen > 0:
                self._curr_idx = (self._curr_idx+1) % self.__alllen
        else:
            self._curr_idx = 0

    def update(self):
        items = [item for item in self._allitems if item.is_enabled()]
        self.__alllen = len(items)
        if self.__alllen > 0:
            self._curr_idx = self._curr_idx % self.__alllen
            self._items = [items[self._curr_idx]]
        else:
            self._curr_idx = 0
            self._items = []

class MenuList(MenuContainer):
    def __init__(self, menu, config):
        super(MenuList, self).__init__(menu, config)
        self.enter_gcode = config.get('enter_gcode', None)
        self.leave_gcode = config.get('leave_gcode', None)
        self.items = config.get('items')

    def aslist_names(self):
        return self._aslist_splitlines(self.items)

    def lookup_item(self, item):
        if isinstance(item, str) and ',' in item:
            item = MenuGroup(self.menu, {'name':'Group', 'items': item}, ',')
            item.populate_items()
        return super(MenuList, self).lookup_item(item)

    def get_enter_gcode(self):
        return self.enter_gcode

    def get_leave_gcode(self):
        return self.leave_gcode

class MenuVSDCard(MenuList):
    def __init__(self, menu, config):
        super(MenuVSDCard, self).__init__(menu, config)

    def populate_files(self):
        sdcard = self.menu.objs['virtual_sdcard']
        if sdcard is not None:
            files = sdcard.get_file_list()
            for fname, fsize in files:
                gcode = [
                    'M23 /%s' % (fname)
                ]
                self.append_item(MenuCommand(self.menu, {'name': '%s' % (fname), 'cursors':'+*', 'gcode': "\n".join(gcode)}))

    def populate(self):
        super(MenuVSDCard, self).populate_items()
        self.populate_files()

class MenuCard(MenuGroup):
    def __init__(self, menu, config):
        super(MenuCard, self).__init__(menu, config)
        self.content = config.get('content')

    def aslist_names(self):
        return self._aslist_splitlines(self.items)

    def aslist_content(self):
        return filter(None, [self._strip_quotes(s) for s in self._aslist_splitlines(self.content)])

    def update_items(self):
        self._items = [item for item in self._allitems]       

    def lookup_item(self, item):
        if isinstance(item, str) and ',' in item:
            item = MenuCycler(self.menu, {'name':'Cycler', 'items': item}, ',')
            item.populate_items()
        return super(MenuCard, self).lookup_item(item)

    def render_content(self, eventtime):
        if not self.is_editing():            
            self.update()
            self.sequencer_update(eventtime)
        if self.selected is not None:
            self.selected = (self.selected % len(self)) if len(self) > 0 else None
        
        items = []
        for i, item in enumerate(self):
            name = ''
            if item.is_enabled():
                name = self._render_item(item, i)
            items.append(name)       
        rows = []
        for row in self.aslist_content():            
            try:
                rows.append(str(row).format(*items))
            except Exception as e:
                logging.error('Page rendering exception: '+ str(e))
        return rows

    def _render(self):
        return self.name

class MenuDeck(MenuList):
    def __init__(self, menu, config):
        super(MenuDeck, self).__init__(menu, config)
        self._show_back = False
        self._show_title = False

    def iter_names(self):
        return self._aslist(self.items)

    def accept(self, item):
        return type(item) is MenuCard
    
    def _render(self):
        return self.name
    
menu_items = { 'item': MenuItem, 'command': MenuCommand, 'input': MenuInput, 'list': MenuList, 'vsdcard':MenuVSDCard, 'deck':MenuDeck, 'card': MenuCard }
# Default dimensions for lcds (rows, cols)
LCD_dims = { 'st7920': (4,16), 'hd44780': (4,20), 'uc1701' : (4,16) }

SEQUENCE_TIMER   = 0.200
BLINK_FAST_SEQUENCE = (True, True, False, False)
BLINK_SLOW_SEQUENCE = (True, True, True, False, False, False)

class MenuManager:
    def __init__(self, config):
        self.running = False
        self.menuitems = {}
        self.menustack = []
        self.top_row = 0
        self.selected = 0
        self.blink_fast_state = True
        self.blink_slow_state = True
        self.blink_fast_idx = 0
        self.blink_slow_idx = 0
        self.timeout_idx = 0
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
            'display': None,
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
            reactor.register_timer(self.sequence_event, reactor.NOW)

    def sequence_event(self, eventtime):
        # take next from sequence
        self.blink_fast_idx = (self.blink_fast_idx+1) % len(BLINK_FAST_SEQUENCE)
        self.blink_slow_idx = (self.blink_slow_idx+1) % len(BLINK_SLOW_SEQUENCE)
        self.timeout_idx = (self.timeout_idx+1) % 5  # 0.2*5 = 1s
        self.blink_fast_state = not not BLINK_FAST_SEQUENCE[self.blink_fast_idx]
        self.blink_slow_state = not not BLINK_SLOW_SEQUENCE[self.blink_slow_idx]
        if self.timeout_idx == 0:
            self.timeout_check(eventtime)            

        return eventtime + SEQUENCE_TIMER

    def timeout_check(self, eventtime):
        # check timeout
        if self.is_running() and self.timeout > 0:
            if self.timer >= self.timeout:
                self.exit()
            self.timer += 1
        else:
            self.timer = 0

    def is_running(self):
        return self.running

    def begin(self, eventtime):
        self.menustack = []        
        self.top_row = 0
        self.selected = 0
        root = self.lookup_menuitem(self.root)
        if isinstance(root, MenuContainer):
            self.update_parameters(eventtime)
            self.populate()
            self.stack_push(root)
            self.running = True            
        else:
            logging.error("Invalid root '%s', menu stopped!" % str(self.root))
            self.running = False

    def populate(self):
        for name, item in self.menuitems.items():
            if isinstance(item, (MenuContainer)):
                item.populate()

    def update_parameters(self, eventtime):
        self.parameters = {
            'screen': {
                'eventtime': eventtime,
                'is2004': (self.rows == 4 and self.cols == 20),
                'is2002': (self.rows == 2 and self.cols == 20),
                'is1604': (self.rows == 4 and self.cols == 16),
                'is1602': (self.rows == 2 and self.cols == 16)
            }
        }
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
                    self.parameters[name].update({'xpos':pos[0], 'ypos':pos[1], 'zpos':pos[2], 'epos': pos[3]})
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
                elif name == 'display':
                    self.parameters[name].update({
                        'progress': 0 if self.objs[name].progress is None else self.objs[name].progress,
                        'progress.visible': not not self.objs[name].progress,
                        'message': '' if self.objs[name].message is None else str(self.objs[name].message),
                        'message.visible': not not self.objs[name].message,
                        'is_enabled': True
                    })                    
            elif type(self.objs[name]) == dict:
                self.parameters[name] = {}
                if name == 'output_pin' or name == 'servo':                    
                    for key, obj in self.objs[name].items():
                        try:
                            self.parameters[name].update({'%s.value'%(key): obj.last_value, '%s.is_enabled'%(key): True})
                        except Exception as e:
                            logging.error('Parameter update error: '+ str(e))
                else:
                    self.parameters[name].update({'is_enabled': False})
            else:
                self.parameters[name] = {'is_enabled': False}

    def stack_push(self, container):
        if not isinstance(container, MenuContainer):
            raise error("Wrong type, expected MenuContainer")
        top = self.stack_peek()
        if top is not None:
            self.run_script(top.get_leave_gcode())
        self.run_script(container.get_enter_gcode())        
        self.menustack.append(container)

    def stack_pop(self):
        container = None
        if self.stack_size() > 0:
            container = self.menustack.pop()
            if not isinstance(container, MenuContainer):
                raise error("Wrong type, expected MenuContainer")
            self.run_script(container.get_leave_gcode())
            top = self.stack_peek()
            if top is not None:
                self.run_script(top.get_enter_gcode())
        return container
    
    def stack_size(self):
        return len(self.menustack)

    def stack_peek(self, lvl=0):
        container = None
        if self.stack_size() > lvl:
            container = self.menustack[self.stack_size()-lvl-1]
        return container
    
    def update(self, eventtime):        
        lines = []
        self.update_parameters(eventtime)
        container = self.stack_peek()        
        if self.running and isinstance(container, MenuContainer):
            if not container.is_editing():
                container.update()
            # clamps
            self.top_row = max(0, min(self.top_row, len(container) - self.rows))
            self.selected = max(0, min(self.selected, len(container)-1))
            if isinstance(container, MenuDeck):
                lines = container[self.selected].render_rows(eventtime)
            else:
                for row in range(self.top_row, self.top_row + self.rows):
                    s = ""
                    if row < len(container):
                        current = container[row]
                        name = "%s" % current
                        if row == self.selected:
                            if isinstance(current, (MenuInput, MenuGroup)) and current.is_editing():
                                s += current.cursors[1]
                            elif isinstance(current, MenuElement):
                                s += current.cursors[0]
                            else:
                                s += '>'
                        else:
                            s += ' '

                        if isinstance(current, MenuList):                        
                            s += name[:self.cols-len(s)-1].ljust(self.cols-len(s)-1) + '>'
                        else:
                            s += name[:self.cols-len(s)].ljust(self.cols-len(s))
                    lines.append(s.ljust(self.cols))            
        return lines

    def up(self):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            current = container[self.selected]
            if isinstance(current, (MenuInput, MenuGroup)) and current.is_editing():
                current.dec_value()
            elif isinstance(current, MenuGroup) and current.find_prev_item() is not None:
                pass
            else:
                if self.selected == 0:
                    return
                if self.selected > self.top_row:
                    self.selected -= 1
                else:
                    self.top_row -= 1
                    self.selected -= 1
                # wind up group last item
                if isinstance(container[self.selected], MenuGroup):
                    container[self.selected].find_prev_item()

    def down(self):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            current = container[self.selected]
            if isinstance(current, (MenuInput, MenuGroup)) and current.is_editing():
                current.inc_value()
            elif isinstance(current, MenuGroup) and current.find_next_item() is not None:
                pass
            else:
                if self.selected >= len(container) - 1:
                    return
                if self.selected < self.top_row + self.rows - 1:
                    self.selected += 1
                else:
                    self.top_row += 1
                    self.selected += 1 
                # wind up group first item
                if isinstance(container[self.selected], MenuGroup):
                    container[self.selected].find_next_item()

    def back(self):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            current = container[self.selected]
            if isinstance(current, (MenuInput, MenuGroup)) and current.is_editing():
                return
            parent = self.stack_peek(1)
            if isinstance(parent, MenuContainer):
                self.stack_pop()
                index = parent.find(container)
                if index is not None and index < len(parent):
                    self.top_row = index
                    self.selected = index
                else:
                    self.top_row = 0
                    self.selected = 0
            else:
                self.stack_pop()
                self.running = False

    def select(self):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            current = container[self.selected]
            if isinstance(current, MenuGroup):
                current = current.selected_item()
            if isinstance(current, MenuList):
                self.stack_push(current)
                self.top_row = 0
                self.selected = 0
            elif isinstance(current, MenuInput):
                if current.is_editing():
                    self.run_script(current.get_gcode())
                    current.reset_value()
                else:
                    current.init_value()
            elif isinstance(current, MenuCommand):
                current()
                self.run_script(current.get_gcode())

    def exit(self):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.run_script(container.get_leave_gcode())
            self.running = False

    def run_script(self, script):
        if script is not None:
            try:
                self.gcode.run_script(script)
            except:
                pass

    def lookup_parameter(self, literal):
        value = None
        try:
            value = float(literal)
        except:
            pass        
        if value is None:
            try:
                key1, key2 = literal.split('.', 1)
                value = self.parameters[key1].get(key2)
            except:
                pass
        return value

    def add_menuitem(self, name, menu):
        if name in self.menuitems:
            raise self.printer.config_error(
                "Menu object '%s' already created" % (name,))        
        self.menuitems[name] = menu

    def lookup_menuitem(self, name):
        if name is None:
            return None
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

