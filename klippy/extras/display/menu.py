# -*- coding: utf-8 -*-
# Basic LCD menu support
#
# Based on the RaspberryPiLcdMenu from Alan Aufderheide, February 2013
# Copyright (C) 2018  Janar Sööt <janar.soot@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
import sys
import ast
import re


class error(Exception):
    pass


# static class for cursor
class MenuCursor:
    NONE = ' '
    SELECT = '>'
    EDIT = '*'


# Menu element baseclass
class MenuElement(object):
    def __init__(self, menu, config):
        self.cursor = config.get('cursor', MenuCursor.SELECT)
        self._menu = menu
        self._width = self._asint(config.get('width', '0'))
        self._scroll = self._asbool(config.get('scroll', 'false'))
        self._enable = self._aslist(config.get('enable', 'true'),
                                    flatten=False)
        self._name = self._asliteral(config.get('name'))
        self.__scroll_offs = 0
        self.__scroll_diff = 0
        self.__scroll_dir = None
        self.__last_state = True
        if len(self.cursor) < 1:
            raise error("Cursor with unexpected length, expecting 1.")

    # override
    def _render(self):
        return self._name

    # override
    def _second_tick(self, eventtime):
        pass

    # override
    def is_editing(self):
        return False

    # override
    def is_readonly(self):
        return True

    # override
    def is_scrollable(self):
        return True

    # override
    def is_enabled(self):
        return self._parse_bool(self._enable)

    def init(self):
        self.__clear_scroll()

    def heartbeat(self, eventtime):
        state = bool(int(eventtime) & 1)
        if self.__last_state ^ state:
            self.__last_state = state
            if not self.is_editing():
                self._second_tick(eventtime)
                self.__update_scroll(eventtime)

    def __clear_scroll(self):
        self.__scroll_dir = None
        self.__scroll_diff = 0
        self.__scroll_offs = 0

    def __update_scroll(self, eventtime):
        if self.__scroll_dir == 0 and self.__scroll_diff > 0:
            self.__scroll_dir = 1
            self.__scroll_offs = 0
        elif self.__scroll_dir and self.__scroll_diff > 0:
            self.__scroll_offs += self.__scroll_dir
            if self.__scroll_offs >= self.__scroll_diff:
                self.__scroll_dir = -1
            elif self.__scroll_offs <= 0:
                self.__scroll_dir = 1
        else:
            self.__clear_scroll()

    def __render_scroll(self, s):
        if self.__scroll_dir is None:
            self.__scroll_dir = 0
            self.__scroll_offs = 0
        return s[
            self.__scroll_offs:self._width + self.__scroll_offs
        ].ljust(self._width)

    def render(self, scroll=False):
        s = str(self._render())
        if self._width > 0:
            self.__scroll_diff = len(s) - self._width
            if (scroll and self._scroll is True and self.is_scrollable()
                    and self.__scroll_diff > 0):
                s = self.__render_scroll(s)
            else:
                self.__clear_scroll()
                s = s[:self._width].ljust(self._width)
        else:
            self.__clear_scroll()
        return s

    def _parse_bool(self, lst):
        try:
            return any([
                all([
                    self._lookup_bool(l2) for l2 in self._words_aslist(l1)
                ]) for l1 in lst
            ])
        except Exception:
            logging.exception("Parsing error")
            return False

    def _lookup_bool(self, b):
        if not self._asbool(b):
            if b[0] == '!':  # logical negation:
                return not (not not self._lookup_parameter(b[1:]))
            else:
                return not not self._lookup_parameter(b)
        return True

    def _lookup_parameter(self, literal):
        if self._isfloat(literal):
            return float(literal)
        else:
            try:
                key1, key2 = literal.split('.', 1)
                return self._menu.parameters[key1].get(key2)
            except Exception:
                return None

    def _asliteral(self, s):
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
        return s.lower() in ('y', 'yes', 't', 'true', 'on', '1')

    def _asint(self, s, default=0):
        if s is None:
            return default
        if isinstance(s, (int, float)):
            return int(s)
        s = str(s).strip()
        return int(float(s)) if self._isfloat(s) else int(default)

    def _asfloat(self, s, default=0.0):
        if s is None:
            return default
        if isinstance(s, (int, float)):
            return float(s)
        s = str(s).strip()
        return float(s) if self._isfloat(s) else float(default)

    def _lines_aslist(self, value, default=[]):
        if isinstance(value, str):
            value = filter(None, [x.strip() for x in value.splitlines()])
        try:
            return list(value)
        except Exception:
            logging.exception("Parsing error")
            return list(default)

    def _words_aslist(self, value, sep=',', default=[]):
        if isinstance(value, str):
            value = filter(None, [x.strip() for x in value.split(sep)])
        try:
            return list(value)
        except Exception:
            logging.exception("Parsing error")
            return list(default)

    def _aslist(self, value, flatten=True, default=[]):
        values = self._lines_aslist(value)
        if not flatten:
            return values
        result = []
        for value in values:
            subvalues = self._words_aslist(value, sep=',')
            result.extend(subvalues)
        return result

    def _isfloat(self, value):
        try:
            float(value)
            return True
        except ValueError:
            return False


