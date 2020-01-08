# -*- coding: utf-8 -*-
# Support for display menu (v2.0)
#
# Copyright (C) 2019 Janar Sööt <janar.soot@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import os, logging, re, ast
from string import Template


class error(Exception):
    pass


class sentinel:
    pass


# Experimental
class MenuRenderBuffer(object):
    """Helper class for callback view render buffer"""
    def __init__(self, cols, rows):
        self.cols = cols
        self.rows = rows
        self.buffer = [" " * self.cols] * self.rows
        self.position = {
            'col': 0,
            'row': 0
        }
        self.dirty = False

    def is_dirty(self):
        return self.dirty

    def set_pos(self, col, row):
        if not (0 <= col < self.cols):
            raise IndexError
        if not (0 <= row < self.rows):
            raise IndexError
        self.position['col'] = col
        self.position['row'] = row

    def get_pos(self):
        return self.position

    def within_limits_pos(self):
        if self.position['col'] >= self.cols:
            self.position['col'] = 0
            self.position['row'] += 1
        if self.position['row'] >= self.rows:
            self.position['row'] = 0

    def write(self, text, col=None, row=None):
        if col is None:
            col = self.position['col']
        if row is None:
            row = self.position['row']

        if col >= self.cols:
            raise IndexError
        if row >= self.rows:
            raise IndexError

        old_line = self.buffer[row]
        new_line = old_line[:col] + text + old_line[col + len(text):]
        self.buffer[row] = new_line[:self.cols]
        self.position = {
            'col': col + len(text),
            'row': row
        }
        self.dirty = True

    def clear(self):
        self.set_pos(0, 0)
        self.buffer = [" " * self.cols] * self.rows
        self.dirty = False

    def get_buffer(self):
        return list(self.buffer)


class MenuConfig(dict):
    """Wrapper for dict to emulate configfile get_name for namespace.
        __ns - item namespace key, used in item relative paths
        $__id - generated id text variable
    """
    def get_name(self):
        __id = '__menuitem_' + hex(id(self)).lstrip("0x").rstrip("L")
        return Template('menu ' + self.get(
            '__ns', __id)).safe_substitute(__id=__id)

    def get_prefix_options(self, prefix):
        return [o for o in self.keys() if o.startswith(prefix)]


