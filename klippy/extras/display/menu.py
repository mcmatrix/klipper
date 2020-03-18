# -*- coding: utf-8 -*-
# Support for display menu (v2.0)
#
# Copyright (C) 2019 Janar Sööt <janar.soot@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import os, logging, ast
from string import Template


class error(Exception):
    pass


class sentinel:
    pass


class MenuConfig(dict):
    """Wrapper for dict to emulate configfile get_name for namespace.
        __ns - item namespace key, used in item relative paths
        $__id - generated id text variable
    """
    def get_name(self):
        __id = '__menu_' + hex(id(self)).lstrip("0x").rstrip("L")
        return Template('menu ' + self.get(
            '__ns', __id)).safe_substitute(__id=__id)

    def get_prefix_options(self, prefix):
        return [o for o in self.keys() if o.startswith(prefix)]


class MenuCommand(object):
    def __init__(self, manager, config):
        self._manager = manager
        self.cursor = config.get('cursor', '>')
        self._scroll = manager.asbool(config.get('scroll', 'False'))
        self._enable_tpl = manager.gcode_macro.load_template(
            config, 'enable', 'True')
        self._name_tpl = manager.gcode_macro.load_template(
            config, 'name')
        # item namespace - used in relative paths
        self._ns = " ".join(config.get_name().split(' ')[1:])
        self._last_heartbeat = None
        self.__scroll_offs = 0
        self.__scroll_diff = 0
        self.__scroll_dir = None
        self.__last_state = True
        # display width is used and adjusted by cursor size
        self._width = self.manager.cols - len(self._cursor)
        # load scripts
        self._script_tpls = {}
        prfx = 'script_'
        for o in config.get_prefix_options(prfx):
            script = config.get(o, '')
            name = o[len(prfx):]
            self._script_tpls[name] = manager.gcode_macro.create_template(
                '%s:%s' % (self.ns, o), script)
        # init
        self.init()

    # override
    def init(self):
        pass

    def _name(self):
        context = self.get_context()
        return self.manager.stripliterals(self.manager.asflatline(
            self._name_tpl.render(context)))

    # override
    def _second_tick(self, eventtime):
        pass

    # override
    def is_editing(self):
        return False

    # override
    def is_scrollable(self):
        return True

    # override
    def is_enabled(self):
        return self.eval_enable()

    # override
    def start_editing(self):
        pass

    # override
    def stop_editing(self):
        pass

    # override
    def get_context(self, cxt=None):
        # get default menu context
        context = self.manager.get_context(cxt)
        context['menu'].update({
            'is_editing': self.is_editing(),
            'width': self._width,
            'ns': self.ns
        })
        return context

    def eval_enable(self):
        context = self.get_context()
        return self.manager.asbool(self._enable_tpl.render(context))

    # Called when a item is selected
    def select(self):
        self.__clear_scroll()
        self.run_script("select")

    def heartbeat(self, eventtime):
        self._last_heartbeat = eventtime
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

    def __name_scroll(self, s):
        if self.__scroll_dir is None:
            self.__scroll_dir = 0
            self.__scroll_offs = 0
        return s[
            self.__scroll_offs:self._width + self.__scroll_offs
        ].ljust(self._width)

    def render_name(self, selected=False):
        s = str(self._name())
        # scroller
        if self._width > 0:
            self.__scroll_diff = len(s) - self._width
            if (selected and self._scroll is True and self.is_scrollable()
                    and self.__scroll_diff > 0):
                s = self.__name_scroll(s)
            else:
                self.__clear_scroll()
                s = s[:self._width].ljust(self._width)
        else:
            self.__clear_scroll()
        # add cursors
        if selected and not self.is_editing():
            s = self.cursor + s
        elif selected and self.is_editing():
            s = '*' + s
        else:
            s = ' ' + s
        return s

    def ns_prefix(self, name):
        name = str(name).strip()
        if name.startswith('..'):
            name = ' '.join([(' '.join(self.ns.split(' ')[:-1])), name[2:]])
        elif name.startswith('.'):
            name = ' '.join([self.ns, name[1:]])
        return name.strip()

    def send_event(self, event, *args):
        return self.manager.send_event(
            "%s:%s" % (self.ns, str(event)), *args)

    def get_script(self, name):
        if name in self._script_tpls:
            return self._script_tpls[name]
        return None

    def run_script(self, name, cxt=None):
        def _get_template(n, from_ns='.'):
            _source = self.manager.lookup_menuitem(self.ns_prefix(from_ns))
            script = _source.get_script(n)
            if script is None:
                raise error(
                    "{}: script '{}' not found".format(_source.ns, str(n)))
            return script.template
        result = ""
        # init context
        context = self.get_context(cxt)
        if name in self._script_tpls:
            context['menu'].update({
                'script_by_name': _get_template
            })
            result = self._script_tpls[name].render(context)
        # run result as gcode
        self.manager.queue_gcode(result)
        # default behaviour
        _handle = getattr(self, "handle_script_" + name, None)
        if callable(_handle):
            _handle()
        return result

    @property
    def cursor(self):
        return str(self._cursor)[:1]

    @cursor.setter
    def cursor(self, value):
        self._cursor = str(value)[:1]

    @property
    def manager(self):
        return self._manager

    @property
    def width(self):
        return self._width

    @property
    def ns(self):
        return self._ns