# menu container baseclass
class MenuContainer(MenuElement):
    def __init__(self, menu, config):
        super(MenuContainer, self).__init__(menu, config)
        self._show_back = self._asbool(config.get('show_back', 'true'))
        self._show_title = self._asbool(config.get('show_title', 'true'))
        self._allitems = []
        self._items = []

    # overload
    def _names_aslist(self):
        return []

    # overload
    def is_accepted(self, item):
        return isinstance(item, MenuElement)

    def is_readonly(self):
        return False

    def is_editing(self):
        return any([item.is_editing() for item in self._items])

    def _lookup_item(self, s):
        if isinstance(s, str):
            s = self._menu.lookup_menuitem(s.strip())
        return s

    def find_item(self, item):
        index = None
        if item in self._items:
            index = self._items.index(item)
        else:
            for con in self._items:
                if isinstance(con, MenuContainer) and item in con:
                    index = self._items.index(con)
        return index

    def append_item(self, s):
        item = self._lookup_item(s)
        if item is not None:
            if not self.is_accepted(item):
                raise error("Menu item '%s'is not accepted!" % str(type(item)))
            if isinstance(item, (MenuContainer)):
                item.populate_items()
            self._allitems.append(item)

    def populate_items(self):
        self._allitems = []  # empty list
        if self._show_back is True:
            name = '[..]'
            if self._show_title:
                name += ' %s' % str(self._name)
            self.append_item(MenuCommand(self._menu, {'name': name,
                                                      'gcode': '',
                                                      'action': 'back'}))
        for name in self._names_aslist():
            self.append_item(name)
        self.update_items()

    def update_items(self):
        self._items = [item for item in self._allitems if item.is_enabled()]

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
        flist = {
            'int': int,
            'float': float,
            'bool': bool,
            'str': str,
            'abs': abs,
            'bin': bin,
            'hex': hex,
            'oct': oct
        }

        def mapper(left_min, left_max, right_min, right_max, cast_fn, index=0):
            # interpolate
            left_span = left_max - left_min
            right_span = right_max - right_min
            scale_factor = float(right_span) / float(left_span)

            def map_fn(values):
                return cast_fn(
                    right_min + (values[index]-left_min)*scale_factor
                )
            return map_fn

        def scaler(scale_factor, cast_fn, index=0):
            def scale_fn(values):
                return cast_fn(values[index]*scale_factor)
            return scale_fn

        def chooser(choices, cast_fn, index=0):
            def choose_fn(values):
                return choices[cast_fn(values[index])]
            return choose_fn

        def timerizer(key, index=0):
            time = {}

            def time_fn(values):
                try:
                    seconds = int(values[index])
                except Exception:
                    logging.exception("Seconds parsing error")
                    seconds = 0

                time['days'], time['seconds'] = divmod(seconds, 86400)
                time['hours'], time['seconds'] = divmod(time['seconds'], 3600)
                time['minutes'], time['seconds'] = divmod(time['seconds'], 60)

                if key in time:
                    return time[key]
                else:
                    return 0
            return time_fn

        def functionizer(key, index=0):
            def func_fn(values):
                if key in flist and callable(flist[key]):
                    return flist[key](values[index])
                else:
                    logging.error("Unknown function: '%s'" % str(key))
                    return values[index]
            return func_fn

        fn = None
        t = str(t).strip()
        # transform: idx.func(a,b,...)
        m = re.search(r"^(\d*)(?:\.?)([\S]+)(\([\S]*\))$", t)
        if m is not None:
            index = m.group(1) or 0
            fname = str(m.group(2)).lower()
            try:
                o = ast.literal_eval(m.group(3))
                if (fname == 'map' and isinstance(o, tuple) and len(o) == 4
                        and isinstance(o[3], (float, int))):
                    # mapper (interpolate), cast type by last parameter type
                    fn = mapper(o[0], o[1], o[2], o[3], type(o[3]), index)
                elif (fname == 'choose' and isinstance(o, tuple)
                        and len(o) == 2):
                    # boolean chooser for 2 size tuple
                    fn = chooser(o, bool, index)
                elif fname == 'choose' and isinstance(o, tuple) and len(o) > 2:
                    # int chooser for list
                    fn = chooser(o, int, index)
                elif (fname == 'choose' and isinstance(o, dict) and o.keys()
                        and isinstance(o.keys()[0], (int, float, str))):
                    # chooser, cast type by first key type
                    fn = chooser(o, type(o.keys()[0]), index)
                elif fname == 'scale' and isinstance(o, (float, int)):
                    # scaler, cast type depends from scale factor type
                    fn = scaler(o, type(o), index)
                elif fname in ('days', 'hours', 'minutes', 'seconds'):
                    fn = timerizer(fname, index)
                elif fname in flist:
                    fn = functionizer(fname, index)
                else:
                    logging.error(
                        "Unknown transform function: '%s'" % str(m.group(0)))
            except Exception:
                logging.exception("Transform parsing error")
        else:
            logging.error(
                "Invalid transform parameter: '%s'" % str(t))
        return fn

    def _transform_aslist(self):
        return list(filter(None, (
            self._parse_transform(t) for t in self._aslist(
                self.transform, flatten=False)
        )))

    def _parameter_aslist(self):
        lst = []
        for p in self._words_aslist(self.parameter):
            lst.append(self._lookup_parameter(p))
            if lst[-1] is None:
                logging.error("Parameter '%s' not found" % str(p))
        return list(lst)

    def _prepare_values(self, value=None):
        values = []
        for i, v in enumerate(self._parameter_aslist()):
            values += [value if i == 0 and value is not None else v]
        if values:
            try:
                values += [t(list(values)) for t in self._transform_aslist()]
            except Exception:
                logging.exception("Transformation error")
        return tuple(values)

    def _get_formatted(self, literal, val=None):
        values = self._prepare_values(val)
        if isinstance(literal, str) and len(values) > 0:
            try:
                literal = literal.format(*values)
            except Exception:
                logging.exception("Format error")
        return literal

    def _render(self):
        return self._get_formatted(self._name)