class MenuItem(object):
    def __init__(self, manager, config):
        self._manager = manager
        self._use_blinking = manager.asbool(
            config.get('use_blinking', 'False'))
        self._blinking_mask = config.get('blinking_mask', '')
        self._use_cursor = manager.asbool(config.get('use_cursor', 'True'))
        self.cursor = config.get('cursor', '|')
        self._width = manager.asint(config.get('width', '0'))
        self._scroll = manager.asbool(config.get('scroll', 'False'))
        self._enable_tpl = manager.gcode_macro.load_template(
            config, 'enable', 'True')
        self._name_tpl = manager.gcode_macro.load_template(
            config, 'name')
        # item namespace - used in item relative paths
        self._ns = " ".join(config.get_name().split(' ')[1:])
        self._last_heartbeat = None
        self.__scroll_offs = 0
        self.__scroll_diff = 0
        self.__scroll_dir = None
        self.__last_state = True
        self._command_queue = []
        # if scroll is enabled and width is not specified then
        # display width is used and adjusted by cursor size
        if self._scroll and not self._width:
            self._width = self.manager.cols - len(self._cursor)
        # clamp width
        self._width = min(
            self.manager.cols - len(self._cursor), max(0, self._width))
        # load scripts
        self._script_tpls = {}
        prfx = 'script_'
        for o in config.get_prefix_options(prfx):
            script = config.get(o, '')
            name = o[len(prfx):]
            _handle = getattr(self, "preprocess_script_" + name, None)
            if callable(_handle):
                script = _handle(script)
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
        # add default 'me' props
        context.update({
            'me': {
                'is_editing': self.is_editing(),
                'width': self._width,
                'ns': self.ns
            },
            'run': self._command_wrapper()
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
        def _blinking(_text, _bstate):
            if (self._use_blinking or not self._use_cursor) and not _bstate:
                s = ""
                for i, t in enumerate(_text):
                    s += (t if i < len(self._blinking_mask)
                          and self._blinking_mask[i] == '+' else ' ')
                return s
            return _text
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
        # blinker & cursor
        if selected and not self.is_editing():
            s = (self.cursor if self._use_cursor else '') + _blinking(
                s, self.manager.blinking_slow_state)
        elif selected and self.is_editing():
            s = ('*' if self._use_cursor else '') + _blinking(
                s, self.manager.blinking_fast_state)
        elif self._use_cursor:
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
            "item:%s:%s" % (self.ns, str(event)), *args)

    def get_script(self, name):
        if name in self._script_tpls:
            return self._script_tpls[name]
        return None

    def run_script(self, name, cxt=None, render_only=False, event_name=None):
        def _prevent():
            _prevent.state = True
            return ''

        def _before():
            _before.state = True
            return ''

        def _log():
            _log.state = True
            return ''

        def _get_template(n, from_ns='.'):
            _source = self.manager.lookup_menuitem(self.ns_prefix(from_ns))
            script = _source.get_script(n)
            if script is None:
                raise error(
                    "{}: script '{}' not found".format(_source.ns, str(n)))
            return script.template
        result = ""
        # init context & commands queue
        context = self.get_context(cxt)
        _prevent.state = False
        _before.state = False
        _log.state = False
        if name in self._script_tpls:
            context.update({
                'script': {
                    'name': event_name if event_name is not None else name,
                    'prevent_default': _prevent,
                    'run_before_gcode': _before,
                    'log_gcode': _log,
                    'by_name': _get_template
                }
            })
            result = self._script_tpls[name].render(context)
        # process result
        if not render_only:
            if _before.state is True:
                # handle queued commands before gcode
                self.handle_commands()
            if _log.state is True:
                # log result gcode
                logging.info("item:{} -> gcode: {}".format(self.ns, result))
            # run result as gcode
            self.manager.queue_gcode(result)
            # default behaviour
            if not _prevent.state:
                _handle = getattr(self, "handle_script_" + name, None)
                if callable(_handle):
                    _handle()
            if _before.state is False:
                # handle queued commands after gcode
                self.handle_commands()
        return result

    def handle_commands(self, **kwargs):
        for name, scope, args in self.command_queue_iter():
            _source = None
            if scope == 'me' or scope == 'self':
                _source = self
            elif scope == 'container':
                _source = self.manager.stack_peek()
            elif scope == 'selected':
                container = self.manager.stack_peek()
                if isinstance(container, MenuSelector):
                    _source = container.selected_item()
            elif scope == 'menu':
                _source = self.manager

            if _source is None:
                self.command_error(
                    name, None, "unknown command scope '%s'" % (scope,), *args)
                continue
            _handle = getattr(_source, "handle_command_" + name, None)
            if callable(_handle):
                try:
                    _handle(*args, **kwargs)
                except Exception as e:
                    self.command_error(name, scope, e, *args)
            else:
                self.command_error(name, scope, "unknown command", *args)

    def command_error(self, name, scope, msg, *args):
        if scope is None:
            logging.error("'{}' -> {}({}): {}".format(
                self.ns, name, ','.join(map(str, args[0:])), msg))
        else:
            logging.error("'{}' [{}] -> {}({}): {}".format(
                self.ns, scope, name, ','.join(map(str, args[0:])), msg))

    def _command_wrapper(self):
        self._command_queue = []

        # queue wrapper for command call, encapsulate __getattr__
        class __Command__(object):
            def __init__(me, scope):
                me.scope = scope

            def __getattr__(me, name):
                def _append(*args):
                    self._command_queue.append(
                        (len(self._command_queue), me.scope, name, list(args)))
                    return ''

                if me.scope == "self" and name == "me":
                    return __Command__('me')
                elif me.scope == "self" and name == "container":
                    return __Command__('container')
                elif me.scope == "self" and name == "selected":
                    return __Command__('selected')
                elif me.scope == "self" and name == "menu":
                    return __Command__('menu')
                else:
                    return _append
        return __Command__('self')

    def command_queue_iter(self):
        for cmd in self._command_queue:
            i, scope, name, args = cmd
            # remove from command list
            self._command_queue.remove(cmd)
            yield (name, scope, args)
        else:
            raise StopIteration

    # commands
    def handle_command_emit(self, name, *args):
        self.manager.send_event("command:" + str(name), self, *args)

    def handle_command_log(self, msg):
        logging.info("item:{} -> {}".format(self.ns, msg))

    @property
    def cursor(self):
        return self._cursor

    @cursor.setter
    def cursor(self, value):
        self._cursor = str(value)[:1]

    @property
    def manager(self):
        return self._manager

    @property
    def ns(self):
        return self._ns


class MenuContainer(MenuItem):
    """Menu container abstract class.
    """
    def __init__(self, manager, config):
        if type(self) is MenuContainer:
            raise error(
                'Abstract MenuContainer cannot be instantiated directly')
        super(MenuContainer, self).__init__(manager, config)
        self.cursor = config.get('cursor', '>')
        self._autorun = manager.asbool(config.get('autorun', 'False'))
        self._permit_timeout = manager.asbool(
            config.get('permit_timeout', 'True'))
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
    def is_homed(self):
        return True

    # overload
    def is_accepted(self, item):
        return isinstance(item, MenuItem)

    def is_timeout_permitted(self):
        return self._permit_timeout

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
        elif isinstance(item, MenuItem):
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
            elif isinstance(item, MenuItem):
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
            if isinstance(item, (MenuItem)):
                item.init()
            if isinstance(item, (MenuContainer)):
                item.add_parents(self._parents)
                item.add_parents(self)
                item.assert_recursive_relation()
                item.populate_items()
            if index is None:
                self._allitems.append((item, name))
            else:
                self._allitems.insert(index, (item, name))

    # overload
    def _populate_items(self):
        pass

    def populate_items(self):
        self._allitems = []  # empty list
        for name in self._names_aslist():
            self._insert_item(name)
        # populate successor items
        self._populate_items()
        # send populate event
        self.send_event('populate', self)
        self.update_items()

    def update_items(self):
        _a = [(item, name) for item, name in self._allitems
              if item.is_enabled()]
        self._items, self._names = zip(*_a) or ([], [])

    # override
    def render_content(self, eventtime):
        return ("", None)

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

    def __getitem__(self, key):
        return self._items[key]

    @property
    def autorun(self):
        return self._autorun


class MenuSelector(MenuContainer):
    """Menu selector abstract class.
    """
    def __init__(self, manager, config):
        if type(self) is MenuSelector:
            raise error(
                'Abstract MenuSelector cannot be instantiated directly')
        super(MenuSelector, self).__init__(manager, config)
        self.__initial = manager.asint(config.get('initial', 0), None)
        self.__selected = None

    # selector methods
    def init_selection(self):
        self.select_at(self.initial)

    def select_at(self, index):
        self.__selected = index
        # select element
        item = self.selected_item()
        if isinstance(item, MenuItem):
            item.select()
        return item

    def select_item(self, needle):
        if isinstance(needle, MenuItem):
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

    def is_homed(self):
        return self.initial == self.selected

    # commands
    def handle_command_reset(self):
        self.stop_editing()
        self.init_selection()

    def handle_command_select(self, index):
        self.select_at(index)

    @property
    def initial(self):
        return self.__initial

    @property
    def selected(self):
        return self.__selected


class MenuInput(MenuItem):
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

    def get_value(self):
        return self._input_value

    def heartbeat(self, eventtime):
        super(MenuInput, self).heartbeat(eventtime)
        if (self._is_dirty is True
                and self.__last_change is not None
                and self._input_value is not None
                and (eventtime - self.__last_change) > 0.250):
            self.run_script('change')
            self._is_dirty = False

    def eval_enable(self):
        context = super(MenuInput, self).get_context()
        return self.manager.asbool(self._enable_tpl.render(context))

    def get_context(self, cxt=None):
        context = super(MenuInput, self).get_context(cxt)
        context['me'].update({
            'input': self.manager.asfloat(
                self._eval_value() if self._input_value is None
                else self._input_value)
        })
        return context

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

    # commands
    def handle_command_start_editing(self):
        self.start_editing()

    def handle_command_stop_editing(self):
        self.stop_editing()


# Experimental
class MenuCallback(MenuContainer):
    def __init__(self, manager, config):
        super(MenuCallback, self).__init__(manager, config)
        self._press_callback = None
        self._back_callback = None
        self._up_callback = None
        self._down_callback = None
        self._render_callback = None
        self._enter_callback = None
        self._leave_callback = None

    # buffer factory
    def create_buffer(self, cols=None, rows=None):
        if cols is None:
            cols = self.manager.cols
        if rows is None:
            rows = self.manager.rows
        return MenuRenderBuffer(cols, rows)

    # register callbacks
    def register_press_callback(self, callback):
        self._press_callback = callback

    def register_back_callback(self, callback):
        self._back_callback = callback

    def register_up_callback(self, callback):
        self._up_callback = callback

    def register_down_callback(self, callback):
        self._down_callback = callback

    # render callback must return tuple of rendered content, active row
    def register_render_callback(self, callback):
        self._render_callback = callback

    def register_enter_callback(self, callback):
        self._enter_callback = callback

    def register_leave_callback(self, callback):
        self._leave_callback = callback

    def render_content(self, eventtime):
        if callable(self._render_callback):
            return self._render_callback(eventtime)
        super(MenuCallback, self).render_content(eventtime)

    # handle callback calls
    def handle_press(self, event):
        if callable(self._press_callback):
            self._press_callback(event)

    def handle_back(self, force=False):
        if callable(self._back_callback):
            self._back_callback(force)

    def handle_up(self, fast_rate=False):
        if callable(self._up_callback):
            self._up_callback(fast_rate)

    def handle_down(self, fast_rate=False):
        if callable(self._down_callback):
            self._down_callback(fast_rate)

    def handle_enter(self):
        if callable(self._enter_callback):
            self._enter_callback()

    def handle_leave(self):
        if callable(self._leave_callback):
            self._leave_callback()


class MenuView(MenuSelector):
    def __init__(self, manager, config):
        # immutable list of items, must be defined before super
        self.immutable_items = []
        super(MenuView, self).__init__(manager, config)
        prfx = 'popup_'
        self.popup_menus = {o[len(prfx):]: config.get(o)
                            for o in config.get_prefix_options(prfx)}
        self._popup_menus = {}
        self.runtime_items = config.get('items', '')  # mutable list of items
        self._runtime_index_start = 0

    def preprocess_script_render(self, script):
        def _preprocess(matched):
            fullmatch = matched.group(0)  # The entire match
            m = matched.group(1)
            name = matched.group(2)
            if m == "back":
                item = self.manager.menuitem_from({
                    'type': 'item',
                    'name': self.manager.asliteral(name),
                    'cursor': '>',
                    'script_shortpress': '{run.menu.back()}'
                })
                # add item from content to immutable list of items
                self.immutable_items.append(item)
                return self._placeholder(item.ns)
            elif m == "item":
                # add item from content to immutable list of items
                self.immutable_items.append(name)
                return self._placeholder(name)
            else:
                logging.error(
                    "Unknown placeholder {} in {}:script_render".format(
                        fullmatch, self.ns))
                return ""
        return re.sub(r"<\?(item|back):\s*(\S.*?)\s*\?>",
                      _preprocess, script, 0, re.MULTILINE)

    def _placeholder(self, s):
        return "<?name:{}?>".format(s)

    def _names_aslist(self):
        return self.immutable_items

    def _lookup_item(self, item):
        if isinstance(item, dict):
            item = self.manager.menuitem_from(item)
        return super(MenuView, self)._lookup_item(item)

    def _populate_extra_items(self):
        # popup menu item
        self._popup_menus = dict()
        for key in self.popup_menus:
            menu = self.manager.lookup_menuitem(self.popup_menus[key])
            if isinstance(menu, MenuContainer):
                menu.assert_recursive_relation(self._parents)
                menu.populate_items()
                self._popup_menus[key] = menu

    def _populate_items(self):
        super(MenuView, self)._populate_items()
        # mark the end of immutable list of items
        # and start of runtime mutable list of items
        self._runtime_index_start = len(self._allitems)
        # populate runtime list of items
        for name in self.manager.lines_aslist(self.runtime_items):
            self._insert_item(name)
        # populate extra menu items
        self._populate_extra_items()

    def insert_item(self, s, index=None):
        # allow runtime items only after immutable list of items
        if index is None:
            super(MenuView, self).insert_item(s)
        else:
            super(MenuView, self).insert_item(self._runtime_index_start+index)

    def get_context(self, cxt=None):
        context = super(MenuView, self).get_context(cxt)
        context['me'].update({
            'popup_names': self._popup_menus.keys(),
            'runtime_names': [
                n for i, n in self._allitems[
                    self._runtime_index_start:] if n in self._names
            ]
        })
        return context

    def render_content(self, eventtime):
        content = ""
        rows = []
        selected_row = None
        try:
            content = self.run_script("render", render_only=True)
            # postprocess content
            for line in self.manager.lines_aslist(content):
                s = ""
                for i, text in enumerate(re.split(
                        r"<\?name:\s*(\S.*?)\s*\?>", line)):
                    if i & 1 == 0:
                        s += text
                    else:
                        idx = self.index_of(text)
                        if idx is not None:
                            current = self[idx]
                            selected = (idx == self.selected)
                            if selected:
                                current.heartbeat(eventtime)
                                selected_row = len(rows)
                            s += str(current.render_name(selected))
                if s.strip():
                    rows.append(s)
                    # logging.info("{}".format(s))
        except Exception:
            logging.exception('View rendering error')
        return ("\n".join(rows), selected_row)

    # commands
    def handle_command_popup(self, name):
        if name in self._popup_menus:
            self.manager.push_container(self._popup_menus[name])
        else:
            raise error("{}: menu '{}' not found".format(self.ns, name))


class MenuVSDView(MenuView):
    def __init__(self, manager, config):
        super(MenuVSDView, self).__init__(manager, config)

    def _populate_items(self):
        super(MenuVSDView, self)._populate_items()
        sdcard = self.manager.objs.get('virtual_sdcard')
        if sdcard is not None:
            files = sdcard.get_file_list()
            for fname, fsize in files:
                gcode = [
                    'M23 /%s' % str(fname)
                ]
                self.insert_item(self.manager.menuitem_from({
                    'type': 'item',
                    'name': self.manager.asliteral(fname),
                    'cursor': '+',
                    'script_shortpress': "\n".join(gcode),
                    'scroll': True
                }))


menu_items = {
    'item': MenuItem,
    'input': MenuInput,
    'view': MenuView,
    'callback': MenuCallback,
    'vsdview': MenuVSDView
}

MENU_UPDATE_DELAY = .100
TIMER_DELAY = .100
LONG_PRESS_DURATION = 0.800
DBL_PRESS_DURATION = 0.300
#  Blinking sequence per 0.100 ->  1 - on, 0 - blank
BLINKING_FAST_SEQUENCE = (1, 1, 1, 1, 0, 0, 0, 0)
BLINKING_SLOW_SEQUENCE = (1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0)


class MenuManager:
    def __init__(self, config, display):
        self.running = False
        self.menuitems = {}
        self.menustack = []
        self._autorun = False
        self._first_run = True
        self.top_row = 0
        self.blinking_fast_state = True
        self.blinking_slow_state = True
        self._defaults_revision = 0
        self.blinking_fast_idx = 0
        self.blinking_slow_idx = 0
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
        self.root_names = config.get('menu_root', '__main')
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
        self._click_counter = 0
        self.analog_pullup = config.getfloat(
            'analog_pullup_resistor', 4700., above=0.)
        self._encoder_fast_rate = config.getfloat(
            'encoder_fast_rate', .03, above=0.)
        self._last_encoder_cw_eventtime = 0
        self._last_encoder_ccw_eventtime = 0
        # printer objects
        self.buttons = self.printer.try_load_module(config, "buttons")
        self.gcode_macro = self.printer.try_load_module(config, 'gcode_macro')
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
        # send init event
        self.send_event('init', self)

    def handle_ready(self):
        # start timer
        reactor = self.printer.get_reactor()
        reactor.register_timer(self.timer_event, reactor.NOW)

    def timer_event(self, eventtime):
        # take next from sequence
        self.blinking_fast_idx = (
            (self.blinking_fast_idx + 1) % len(BLINKING_FAST_SEQUENCE)
        )
        self.blinking_slow_idx = (
            (self.blinking_slow_idx + 1) % len(BLINKING_SLOW_SEQUENCE)
        )
        self.timeout_idx = (self.timeout_idx + 1) % 10  # 0.1*10 = 1s
        self.blinking_fast_state = (
            not not BLINKING_FAST_SEQUENCE[self.blinking_fast_idx]
        )
        self.blinking_slow_state = (
            not not BLINKING_SLOW_SEQUENCE[self.blinking_slow_idx]
        )
        if self.timeout_idx == 0:
            self.timeout_check(eventtime)
        # check press
        if self._last_click_press > 0:
            diff = eventtime - self._last_click_press
            if self._click_counter > 1:
                # dbl click
                self._last_click_press = 0
                self._click_counter = 0
                self._click_callback(eventtime, 'dblpress')
            elif self._click_counter == 0 and diff >= LONG_PRESS_DURATION:
                # long click
                self._last_click_press = 0
                self._click_counter = 0
                self._click_callback(eventtime, 'longpress')
            elif self._click_counter == 1 and diff >= DBL_PRESS_DURATION:
                # short click
                self._last_click_press = 0
                self._click_counter = 0
                self._click_callback(eventtime, 'shortpress')
        return eventtime + TIMER_DELAY

    def timeout_check(self, eventtime):
        permit_check = False
        if (self.is_running() and self.timeout > 0
                and isinstance(self.root, MenuContainer)):
            container = self.stack_peek()
            if (isinstance(container, MenuContainer)
                    and container.is_timeout_permitted() is True):
                if container is self.root:
                    if not container.is_homed():
                        permit_check = True
                    elif not self._autorun:
                        permit_check = True
                else:
                    permit_check = True
        # check timeout
        if permit_check is True:
            if self.timer >= self.timeout:
                self.exit()
            else:
                self.timer += 1
        else:
            self.timer = 0

    def restart(self, root=None, force_exit=True):
        if self.is_running():
            self.exit(force_exit)
        self.load_root(root, True)

    def load_root(self, root=None, autorun=None):
        self.root = None
        if root is None:
            # find first enabled root from list
            for name in self.lines_aslist(self.root_names):
                item = self.lookup_menuitem(name)
                if item.is_enabled():
                    self.root = item
                    break
            if self.root is None:
                logging.error("No active root item found!")
        else:
            self.root = self.lookup_menuitem(root)

        if autorun is None and isinstance(self.root, MenuContainer):
            self._autorun = self.root.autorun
        else:
            self._autorun = not not autorun

    def register_object(self, obj, name=None, override=False):
        """Register an object with a "get_status" callback"""
        if obj is not None:
            if name is None:
                name = obj.__class__.__name__
            if override or name not in self.objs:
                self.objs[name] = obj

    def unregister_object(self, name):
        """Unregister an object from "get_status" callback list"""
        if name is not None:
            if not isinstance(name, str):
                name = name.__class__.__name__
            if name in self.objs:
                self.objs.pop(name)

    def after(self, starttime, callback, *args):
        """Helper method for reactor.register_callback.
        The callback will be executed once after the start time elapses.
        """
        def callit(eventtime):
            callback(eventtime, *args)
        reactor = self.printer.get_reactor()
        starttime = max(0., float(starttime))
        reactor.register_callback(callit, starttime)

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
            if isinstance(self.root, MenuSelector):
                self.root.init_selection()
            self.root.populate_items()
            self.stack_push(self.root)
            self.running = True
            return
        elif self.root is not None:
            logging.error("Invalid root, menu stopped!")
        self.running = False

    def get_status(self, eventtime):
        return {
            'eventtime': eventtime,
            'timeout': self.timeout,
            'autorun': self._autorun,
            'running': self.running,
            'blinking_fast': self.blinking_fast_state,
            'blinking_slow': self.blinking_slow_state,
            'rows': self.rows,
            'cols': self.cols,
            'default': dict(self.defaults),
            'action_set_default': self._action_set_default,
            'action_reset_defaults': self._action_reset_defaults
        }

    def get_context(self, cxt=None):
        context = dict(self.context)
        if isinstance(cxt, dict):
            context.update(cxt)
        return context

    def update_context(self, eventtime):
        # iterate menu objects
        objs = dict(self.objs)
        parameter = {}
        for name in objs.keys():
            try:
                if objs[name] is not None:
                    get_status = getattr(objs[name], "get_status", None)
                    if callable(get_status):
                        parameter[name] = get_status(eventtime)
                    else:
                        parameter[name] = {}
            except Exception:
                logging.exception("Parameter '%s' update error" % str(name))
        # menu default jinja2 context
        _tpl = self.gcode_macro.create_template("update_context", "")
        self.context = {
            'printer': _tpl.create_status_wrapper(eventtime),
            'menu_objects': parameter
        }

    def stack_push(self, container):
        if not isinstance(container, MenuContainer):
            raise error("Wrong type, expected MenuContainer")
        top = self.stack_peek()
        if top is not None:
            if isinstance(top, MenuView):
                top.run_script('leave')
            elif isinstance(top, MenuCallback):
                top.handle_leave()
        if isinstance(container, MenuView):
            container.run_script('enter')
        elif isinstance(container, MenuCallback):
            container.handle_enter()
        if not container.is_editing():
            container.update_items()
            if isinstance(container, MenuSelector):
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
                    if isinstance(top, MenuSelector):
                        top.init_selection()
                if isinstance(container, MenuView):
                    container.run_script('leave')
                elif isinstance(container, MenuCallback):
                    container.handle_leave()
                if isinstance(top, MenuView):
                    top.run_script('enter')
                elif isinstance(top, MenuCallback):
                    top.handle_enter()
            else:
                if isinstance(container, MenuView):
                    container.run_script('leave')
                elif isinstance(container, MenuCallback):
                    container.handle_leave()
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
            content, viewport_row = container.render_content(eventtime)
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
        # check first run and load root if needed
        if self._first_run:
            self.update_context(eventtime)
            if self.root is None:
                self.load_root()
            self._first_run = False
        # screen update
        if self.is_running():
            self.lcd_chip.clear()
            for y, line in enumerate(self.render(eventtime)):
                self.display.draw_text(0, y, line)
            self.lcd_chip.flush()
            return eventtime + MENU_UPDATE_DELAY
        elif not self.is_running() and self._autorun is True:
            # lets start and populate the menu items
            self.begin(eventtime)
            return eventtime + MENU_UPDATE_DELAY
        else:
            return 0

    def up(self, fast_rate=False):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            if isinstance(container, MenuSelector):
                current = container.selected_item()
                if isinstance(current, MenuInput) and current.is_editing():
                    current.dec_value(fast_rate)
                else:
                    container.select_prev()
            elif isinstance(container, MenuCallback):
                container.handle_up(fast_rate)

    def down(self, fast_rate=False):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            if isinstance(container, MenuSelector):
                current = container.selected_item()
                if isinstance(current, MenuInput) and current.is_editing():
                    current.inc_value(fast_rate)
                else:
                    container.select_next()
            elif isinstance(container, MenuCallback):
                container.handle_down(fast_rate)

    def back(self, force=False):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            if isinstance(container, MenuSelector):
                current = container.selected_item()
                if isinstance(current, MenuInput) and current.is_editing():
                    if force is True:
                        current.stop_editing()
                    else:
                        return
            elif isinstance(container, MenuCallback):
                if container.handle_back(force) is True:
                    return
            parent = self.stack_peek(1)
            if isinstance(parent, MenuContainer):
                self.stack_pop()
                if isinstance(parent, MenuSelector):
                    index = parent.index_of(container, True)
                    parent.select_at(index)
            else:
                self.stack_pop()
                self.running = False

    def exit(self, force=False):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            if isinstance(container, MenuSelector):
                current = container.selected_item()
                if (not force and isinstance(current, MenuInput)
                        and current.is_editing()):
                    return
            if isinstance(container, MenuView):
                container.run_script('leave')
            elif isinstance(container, MenuCallback):
                container.handle_leave()
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

    def press(self, event='shortpress'):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            if isinstance(container, MenuSelector):
                current = container.selected_item()
                if isinstance(current, MenuContainer):
                    self.stack_push(current)
                elif isinstance(current, MenuItem):
                    current.run_script(event)
                    current.run_script('press', event_name=event)
                else:
                    # current is None, no selection. passthru to container
                    container.run_script(event)
                    container.run_script('press', event_name=event)
            elif isinstance(container, MenuCallback):
                container.handle_press(event)

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

    def lookup_menuitems(self, prefix=None):
        if prefix is None:
            return list(self.menuitems.items())
        items = [(n, self.menuitems[n])
                 for n in self.menuitems if n.startswith(prefix + ' ')]
        if prefix in self.menuitems:
            return [(prefix, self.menuitems[prefix])] + items
        return items

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
                self._last_click_press = eventtime
            elif self._last_click_press > 0:
                diff = eventtime - self._last_click_press
                if diff < DBL_PRESS_DURATION:
                    self._click_counter += 1
                else:
                    self._click_counter = 1

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

    # get_status actions
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

    # commands
    def handle_command_back(self, force=False):
        self.back(force)

    def handle_command_exit(self, force=False):
        self.exit(force)

    # manager helper methods
    @classmethod
    def stripliterals(cls, s):
        """Literals are beginning or ending by the back-tick '`' (grave accent)
        character instead of double or single quotes. To escape a back-tick use
        a double back-tick."""
        s = str(s)
        if s.startswith('``') or s.startswith('`'):
            s = s[1:]
        if s.endswith('``') or s.endswith('`'):
            s = s[:-1]
        return s

    @classmethod
    def asliteral(cls, s):
        """Enclose text by the back-tick"""
        return '`' + str(s) + '`'

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