class MenuContainer(MenuCommand):
    """Menu container abstract class.
    """
    def __init__(self, manager, config):
        if type(self) is MenuContainer:
            raise error(
                'Abstract MenuContainer cannot be instantiated directly')
        super(MenuContainer, self).__init__(manager, config)
        self.cursor = config.get('cursor', '>')
        self.__selected = None
        self._allitems = []
        self._names = []
        self._items = []

    def init(self):
        super(MenuContainer, self).init()
        # recursive guard
        self._parents = []

    # overload
    def _names_aslist(self):
        return []

    # overload
    def is_accepted(self, item):
        return isinstance(item, MenuCommand)

    def is_editing(self):
        return any([item.is_editing() for item in self._items])

    def stop_editing(self):
        for item in self._items:
            if item.is_editing():
                item.stop_editing()

    def lookup_item(self, item):
        if isinstance(item, str):
            name = item.strip()
            ns = self.ns_prefix(name)
            return (self.manager.lookup_menuitem(ns), name)
        elif isinstance(item, MenuCommand):
            return (item, item.ns)
        return (None, item)

    # overload
    def _lookup_item(self, item):
        return self.lookup_item(item)

    def _index_of(self, item):
        try:
            index = None
            if isinstance(item, str):
                s = item.strip()
                index = self._names.index(s)
            elif isinstance(item, MenuCommand):
                index = self._items.index(item)
            return index
        except ValueError:
            return None

    def index_of(self, item, look_inside=False):
        index = self._index_of(item)
        if index is None and look_inside is True:
            for con in self:
                if isinstance(con, MenuContainer) and con._index_of(item):
                    index = self._index_of(con)
        return index

    def add_parents(self, parents):
        if isinstance(parents, list):
            self._parents.extend(parents)
        else:
            self._parents.append(parents)

    def assert_recursive_relation(self, parents=None):
        assert self not in (parents or self._parents), \
            "Recursive relation of '%s' container" % (self.ns,)

    def insert_item(self, s, index=None):
        self._insert_item(s, index)

    def _insert_item(self, s, index=None):
        item, name = self._lookup_item(s)
        if item is not None:
            if not self.is_accepted(item):
                raise error("Menu item '%s'is not accepted!" % str(type(item)))
            if isinstance(item, (MenuCommand)):
                item.init()
            if isinstance(item, (MenuContainer)):
                item.add_parents(self._parents)
                item.add_parents(self)
                item.assert_recursive_relation()
                item.populate()
            if index is None:
                self._allitems.append((item, name))
            else:
                self._allitems.insert(index, (item, name))

    # overload
    def _populate(self):
        pass

    def populate(self):
        self._allitems = []  # empty list
        for name in self._names_aslist():
            self._insert_item(name)
        # populate successor items
        self._populate()
        # send populate event
        self.send_event('populate', self)
        self.update_items()

    def update_items(self):
        _a = [(item, name) for item, name in self._allitems
              if item.is_enabled()]
        self._items, self._names = zip(*_a) or ([], [])

    # select methods
    def init_selection(self):
        self.select_at(0)

    def select_at(self, index):
        self.__selected = index
        # select element
        item = self.selected_item()
        if isinstance(item, MenuCommand):
            item.select()
        return item

    def select_item(self, needle):
        if isinstance(needle, MenuCommand):
            if self.selected_item() is not needle:
                index = self.index_of(needle)
                if index is not None:
                    self.select_at(index)
        else:
            logging.error("Cannot select non menuitem")
        return self.selected

    def selected_item(self):
        if isinstance(self.selected, int) and 0 <= self.selected < len(self):
            return self[self.selected]
        else:
            return None

    def select_next(self):
        if not isinstance(self.selected, int):
            index = 0 if len(self) else None
        elif 0 <= self.selected < len(self) - 1:
            index = self.selected + 1
        else:
            index = self.selected
        return self.select_at(index)

    def select_prev(self):
        if not isinstance(self.selected, int):
            index = 0 if len(self) else None
        elif 0 < self.selected < len(self):
            index = self.selected - 1
        else:
            index = self.selected
        return self.select_at(index)

    # override
    def render_container(self, eventtime):
        return ("", None)

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

    def __getitem__(self, key):
        return self._items[key]

    @property
    def selected(self):
        return self.__selected