class MenuCommand(MenuItem):
    def __init__(self, menu, config):
        super(MenuCommand, self).__init__(menu, config)
        self._gcode = config.get('gcode')
        self._action = config.get('action', None)

    def is_readonly(self):
        return False

    def get_gcode(self):
        return self._get_formatted(self._gcode)

    def __call__(self):
        if self._action is not None:
            try:
                fmt = self._get_formatted(self._action)
                args = fmt.split()
                self._menu.run_action(args[0], *args[1:])
            except Exception:
                logging.exception("Action format error")


class MenuInput(MenuCommand):
    def __init__(self, menu, config):
        super(MenuInput, self).__init__(menu, config)
        self._reverse = self._asbool(config.get('reverse', 'false'))
        self._realtime = self._asbool(config.get('realtime', 'false'))
        self._readonly = self._aslist(
            config.get('readonly', 'false'), flatten=False)
        self._input_value = None
        self._input_min = config.getfloat('input_min', sys.float_info.min)
        self._input_max = config.getfloat('input_max', sys.float_info.max)
        self._input_step = config.getfloat('input_step', above=0.)

    def is_scrollable(self):
        return False

    def is_readonly(self):
        return self._parse_bool(self._readonly)

    def _render(self):
        return self._get_formatted(self._name, self._input_value)

    def get_gcode(self):
        return self._get_formatted(self._gcode, self._input_value)

    def is_editing(self):
        return self._input_value is not None

    def init_value(self):
        self._input_value = None
        if not self.is_readonly():
            args = self._prepare_values()
            if len(args) > 0 and self._isfloat(args[0]):
                self._input_value = float(args[0])
            else:
                logging.error("Cannot init input value")

    def reset_value(self):
        self._input_value = None

    def inc_value(self):
        prev_value = self._input_value
        if self._input_value is None:
            return

        if(self._reverse is True):
            self._input_value -= abs(self._input_step)
        else:
            self._input_value += abs(self._input_step)
        self._input_value = min(self._input_max, max(
            self._input_min, self._input_value))

        if self._realtime and prev_value != self._input_value:
            self._menu.run_script(self.get_gcode())

    def dec_value(self):
        prev_value = self._input_value
        if self._input_value is None:
            return

        if(self._reverse is True):
            self._input_value += abs(self._input_step)
        else:
            self._input_value -= abs(self._input_step)
        self._input_value = min(self._input_max, max(
            self._input_min, self._input_value))

        if self._realtime and prev_value != self._input_value:
            self._menu.run_script(self.get_gcode())