class MenuInput(MenuCommand):
    def __init__(self, manager, config,):
        super(MenuInput, self).__init__(manager, config)
        self._reverse = manager.asbool(config.get('reverse', 'false'))
        self._input_tpl = manager.gcode_macro.load_template(config, 'input')
        self._input_min_tpl = manager.gcode_macro.load_template(
            config, 'input_min', '-999999.0')
        self._input_max_tpl = manager.gcode_macro.load_template(
            config, 'input_max', '999999.0')
        self._input_step = config.getfloat('input_step', above=0.)
        self._input_step2 = config.getfloat('input_step2', 0, minval=0.)

    def init(self):
        super(MenuInput, self).init()
        self._is_dirty = False
        self.__last_change = None
        self._input_value = None

    def is_scrollable(self):
        return False

    def is_editing(self):
        return self._input_value is not None

    def stop_editing(self):
        if not self.is_editing():
            return
        self._reset_value()

    def start_editing(self):
        if self.is_editing():
            return
        self._init_value()

    def heartbeat(self, eventtime):
        super(MenuInput, self).heartbeat(eventtime)
        if (self._is_dirty is True
                and self.__last_change is not None
                and self._input_value is not None
                and (eventtime - self.__last_change) > 0.250):
            self.run_script('change')
            self._is_dirty = False

    def get_context(self, cxt=None):
        context = super(MenuInput, self).get_context(cxt)
        context['menu'].update({
            'input': self.manager.asfloat(
                self._eval_value() if self._input_value is None
                else self._input_value)
        })
        return context

    def eval_enable(self):
        context = super(MenuInput, self).get_context()
        return self.manager.asbool(self._enable_tpl.render(context))

    def _eval_min(self):
        context = super(MenuInput, self).get_context()
        return self._input_min_tpl.render(context)

    def _eval_max(self):
        context = super(MenuInput, self).get_context()
        return self._input_max_tpl.render(context)

    def _eval_value(self):
        context = super(MenuInput, self).get_context()
        return self._input_tpl.render(context)

    def _value_changed(self):
        self.__last_change = self._last_heartbeat
        self._is_dirty = True

    def _init_value(self):
        self._input_value = None
        self._input_min = self.manager.asfloat(self._eval_min())
        self._input_max = self.manager.asfloat(self._eval_max())
        value = self._eval_value()
        if self.manager.isfloat(value):
            self._input_value = min(self._input_max, max(
                self._input_min, self.manager.asfloat(value)))
            self._value_changed()
        else:
            logging.error("Cannot init input value")

    def _reset_value(self):
        self._input_value = None

    def inc_value(self, fast_rate=False):
        last_value = self._input_value
        input_step = (self._input_step2 if fast_rate and self._input_step2 > 0
                      else self._input_step)
        if self._input_value is None:
            return

        if(self._reverse is True):
            self._input_value -= abs(input_step)
        else:
            self._input_value += abs(input_step)
        self._input_value = min(self._input_max, max(
            self._input_min, self._input_value))

        if last_value != self._input_value:
            self._value_changed()

    def dec_value(self, fast_rate=False):
        last_value = self._input_value
        input_step = (self._input_step2 if fast_rate and self._input_step2 > 0
                      else self._input_step)
        if self._input_value is None:
            return

        if(self._reverse is True):
            self._input_value += abs(input_step)
        else:
            self._input_value -= abs(input_step)
        self._input_value = min(self._input_max, max(
            self._input_min, self._input_value))

        if last_value != self._input_value:
            self._value_changed()

    # default behaviour for shortpress
    def handle_script_shortpress(self):
        if not self.is_editing():
            self.start_editing()
        elif self.is_editing():
            self.stop_editing()