class MenuGroup(MenuContainer):
    def __init__(self, menu, config, sep=','):
        super(MenuGroup, self).__init__(menu, config)
        self._sep = sep
        self._show_back = False
        self.selected = None
        self.items = config.get('items')

    def is_accepted(self, item):
        return (super(MenuGroup, self).is_accepted(item)
                and type(item) is not MenuCard)

    def is_scrollable(self):
        return False

    def is_enabled(self):
        return not not len(self)

    def is_readonly(self):
        return all([item.is_readonly() for item in self._items])

    def _names_aslist(self):
        return self._words_aslist(self.items, sep=self._sep)

    def init(self):
        super(MenuGroup, self).init()
        for item in self._items:
            item.init()

    def _render_item(self, item, selected=False, scroll=False):
        name = "%s" % str(item.render(scroll))
        if selected and not self.is_editing():
            name = name if self._menu.blink_slow_state else ' '*len(name)
        elif selected and self.is_editing():
            name = name if self._menu.blink_fast_state else ' '*len(name)
        return name

    def _render(self):
        s = ""
        if self.selected is not None:
            self.selected = (
                (self.selected % len(self)) if len(self) > 0 else None)

        for i, item in enumerate(self):
            s += self._render_item(item, (i == self.selected), True)
        return s

    def _call_selected(self, method=None):
        res = None
        if self.selected is not None:
            try:
                if method is None:
                    res = self[self.selected]
                else:
                    res = getattr(self[self.selected], method)()
            except Exception:
                logging.exception("Call selected error")
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
        while (self.selected is not None
                and self.selected < len(self)
                and self._call_selected('is_readonly')):
            if self.selected < len(self) - 1:
                self.selected = (self.selected + 1)
            else:
                self.selected = None
        return self.selected

    def find_prev_item(self):
        if self.selected is None:
            self.selected = len(self) - 1
        elif self.selected > 0:
            self.selected -= 1
        else:
            self.selected = None
        # skip readonly
        while (self.selected is not None
                and self.selected >= 0
                and self._call_selected('is_readonly')):
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

    def _lookup_item(self, item):
        if isinstance(item, str) and '|' in item:
            item = MenuItemGroup(self._menu, {
                'name': 'ItemGroup',
                'items': item
            }, '|')
        elif isinstance(item, str) and item.isdigit():
            try:
                self._interval = max(0, int(item))
            except Exception:
                logging.exception("Interval parsing error")
            item = None
        return super(MenuCycler, self)._lookup_item(item)

    def _second_tick(self, eventtime):
        super(MenuCycler, self)._second_tick(eventtime)
        if self._interval > 0:
            self.__interval_cnt = (self.__interval_cnt+1) % self._interval
            if self.__interval_cnt == 0 and self.__alllen > 0:
                self._curr_idx = (self._curr_idx+1) % self.__alllen
        else:
            self._curr_idx = 0

    def heartbeat(self, eventtime):
        super(MenuCycler, self).heartbeat(eventtime)
        for item in self._items:
            item.heartbeat(eventtime)

    def update_items(self):
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
        self._enter_gcode = config.get('enter_gcode', None)
        self._leave_gcode = config.get('leave_gcode', None)
        self.items = config.get('items')

    def is_accepted(self, item):
        return (super(MenuList, self).is_accepted(item)
                and type(item) is not MenuCard)

    def _names_aslist(self):
        return self._lines_aslist(self.items)

    def _lookup_item(self, item):
        if isinstance(item, str) and ',' in item:
            item = MenuGroup(self._menu, {'name': 'Group', 'items': item}, ',')
        return super(MenuList, self)._lookup_item(item)

    def update_items(self):
        super(MenuList, self).update_items()
        for item in self._items:
            if isinstance(item, MenuGroup) and not item.is_editing():
                item.update_items()

    def get_enter_gcode(self):
        return self._enter_gcode

    def get_leave_gcode(self):
        return self._leave_gcode