class MenuList(MenuContainer):
    def __init__(self, manager, config):
        super(MenuList, self).__init__(manager, config)
        self._show_title = manager.asbool(config.get('show_title', 'True'))

    def _names_aslist(self):
        return self.manager.lookup_names(self.ns)

    def _populate(self):
        super(MenuList, self)._populate()
        #  add back as first item
        name = '..'
        if self._show_title:
            name += ' [%s]' % str(self._name())
        item = self.manager.menuitem_from({
            'type': 'command',
            'name': self.manager.asliteral(name),
            'cursor': '>',
            'script_press': '{menu.back()}'
        })
        self.insert_item(item, 0)

    def render_container(self, eventtime):
        rows = []
        selected_row = None
        try:
            for row, item in enumerate(self):
                s = ""
                selected = (row == self.selected)
                if selected:
                    item.heartbeat(eventtime)
                    selected_row = len(rows)
                name = str(item.render_name(selected))
                if isinstance(item, MenuList):
                    s += name[:item.width-1].ljust(item.width-1)
                    s += '>'
                else:
                    s += name[:item.width].ljust(item.width)
                rows.append(s)
        except Exception:
            logging.exception('List rendering error')
        return ("\n".join(rows), selected_row)


class MenuVSDList(MenuList):
    def __init__(self, manager, config):
        super(MenuVSDList, self).__init__(manager, config)

    def _populate(self):
        super(MenuVSDList, self)._populate()
        sdcard = self.manager.objs.get('virtual_sdcard')
        if sdcard is not None:
            files = sdcard.get_file_list()
            for fname, fsize in files:
                gcode = [
                    'M23 /%s' % str(fname)
                ]
                self.insert_item(self.manager.menuitem_from({
                    'type': 'command',
                    'name': self.manager.asliteral(fname),
                    'cursor': '+',
                    'script_press': "\n".join(gcode),
                    'scroll': True
                }))


menu_items = {
    'command': MenuCommand,
    'input': MenuInput,
    'list': MenuList,
    'vsdlist': MenuVSDList
}

MENU_UPDATE_DELAY = .100
TIMER_DELAY = .100
LONG_PRESS_DURATION = 0.800