class MenuVSDCard(MenuList):
    def __init__(self, menu, config):
        super(MenuVSDCard, self).__init__(menu, config)

    def _populate_files(self):
        sdcard = self._menu.objs['virtual_sdcard']
        if sdcard is not None:
            files = sdcard.get_file_list()
            for fname, fsize in files:
                gcode = [
                    'M23 /%s' % str(fname)
                ]
                self.append_item(MenuCommand(self._menu, {
                    'name': '%s' % str(fname),
                    'cursor': '+',
                    'gcode': "\n".join(gcode)
                }))

    def populate_items(self):
        super(MenuVSDCard, self).populate_items()
        self._populate_files()


class MenuCard(MenuGroup):
    def __init__(self, menu, config):
        super(MenuCard, self).__init__(menu, config)
        self.content = config.get('content')

    def _names_aslist(self):
        return self._lines_aslist(self.items)

    def _content_aslist(self):
        return filter(None, [
            self._asliteral(s) for s in self._lines_aslist(self.content)
        ])

    def update_items(self):
        self._items = self._allitems[:]
        for item in self._items:
            if isinstance(item, MenuGroup) and not item.is_editing():
                item.update_items()

    def _lookup_item(self, item):
        if isinstance(item, str) and ',' in item:
            item = MenuCycler(self._menu, {
                'name': 'Cycler',
                'items': item
            }, ',')
        return super(MenuCard, self)._lookup_item(item)

    def render_content(self, eventtime):
        if self.selected is not None:
            self.selected = (
                (self.selected % len(self)) if len(self) > 0 else None)

        items = []
        for i, item in enumerate(self):
            name = ''
            if item.is_enabled():
                item.heartbeat(eventtime)
                name = self._render_item(item, (i == self.selected), True)
            items.append(name)
        lines = []
        for line in self._content_aslist():
            try:
                lines.append(str(line).format(*items))
            except Exception:
                logging.exception('Card rendering error')
        return lines

    def _render(self):
        return self._name


class MenuDeck(MenuList):
    def __init__(self, menu, config):
        super(MenuDeck, self).__init__(menu, config)
        self._show_back = False
        self._show_title = False

    def _names_aslist(self):
        return self._aslist(self.items)

    def is_accepted(self, item):
        return type(item) is MenuCard

    def _render(self):
        return self._name


menu_items = {
    'item': MenuItem,
    'command': MenuCommand,
    'input': MenuInput,
    'list': MenuList,
    'vsdcard': MenuVSDCard,
    'deck': MenuDeck,
    'card': MenuCard
}
# Default dimensions for lcds (rows, cols)
LCD_dims = {'st7920': (4, 16), 'hd44780': (4, 20), 'uc1701': (4, 16)}

MENU_UPDATE_DELAY = .100
TIMER_DELAY = .200
BLINK_FAST_SEQUENCE = (True, True, False, False)
BLINK_SLOW_SEQUENCE = (True, True, True, True, False, False, False)


class MenuManager:
    def __init__(self, config, lcd_chip):
        self.running = False
        self.menuitems = {}
        self.menustack = []
        self._recursive_guard = []
        self.top_row = 0
        self.selected = 0
        self.blink_fast_state = True
        self.blink_slow_state = True
        self.blink_fast_idx = 0
        self.blink_slow_idx = 0
        self.timeout_idx = 0
        self.lcd_chip = lcd_chip
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
        # load servo name & output_pin names
        self.lookup_section_names(config, 'output_pin')
        self.lookup_section_names(config, 'servo')
        self.root = None
        self._root = config.get('menu_root', None)
        self.autorun = config.getboolean('menu_autorun', False)
        dims = config.getchoice('lcd_type', LCD_dims)
        self.rows = config.getint('rows', dims[0])
        self.cols = config.getint('cols', dims[1])
        self.timeout = config.getint('menu_timeout', 0)
        self.timer = 0
        # buttons
        self.encoder_pins = config.get('encoder_pins', None)
        self.click_pin = config.get('click_pin', None)
        self.back_pin = config.get('back_pin', None)
        self.up_pin = config.get('up_pin', None)
        self.down_pin = config.get('down_pin', None)
        self.kill_pin = config.get('kill_pin', None)
        # printer objects
        self.buttons = self.printer.try_load_module(config, "buttons")
        # register itself for a printer_state callback
        config.get_printer().add_object('menu', self)
        # register buttons & encoder
        if self.buttons:
            if self.encoder_pins:
                try:
                    pin1, pin2 = self.encoder_pins.split(',')
                except Exception:
                    raise config.error("Unable to parse encoder_pins")
                self.buttons.register_rotary_encoder(
                    pin1.strip(), pin2.strip(),
                    self.encoder_cw_callback, self.encoder_ccw_callback)
            if self.click_pin:
                self.buttons.register_button_push(
                    self.click_pin, self.click_callback)
            if self.back_pin:
                self.buttons.register_button_push(
                    self.back_pin, self.back_callback)
            if self.up_pin:
                self.buttons.register_button_push(
                    self.up_pin, self.up_callback)
            if self.down_pin:
                self.buttons.register_button_push(
                    self.down_pin, self.down_callback)
            if self.kill_pin:
                self.buttons.register_button_push(
                    self.kill_pin, self.kill_callback)

        # Add MENU commands
        self.gcode.register_mux_command("MENU", "DO", 'dump', self.cmd_DO_DUMP,
                                        desc=self.cmd_DO_help)
        self.gcode.register_mux_command("MENU", "DO", 'exit', self.cmd_DO_EXIT,
                                        desc=self.cmd_DO_help)
        self.gcode.register_mux_command("MENU", "DO", 'back', self.cmd_DO_BACK,
                                        desc=self.cmd_DO_help)
        # load items
        self.load_menuitems(config)

    def printer_state(self, state):
        if state == 'ready':
            # Load menu root
            if self._root is not None:
                self.root = self.lookup_menuitem(self._root)
            # Load printer objects available in ready state
            for name in self.objs.keys():
                if self.objs[name] is None:
                    self.objs[name] = self.printer.lookup_object(name, None)
                elif isinstance(self.objs[name], dict):
                    for key, obj in self.objs[name].items():
                        if isinstance(obj, str):
                            self.objs[name][key] = self.printer.lookup_object(
                                obj, None)
            # start timer
            reactor = self.printer.get_reactor()
            reactor.register_timer(self.timer_event, reactor.NOW)

    def timer_event(self, eventtime):
        # take next from sequence
        self.blink_fast_idx = (
            (self.blink_fast_idx+1) % len(BLINK_FAST_SEQUENCE)
        )
        self.blink_slow_idx = (
            (self.blink_slow_idx+1) % len(BLINK_SLOW_SEQUENCE)
        )
        self.timeout_idx = (self.timeout_idx+1) % 5  # 0.2*5 = 1s
        self.blink_fast_state = (
            not not BLINK_FAST_SEQUENCE[self.blink_fast_idx]
        )
        self.blink_slow_state = (
            not not BLINK_SLOW_SEQUENCE[self.blink_slow_idx]
        )
        if self.timeout_idx == 0:
            self.timeout_check(eventtime)

        return eventtime + TIMER_DELAY

    def timeout_check(self, eventtime):
        # check timeout
        if (self.is_running() and self.timeout > 0
                and not self._timeout_autorun_root()):
            if self.timer >= self.timeout:
                self.exit()
            self.timer += 1
        else:
            self.timer = 0

    def _timeout_autorun_root(self):
        return (self.autorun is True and self.root is not None
                and self.stack_peek() is self.root and self.selected == 0)

    def is_running(self):
        return self.running

    def begin(self, eventtime):
        self.menustack = []
        self._recursive_guard = []
        self.top_row = 0
        self.selected = 0
        self.timer = 0
        if isinstance(self.root, MenuContainer):
            self.update_parameters(eventtime)
            self.root.populate_items()
            self.stack_push(self.root)
            self.running = True
            return
        elif self.root is not None:
            logging.error("Invalid root '%s', menu stopped!" % str(self._root))

        self.running = False

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
                    self.parameters[name] = self.objs[name].get_status(
                        eventtime)
                except Exception:
                    self.parameters[name] = {}
                self.parameters[name].update({'is_enabled': True})
                # get additional info
                if name == 'toolhead':
                    pos = self.objs[name].get_position()
                    self.parameters[name].update({
                        'xpos': pos[0],
                        'ypos': pos[1],
                        'zpos': pos[2],
                        'epos': pos[3]
                    })
                    self.parameters[name].update({
                        'is_printing':
                            (self.parameters[name]['status'] == "Printing"),
                        'is_ready':
                            (self.parameters[name]['status'] == "Ready"),
                        'is_idle':
                            (self.parameters[name]['status'] == "Idle")
                    })
                elif name == 'extruder0':
                    info = self.objs[name].get_heater().get_status(eventtime)
                    self.parameters[name].update(info)
                elif name == 'extruder1':
                    info = self.objs[name].get_heater().get_status(eventtime)
                    self.parameters[name].update(info)
                elif name == 'display':
                    self.parameters[name].update({
                        'progress': self.objs[name].progress or 0,
                        'progress.visible': not not self.objs[name].progress,
                        'message': self.objs[name].message or '',
                        'message.visible': not not self.objs[name].message,
                        'is_enabled': True
                    })
            elif type(self.objs[name]) == dict:
                self.parameters[name] = {}
                if name == 'output_pin' or name == 'servo':
                    for key, obj in self.objs[name].items():
                        try:
                            self.parameters[name].update({
                                '%s.value' % str(key): obj.last_value,
                                '%s.is_enabled' % str(key): True
                            })
                        except Exception:
                            logging.exception('Parameter update error')
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
        if not container.is_editing():
            container.update_items()
        self.menustack.append(container)

    def stack_pop(self):
        container = None
        if self.stack_size() > 0:
            container = self.menustack.pop()
            if not isinstance(container, MenuContainer):
                raise error("Wrong type, expected MenuContainer")
            top = self.stack_peek()
            if top is not None:
                if not isinstance(container, MenuContainer):
                    raise error("Wrong type, expected MenuContainer")
                if not top.is_editing():
                    top.update_items()
                self.run_script(container.get_leave_gcode())
                self.run_script(top.get_enter_gcode())
            else:
                self.run_script(container.get_leave_gcode())
        return container

    def stack_size(self):
        return len(self.menustack)

    def stack_peek(self, lvl=0):
        container = None
        if self.stack_size() > lvl:
            container = self.menustack[self.stack_size()-lvl-1]
        return container

    def render(self, eventtime):
        lines = []
        self.update_parameters(eventtime)
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            container.heartbeat(eventtime)
            # clamps
            self.top_row = max(0, min(
                self.top_row, len(container) - self.rows))
            self.selected = max(0, min(
                self.selected, len(container)-1))
            if isinstance(container, MenuDeck):
                if not container.is_editing():
                    container.update_items()
                container[self.selected].heartbeat(eventtime)
                lines = container[self.selected].render_content(eventtime)
            else:
                for row in range(self.top_row, self.top_row + self.rows):
                    s = ""
                    if row < len(container):
                        selected = (row == self.selected)
                        current = container[row]
                        if selected:
                            current.heartbeat(eventtime)
                            if (isinstance(current, (MenuInput, MenuGroup))
                                    and current.is_editing()):
                                s += MenuCursor.EDIT
                            elif isinstance(current, MenuElement):
                                s += current.cursor
                            else:
                                s += MenuCursor.SELECT
                        else:
                            s += MenuCursor.NONE

                        name = "%s" % str(current.render(selected))
                        i = len(s)
                        if isinstance(current, MenuList):
                            s += name[:self.cols-i-1].ljust(self.cols-i-1)
                            s += '>'
                        else:
                            s += name[:self.cols-i].ljust(self.cols-i)
                    lines.append(s.ljust(self.cols))
        return lines

    def screen_update_event(self, eventtime):
        if self.is_running():
            self.lcd_chip.clear()
            for y, line in enumerate(self.render(eventtime)):
                self.lcd_chip.write_text(0, y, line)
            self.lcd_chip.flush()
            return eventtime + MENU_UPDATE_DELAY
        elif not self.is_running() and self.autorun is True:
            # lets start and populate the menu items
            self.begin(eventtime)
            return eventtime + MENU_UPDATE_DELAY
        else:
            return 0

    def up(self):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            current = container[self.selected]
            if (isinstance(current, (MenuInput, MenuGroup))
                    and current.is_editing()):
                current.dec_value()
            elif (isinstance(current, MenuGroup)
                    and current.find_prev_item() is not None):
                pass
            else:
                if self.selected == 0:
                    return
                if self.selected > self.top_row:
                    self.selected -= 1
                else:
                    self.top_row -= 1
                    self.selected -= 1
                # init element
                if isinstance(container[self.selected], MenuElement):
                    container[self.selected].init()
                # wind up group last item or init item
                if isinstance(container[self.selected], MenuGroup):
                    container[self.selected].find_prev_item()

    def down(self):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            current = container[self.selected]
            if (isinstance(current, (MenuInput, MenuGroup))
                    and current.is_editing()):
                current.inc_value()
            elif (isinstance(current, MenuGroup)
                    and current.find_next_item() is not None):
                pass
            else:
                if self.selected >= len(container) - 1:
                    return
                if self.selected < self.top_row + self.rows - 1:
                    self.selected += 1
                else:
                    self.top_row += 1
                    self.selected += 1
                # init element
                if isinstance(container[self.selected], MenuElement):
                    container[self.selected].init()
                # wind up group first item
                if isinstance(container[self.selected], MenuGroup):
                    container[self.selected].find_next_item()

    def back(self):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            current = container[self.selected]
            if (isinstance(current, (MenuInput, MenuGroup))
                    and current.is_editing()):
                return
            parent = self.stack_peek(1)
            if isinstance(parent, MenuContainer):
                self.stack_pop()
                index = parent.find_item(container)
                if index is not None and index < len(parent):
                    self.top_row = index
                    self.selected = index
                else:
                    self.top_row = 0
                    self.selected = 0
                # init element
                if isinstance(parent[self.selected], MenuElement):
                    parent[self.selected].init()
                # wind up group first item or init item
                if isinstance(parent[self.selected], MenuGroup):
                    parent[self.selected].find_next_item()
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

    def run_action(self, action, *args):
        action = str(action).strip().lower()
        if action == 'back':
            self.back()
        elif action == 'exit':
            self.exit()
        elif action == 'log':
            try:
                logging.info("Info from log action: {}".format(*args))
            except Exception:
                logging.exception("Malformed log action call")
        else:
            logging.error("Unknown action %s" % (action))

    def run_script(self, script):
        if script is not None:
            try:
                self.gcode.run_script(script)
            except Exception:
                logging.exception("Script running error")

    def add_menuitem(self, name, menu):
        if name in self.menuitems:
            raise self.printer.config_error(
                "Menu object '%s' already created" % (name,))
        self.menuitems[name] = menu

    def lookup_menuitem(self, name, peek=False):
        if name is None:
            return None
        if name not in self.menuitems:
            raise self.printer.config_error(
                "Unknown menuitem '%s'" % (name,))
        if not peek and isinstance(self.menuitems[name], MenuContainer):
            if name in self._recursive_guard:
                raise self.printer.config_error(
                    "Containers can only be used once! "
                    "Potential recursive relation of '%s'" % (name,))
            else:
                self._recursive_guard.append(name)
        return self.menuitems[name]

    def lookup_section_names(self, config, section):
        for cfg in config.get_prefix_sections('%s ' % section):
            name = " ".join(cfg.get_name().split()[1:])
            self.objs[section][name] = cfg.get_name()

    def load_menuitems(self, config):
        for cfg in config.get_prefix_sections('menu '):
            name = " ".join(cfg.get_name().split()[1:])
            item = cfg.getchoice('type', menu_items)(self, cfg)
            self.add_menuitem(name, item)

    cmd_DO_help = "Menu do things (dump, exit, back)"

    def cmd_DO_DUMP(self, params):
        for key1 in self.parameters:
            if type(self.parameters[key1]) == dict:
                for key2 in self.parameters[key1]:
                    msg = "{0}.{1} = {2}".format(
                        key1, key2,
                        self.parameters[key1].get(key2)
                    )
                    logging.info(msg)
                    self.gcode.respond_info(msg)
            else:
                msg = "{0} = {1}".format(key1, self.parameters.get(key1))
                logging.info(msg)
                self.gcode.respond_info(msg)

    def cmd_DO_EXIT(self, params):
        self.exit()

    def cmd_DO_BACK(self, params):
        self.back()

    # buttons & encoder callbacks
    def encoder_cw_callback(self, eventtime):
        self.up()

    def encoder_ccw_callback(self, eventtime):
        self.down()

    def click_callback(self, eventtime):
        if self.click_pin:
            if not self.is_running():
                # lets start and populate the menu items
                self.begin(eventtime)
            elif self.is_running():
                self.select()

    def back_callback(self, eventtime):
        if self.back_pin:
            self.back()

    def up_callback(self, eventtime):
        if self.up_pin:
            self.up()

    def down_callback(self, eventtime):
        if self.down_pin:
            self.down()

    def kill_callback(self, eventtime):
        if self.kill_pin:
            # Emergency Stop
            self.printer.invoke_shutdown("Shutdown due to kill button!")