class MenuManager:
    def __init__(self, config, display):
        self.running = False
        self.menuitems = {}
        self.menustack = []
        self.top_row = 0
        self._defaults_revision = 0
        self.timeout_idx = 0
        self.display = display
        self.lcd_chip = display.get_lcd_chip()
        self.printer = config.get_printer()
        self.pconfig = self.printer.lookup_object('configfile')
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode_queue = []
        self.context = {}
        self.defaults = {}
        self.objs = {}
        self.root = None
        self._root = config.get('menu_root', '__main')
        self.cols, self.rows = self.lcd_chip.get_dimensions()
        self.timeout = config.getint('menu_timeout', 0)
        self.timer = 0
        # buttons
        self.encoder_pins = config.get('encoder_pins', None)
        self.click_pin = config.get('click_pin', None)
        self.back_pin = config.get('back_pin', None)
        self.up_pin = config.get('up_pin', None)
        self.down_pin = config.get('down_pin', None)
        self.kill_pin = config.get('kill_pin', None)
        # analog button ranges
        self.analog_range_click_pin = config.get(
            'analog_range_click_pin', None)
        self.analog_range_back_pin = config.get(
            'analog_range_back_pin', None)
        self.analog_range_up_pin = config.get(
            'analog_range_up_pin', None)
        self.analog_range_down_pin = config.get(
            'analog_range_down_pin', None)
        self.analog_range_kill_pin = config.get(
            'analog_range_kill_pin', None)
        self._last_click_press = 0
        self._last_click_state = 0
        self.analog_pullup = config.getfloat(
            'analog_pullup_resistor', 4700., above=0.)
        self._encoder_fast_rate = config.getfloat(
            'encoder_fast_rate', .03, above=0.)
        self._last_encoder_cw_eventtime = 0
        self._last_encoder_ccw_eventtime = 0
        # printer objects
        self.buttons = self.printer.load_object(config, "buttons")
        # register itself for printer callbacks
        self.printer.add_object('menu', self)
        self.printer.register_event_handler("klippy:ready", self.handle_ready)
        # register buttons & encoder
        if self.buttons:
            # digital buttons
            if self.encoder_pins:
                try:
                    pin1, pin2 = self.encoder_pins.split(',')
                except Exception:
                    raise config.error("Unable to parse encoder_pins")
                self.buttons.register_rotary_encoder(
                    pin1.strip(), pin2.strip(),
                    self.encoder_cw_callback, self.encoder_ccw_callback)
            if self.click_pin:
                if self.analog_range_click_pin is not None:
                    try:
                        p_min, p_max = map(
                            float, self.analog_range_click_pin.split(','))
                    except Exception:
                        raise config.error(
                            "Unable to parse analog_range_click_pin")
                    self.buttons.register_adc_button(
                        self.click_pin, p_min, p_max, self.analog_pullup,
                        self.click_callback)
                else:
                    self.buttons.register_buttons(
                        [self.click_pin], self.click_callback)
            if self.back_pin:
                if self.analog_range_back_pin is not None:
                    try:
                        p_min, p_max = map(
                            float, self.analog_range_back_pin.split(','))
                    except Exception:
                        raise config.error(
                            "Unable to parse analog_range_back_pin")
                    self.buttons.register_adc_button_push(
                        self.back_pin, p_min, p_max, self.analog_pullup,
                        self.back_callback)
                else:
                    self.buttons.register_button_push(
                        self.back_pin, self.back_callback)
            if self.up_pin:
                if self.analog_range_up_pin is not None:
                    try:
                        p_min, p_max = map(
                            float, self.analog_range_up_pin.split(','))
                    except Exception:
                        raise config.error(
                            "Unable to parse analog_range_up_pin")
                    self.buttons.register_adc_button_push(
                        self.up_pin, p_min, p_max, self.analog_pullup,
                        self.up_callback)
                else:
                    self.buttons.register_button_push(
                        self.up_pin, self.up_callback)
            if self.down_pin:
                if self.analog_range_down_pin is not None:
                    try:
                        p_min, p_max = map(
                            float, self.analog_range_down_pin.split(','))
                    except Exception:
                        raise config.error(
                            "Unable to parse analog_range_down_pin")
                    self.buttons.register_adc_button_push(
                        self.down_pin, p_min, p_max, self.analog_pullup,
                        self.down_callback)
                else:
                    self.buttons.register_button_push(
                        self.down_pin, self.down_callback)
            if self.kill_pin:
                if self.analog_range_kill_pin is not None:
                    try:
                        p_min, p_max = map(
                            float, self.analog_range_kill_pin.split(','))
                    except Exception:
                        raise config.error(
                            "Unable to parse analog_range_kill_pin")
                    self.buttons.register_adc_button_push(
                        self.kill_pin, p_min, p_max, self.analog_pullup,
                        self.kill_callback)
                else:
                    self.buttons.register_button_push(
                        self.kill_pin, self.kill_callback)

        # Load local config file in same directory as current module
        self.load_config(os.path.dirname(__file__), 'menu.cfg')
        # Load items from main config
        self.load_menuitems(config)
        # Load defaults from main config
        self.load_defaults(config)
        # Load menu root
        self.root = self.lookup_menuitem(self._root)
        # send init event
        self.send_event('init', self)

    def handle_ready(self):
        # start timer
        reactor = self.printer.get_reactor()
        reactor.register_timer(self.timer_event, reactor.NOW)

    def timer_event(self, eventtime):
        self.timeout_idx = (self.timeout_idx + 1) % 10  # 0.1*10 = 1s
        if self.timeout_idx == 0:
            self.timeout_check(eventtime)
        # check press
        if self._last_click_press > 0:
            diff = eventtime - self._last_click_press
            if self._last_click_state == 0 and diff >= LONG_PRESS_DURATION:
                # long click
                self._last_click_press = 0
                self._last_click_state = 0
                self._click_callback(eventtime, 'longpress')
            elif self._last_click_state == 1 and diff <= LONG_PRESS_DURATION:
                # short click
                self._last_click_press = 0
                self._last_click_state = 0
                self._click_callback(eventtime, 'press')
        return eventtime + TIMER_DELAY

    def timeout_check(self, eventtime):
        if (self.is_running() and self.timeout > 0
                and isinstance(self.root, MenuContainer)):
            if self.timer >= self.timeout:
                self.exit()
            else:
                self.timer += 1
        else:
            self.timer = 0

    def _action_send_event(self, name, event, *args):
        self.send_event("%s:%s" % (str(name), str(event)), *args)
        return ""

    def send_event(self, event, *args):
        return self.printer.send_event("menu:" + str(event), *args)

    def is_running(self):
        return self.running

    def begin(self, eventtime):
        self.menustack = []
        self.top_row = 0
        self.timer = 0
        if isinstance(self.root, MenuContainer):
            # send begin event
            self.send_event('begin', self)
            self.update_context(eventtime)
            if isinstance(self.root, MenuContainer):
                self.root.init_selection()
            self.root.populate()
            self.stack_push(self.root)
            self.running = True
            return
        elif self.root is not None:
            logging.error("Invalid root, menu stopped!")
        self.running = False

    def get_status(self, eventtime):
        return {
            'timeout': self.timeout,
            'running': self.running,
            'rows': self.rows,
            'cols': self.cols,
            'default': dict(self.defaults)
        }

    def get_context(self, cxt=None):
        context = dict(self.context)
        if isinstance(cxt, dict):
            context.update(cxt)
        return context

    def update_context(self, eventtime):
        # menu default jinja2 context
        _tpl = self.gcode_macro.create_template("update_context", "")
        self.context = {
            'printer': _tpl.create_status_wrapper(eventtime),
            'menu': {
                'eventtime': eventtime,
                'back': self._action_back,
                'exit': self._action_exit,
                'send_event': self._action_send_event,
                'set_default': self._action_set_default,
                'reset_defaults': self._action_reset_defaults
            }
        }

    def _action_set_default(self, name, value):
        if name in self.defaults:
            configfile = self.printer.lookup_object('configfile')
            self.defaults[name] = value
            self._defaults_revision += 1
            configfile.set('menu', 'default_' + str(name), value)
            configfile.set(
                'menu', 'defaults_revision', self._defaults_revision)
        else:
            logging.error("Unknown menu default: '%s'" % str(name))
        return ""

    def _action_reset_defaults(self):
        configfile = self.printer.lookup_object('configfile')
        configfile.remove_section('menu')
        self._defaults_revision += 1
        configfile.set(
            'menu', 'defaults_revision', self._defaults_revision)
        return ""

    def stack_push(self, container):
        if not isinstance(container, MenuContainer):
            raise error("Wrong type, expected MenuContainer")
        top = self.stack_peek()
        if top is not None:
            if isinstance(top, MenuList):
                top.run_script('leave')
        if isinstance(container, MenuList):
            container.run_script('enter')
        if not container.is_editing():
            container.update_items()
            container.init_selection()
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
                    top.init_selection()
                if isinstance(container, MenuList):
                    container.run_script('leave')
                if isinstance(top, MenuList):
                    top.run_script('enter')
            else:
                if isinstance(container, MenuList):
                    container.run_script('leave')
        return container

    def stack_size(self):
        return len(self.menustack)

    def stack_peek(self, lvl=0):
        container = None
        if self.stack_size() > lvl:
            container = self.menustack[self.stack_size() - lvl - 1]
        return container

    def render(self, eventtime):
        lines = []
        self.update_context(eventtime)
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            container.heartbeat(eventtime)
            content, viewport_row = container.render_container(eventtime)
            if viewport_row is not None:
                while viewport_row >= (self.top_row + self.rows):
                    self.top_row += 1
                while viewport_row < self.top_row and self.top_row > 0:
                    self.top_row -= 1
            else:
                self.top_row = 0
            rows = self.aslatin(content).splitlines()
            for row in range(0, self.rows):
                try:
                    text = self.stripliterals(rows[self.top_row + row])
                except IndexError:
                    text = ""
                lines.append(text.ljust(self.cols))
        return lines

    def screen_update_event(self, eventtime):
        # screen update
        if self.is_running():
            self.lcd_chip.clear()
            for y, line in enumerate(self.render(eventtime)):
                self.display.draw_text(0, y, line, eventtime)
            self.lcd_chip.flush()
            return eventtime + MENU_UPDATE_DELAY
        else:
            return 0

    def up(self, fast_rate=False):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            current = container.selected_item()
            if isinstance(current, MenuInput) and current.is_editing():
                current.dec_value(fast_rate)
            else:
                container.select_prev()

    def down(self, fast_rate=False):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            current = container.selected_item()
            if isinstance(current, MenuInput) and current.is_editing():
                current.inc_value(fast_rate)
            else:
                container.select_next()

    def _action_back(self, force=False):
        self.back(force)
        return ""

    def back(self, force=False):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            current = container.selected_item()
            if isinstance(current, MenuInput) and current.is_editing():
                if force is True:
                    current.stop_editing()
                else:
                    return
            parent = self.stack_peek(1)
            if isinstance(parent, MenuContainer):
                self.stack_pop()
                index = parent.index_of(container, True)
                parent.select_at(index)
            else:
                self.stack_pop()
                self.running = False

    def _action_exit(self, force=False):
        self.exit(force)
        return ""

    def exit(self, force=False):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            current = container.selected_item()
            if (not force and isinstance(current, MenuInput)
                    and current.is_editing()):
                return
            if isinstance(container, MenuList):
                container.run_script('leave')
            self.send_event('exit', self)
            self.running = False

    def push_container(self, menu):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            if (isinstance(menu, MenuContainer)
                    and not container.is_editing()
                    and menu is not container):
                self.stack_push(menu)
                return True
        return False

    def press(self, event='press'):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            current = container.selected_item()
            if isinstance(current, MenuContainer):
                self.stack_push(current)
            elif isinstance(current, MenuCommand):
                current.run_script(event)

    def queue_gcode(self, script):
        if not script:
            return
        if not self.gcode_queue:
            reactor = self.printer.get_reactor()
            reactor.register_callback(self.dispatch_gcode)
        self.gcode_queue.append(script)

    def dispatch_gcode(self, eventtime):
        while self.gcode_queue:
            script = self.gcode_queue[0]
            try:
                self.gcode.run_script(script)
            except Exception:
                logging.exception("Script running error")
            self.gcode_queue.pop(0)

    def menuitem_from(self, config):
        if isinstance(config, dict):
            config = MenuConfig(dict(config))
        return self.aschoice(
            config, 'type', menu_items)(self, config)

    def add_menuitem(self, name, menu):
        if name in self.menuitems:
            logging.info(
                "Declaration of '%s' hides "
                "previous menuitem declaration" % (name,))
        self.menuitems[name] = menu

    def lookup_menuitem(self, name, default=sentinel):
        if name is None:
            return None
        if name in self.menuitems:
            return self.menuitems[name]
        if default is sentinel:
            raise self.printer.config_error(
                "Unknown menuitem '%s'" % (name,))
        return default

    def lookup_names(self, prefix):
        if prefix and not prefix.endswith(' '):
            prefix = prefix + ' '
        names = [n for n in self.menuitems
                 if n.startswith(prefix) and ' ' not in n[len(prefix):]]
        return names

    def load_config(self, *args):
        cfg = None
        filename = os.path.join(*args)
        try:
            cfg = self.pconfig.read_config(filename)
        except Exception:
            raise self.printer.config_error(
                "Cannot load config '%s'" % (filename,))
        if cfg:
            self.load_menuitems(cfg)
            self.load_defaults(cfg)
        return cfg

    def load_menuitems(self, config):
        for cfg in config.get_prefix_sections('menu '):
            item = self.menuitem_from(cfg)
            self.add_menuitem(item.ns, item)

    def load_defaults(self, config):
        if config.has_section('menu'):
            cfg = config.getsection('menu')
            # load revision
            self._defaults_revision = self.asint(
                cfg.get('defaults_revision', '0'), 0)
            # load default records
            prefix = 'default_'
            for option in cfg.get_prefix_options(prefix):
                try:
                    self.defaults[option[len(prefix):]] = ast.literal_eval(
                        cfg.get(option))
                except ValueError:
                    raise cfg.error(
                        "Option '%s' in '%s' is not a valid literal" % (
                            option, cfg.get_name()))

    # buttons & encoder callbacks
    def encoder_cw_callback(self, eventtime):
        fast_rate = ((eventtime - self._last_encoder_cw_eventtime)
                     <= self._encoder_fast_rate)
        self._last_encoder_cw_eventtime = eventtime
        self.up(fast_rate)

    def encoder_ccw_callback(self, eventtime):
        fast_rate = ((eventtime - self._last_encoder_ccw_eventtime)
                     <= self._encoder_fast_rate)
        self._last_encoder_ccw_eventtime = eventtime
        self.down(fast_rate)

    def click_callback(self, eventtime, state):
        if self.click_pin:
            if state:
                self._last_click_press = eventtime  # pressed
            elif self._last_click_press > 0:
                self._last_click_state = 1  # released

    def _click_callback(self, eventtime, event):
        if self.is_running():
            self.press(event)
        else:
            # lets start and populate the menu items
            self.begin(eventtime)

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

    # manager helper methods
    @classmethod
    def stripliterals(cls, s):
        """Literals are beginning or ending by the double or single quotes"""
        s = str(s)
        if s.startswith('"') or s.startswith("'"):
            s = s[1:]
        if s.endswith('"') or s.endswith("'"):
            s = s[:-1]
        return s

    @classmethod
    def asliteral(cls, s):
        """Enclose text by the single quotes"""
        return "'" + str(s) + "'"

    @classmethod
    def aslatin(cls, s):
        if isinstance(s, str):
            return s
        elif isinstance(s, unicode):
            return unicode(s).encode('latin-1', 'ignore')
        else:
            return str(s)

    @classmethod
    def asflatline(cls, s):
        return ''.join(cls.aslatin(s).splitlines())

    @classmethod
    def asbool(cls, s):
        if isinstance(s, (bool, int, float)):
            return bool(s)
        elif cls.isfloat(s):
            return bool(cls.asfloat(s))
        s = str(s).strip()
        return s.lower() in ('y', 'yes', 't', 'true', 'on', '1')

    @classmethod
    def asint(cls, s, default=sentinel):
        if isinstance(s, (int, float)):
            return int(s)
        s = str(s).strip()
        prefix = s[0:2]
        try:
            if prefix == '0x':
                return int(s, 16)
            elif prefix == '0b':
                return int(s, 2)
            else:
                return int(float(s))
        except ValueError as e:
            if default is not sentinel:
                return default
            raise e

    @classmethod
    def asfloat(cls, s, default=sentinel):
        if isinstance(s, (int, float)):
            return float(s)
        s = str(s).strip()
        try:
            return float(s)
        except ValueError as e:
            if default is not sentinel:
                return default
            raise e

    @classmethod
    def isfloat(cls, value):
        try:
            float(value)
            return True
        except ValueError:
            return False

    @classmethod
    def lines_aslist(cls, value, default=[]):
        if isinstance(value, str):
            value = filter(None, [x.strip() for x in value.splitlines()])
        try:
            return list(value)
        except Exception:
            logging.exception("Lines as list parsing error")
            return list(default)

    @classmethod
    def words_aslist(cls, value, sep=',', default=[]):
        if isinstance(value, str):
            value = filter(None, [x.strip() for x in value.split(sep)])
        try:
            return list(value)
        except Exception:
            logging.exception("Words as list parsing error")
            return list(default)

    @classmethod
    def aslist(cls, value, flatten=True, default=[]):
        values = cls.lines_aslist(value)
        if not flatten:
            return values
        result = []
        for value in values:
            subvalues = cls.words_aslist(value, sep=',')
            result.extend(subvalues)
        return result

    @classmethod
    def aschoice(cls, config, option, choices, default=sentinel):
        if default is not sentinel:
            c = config.get(option, default)
        else:
            c = config.get(option)
        if c not in choices:
            raise error("Choice '%s' for option '%s'"
                        " is not a valid choice" % (c, option))
        return choices[c]
