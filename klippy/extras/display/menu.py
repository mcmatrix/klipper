# -*- coding: utf-8 -*-
# Support for display menu
#
# Copyright (C) 2019 Janar Sööt <janar.soot@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import os, logging, re
from string import Template


class error(Exception):
    pass


class sentinel:
    pass


# static class for cursor
class MenuCursor:
    NONE = ' '
    SELECT = '>'
    EDIT = '*'


# wrapper for dict to emulate configfile get_name for namespace
# __ns - item namespace, used in item relative paths
# $__id - variable is generated name for item
# internal usage
class MenuConfig(dict):
    def get_name(self):
        __id = 'menuitem' + hex(id(self)).lstrip("0x").rstrip("L")
        return Template('menu ' + self.get(
            '__ns', __id)).safe_substitute(__id=__id)


# internal usage
class MenuTemplateActions(object):
    def __init__(self):
        self.queue = []

    def __call__(self, item, n, **kwargs):
        _handle = getattr(item, "handle_action", None)
        if callable(_handle):
            for name, args in self.iter_pop(n):
                _handle(name, *args, **kwargs)

    def get_caller(self):
        self.queue = []

        # custom action caller, encapsulate __getattr__
        class __ActionCaller__(object):
            def __getattr__(me, name):
                def __append(*args):
                    self.queue.append(
                        (len(self.queue), name, list(args)))
                    return ''
                return __append
        return __ActionCaller__()

    def iter_pop(self, n):
        names = MenuHelper.words_aslist(n)
        # find matching actions
        if len(names) == 1 and names[0] == '*':
            matches = [t for t in self.queue]
        else:
            matches = [t for t in self.queue if t[1] in names]
        for match in matches:
            i, name, args = match
            # remove found match from action list
            self.queue.remove(match)
            # yield found action
            yield (name, args)
        else:
            raise StopIteration


# static class for type cast
class MenuHelper:
    @staticmethod
    def asliteral(s):
        s = str(s)
        if (s.startswith('"') and s.endswith('"')) or \
                (s.startswith("'") and s.endswith("'")):
            s = s[1:-1]
        return s

    @staticmethod
    def aslatin(s):
        if isinstance(s, str):
            return s
        elif isinstance(s, unicode):
            return unicode(s).encode('latin-1', 'ignore')
        else:
            return str(s)

    @staticmethod
    def asflatline(s):
        return ''.join(MenuHelper.aslatin(s).splitlines())

    @staticmethod
    def asbool(s, default=False):
        if s is None:
            return bool(default)
        elif isinstance(s, (bool, int, float)):
            return bool(s)
        elif MenuHelper.isfloat(s):
            return bool(MenuHelper.asfloat(s))
        s = str(s).strip()
        return s.lower() in ('y', 'yes', 't', 'true', 'on', '1')

    @staticmethod
    def asint(s, default=sentinel):
        if isinstance(s, (int, float)):
            return int(s)
        s = str(s).strip()
        return int(float(s)) if MenuHelper.isfloat(s) else (
            int(float(default)) if default is not sentinel else int(float(s)))

    @staticmethod
    def asfloat(s, default=sentinel):
        if isinstance(s, (int, float)):
            return float(s)
        s = str(s).strip()
        return float(s) if MenuHelper.isfloat(s) else (
            float(default) if default is not sentinel else float(s))

    @staticmethod
    def isfloat(value):
        try:
            float(value)
            return True
        except ValueError:
            return False

    @staticmethod
    def lines_aslist(value, default=[]):
        if isinstance(value, str):
            value = filter(None, [x.strip() for x in value.splitlines()])
        try:
            return list(value)
        except Exception:
            logging.exception("Lines as list parsing error")
            return list(default)

    @staticmethod
    def words_aslist(value, sep=',', default=[]):
        if isinstance(value, str):
            value = filter(None, [x.strip() for x in value.split(sep)])
        try:
            return list(value)
        except Exception:
            logging.exception("Words as list parsing error")
            return list(default)

    @staticmethod
    def aslist(value, flatten=True, default=[]):
        values = MenuHelper.lines_aslist(value)
        if not flatten:
            return values
        result = []
        for value in values:
            subvalues = MenuHelper.words_aslist(value, sep=',')
            result.extend(subvalues)
        return result

    @staticmethod
    def aschoice(config, option, choices, default=sentinel):
        if default is not sentinel:
            c = config.get(option, default)
        else:
            c = config.get(option)
        if c not in choices:
            raise error("Choice '%s' for option '%s'"
                        " is not a valid choice" % (c, option))
        return choices[c]


class MenuItem(object):
    """Menu item abstract class.
    """
    def __init__(self, manager, config):
        super(MenuItem, self).__init__()
        if type(self) is MenuItem:
            raise Exception(
                'Abstract MenuItem cannot be instantiated directly')
        self.cursor = config.get('cursor', MenuCursor.SELECT)[:1]
        self._manager = manager
        # default display width adjusted by cursor size
        self._width = MenuHelper.asint(config.get(
            'width', (self.manager.cols - len(self.cursor))))
        self._scroll = MenuHelper.asbool(config.get('scroll', 'false'))
        self._enable_tpl = manager.gcode_macro.load_template(
            config, 'enable', 'True')
        self._name_tpl = manager.gcode_macro.load_template(
            config, 'name')
        self._last_heartbeat = None
        self.__scroll_offs = 0
        self.__scroll_diff = 0
        self.__scroll_dir = None
        self.__last_state = True
        # item namespace - used in item relative paths
        self._ns = " ".join(config.get_name().split()[1:])
        self.init()

    # override
    def init(self):
        pass

    def _name(self):
        context = self.get_context()
        return MenuHelper.asliteral(MenuHelper.asflatline(
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
    def start_editing(self, run_script=True):
        pass

    # override
    def stop_editing(self, run_script=True):
        pass

    # override
    def handle_action(self, name, *args, **kwargs):
        if name == 'emit':
            if len(args[0:]) > 0 and len(str(args[0])) > 0:
                self.manager.send_event(
                    "action:" + str(args[0]), self, *args[1:])
            else:
                logging.error("Malformed action: {}({})".format(
                    name, ','.join(map(str, args[0:]))))
        elif name == 'log':
            logging.info("item:{} -> {}".format(
                self.ns, ' '.join(map(str, args[0:]))))

    # override
    def get_context(self, cxt=None):
        # get default menu context
        return self.manager.get_context(cxt)

    def eval_enable(self):
        context = self.get_context()
        return MenuHelper.asbool(self._enable_tpl.render(context))

    # Called when a item is selected
    def select(self):
        self.__clear_scroll()

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

    def render_name(self, scroll=False):
        s = str(self._name())
        if self._width > 0:
            self.__scroll_diff = len(s) - self._width
            if (scroll and self._scroll is True and self.is_scrollable()
                    and self.__scroll_diff > 0):
                s = self.__name_scroll(s)
            else:
                self.__clear_scroll()
                s = s[:self._width].ljust(self._width)
        else:
            self.__clear_scroll()
        return s

    def ns_prefix(self, name):
        name = str(name).strip()
        if name.startswith('.'):
            name = ' '.join([self.ns, name[1:]])
        return name

    def send_event(self, event, *args):
        return self.manager.send_event(
            "item:%s:%s" % (self.ns, str(event)), *args)

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
            raise Exception(
                'Abstract MenuContainer cannot be instantiated directly')
        super(MenuContainer, self).__init__(manager, config)
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
        return isinstance(item, MenuItem)

    def is_editing(self):
        return any([item.is_editing() for item in self._items])

    def stop_editing(self, run_script=True):
        for item in self._items:
            if item.is_editing():
                item.stop_editing(run_script)

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
        self._items, self._names = zip(*_a)

    # override
    def render_content(self, eventtime):
        return ("", None)

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

    def __getitem__(self, key):
        return self._items[key]


class MenuSelector(object):
    """Menu container selector abstract class.
    Use together with MenuContainer
    """
    def __init__(self):
        if type(self) is MenuSelector:
            raise Exception(
                'Abstract MenuSelector cannot be instantiated directly')
        super(MenuSelector, self).__init__()
        if not hasattr(self, '__len__'):
            raise Exception(
                'MenuSelector derived class must implement __len__')
        if not hasattr(self, '__getitem__'):
            raise Exception(
                'MenuSelector derived class must implement __getitem__')
        self.__selected = None

    def init_selection(self):
        self.select_at(0)

    def select_at(self, index):
        self.__selected = index
        # select element
        item = self.selected_item()
        if isinstance(item, MenuItem):
            item.select()
        return item

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

    @property
    def selected(self):
        return self.__selected


class MenuCommand(MenuItem):
    def __init__(self, manager, config):
        super(MenuCommand, self).__init__(manager, config)
        self._gcode_tpl = manager.gcode_macro.load_template(
            config, 'gcode', '')
        self._auto = MenuHelper.asbool(config.get('auto', 'true'))

    def is_auto(self):
        return self._auto

    def get_gcode(self, cxt=None):
        context = self.get_context(cxt)
        return self._gcode_tpl.render(context)

    # override
    def handle_action(self, name, *args, **kwargs):
        super(MenuCommand, self).handle_action(name, *args, **kwargs)
        if name == 'run_gcode':
            gcode = kwargs.pop('gcode', '')
            self.manager.queue_gcode(gcode)


class MenuInput(MenuCommand):
    def __init__(self, manager, config,):
        super(MenuInput, self).__init__(manager, config)
        self._reverse = MenuHelper.asbool(config.get('reverse', 'false'))
        self._realtime = MenuHelper.asbool(config.get('realtime', 'false'))
        self._input_tpl = manager.gcode_macro.load_template(config, 'input')
        self._input_min_tpl = manager.gcode_macro.load_template(
            config, 'input_min', '-999999.0')
        self._input_max_tpl = manager.gcode_macro.load_template(
            config, 'input_max', '999999.0')
        self._input_step = config.getfloat('input_step', above=0.)
        self._input_step2 = config.getfloat('input_step2', 0, minval=0.)
        self._longpress_gcode_tpl = manager.gcode_macro.load_template(
            config, 'longpress_gcode', '')
        self._start_gcode_tpl = manager.gcode_macro.load_template(
            config, 'start_gcode', '')
        self._stop_gcode_tpl = manager.gcode_macro.load_template(
            config, 'stop_gcode', '')

    def init(self):
        super(MenuInput, self).init()
        self._is_dirty = False
        self.__last_change = None
        self._input_value = None
        self.__last_value = None

    def is_scrollable(self):
        return False

    def is_realtime(self):
        return self._realtime

    def get_longpress_gcode(self, cxt=None):
        context = self.get_context(cxt)
        return self._longpress_gcode_tpl.render(context)

    def run_start_gcode(self):
        context = self.get_context()
        self.manager.queue_gcode(self._start_gcode_tpl.render(context))

    def run_stop_gcode(self):
        context = self.get_context()
        self.manager.queue_gcode(self._stop_gcode_tpl.render(context))

    def is_editing(self):
        return self._input_value is not None

    def stop_editing(self, run_script=True):
        if not self.is_editing():
            return
        if run_script is True:
            self.run_stop_gcode()
        self._reset_value()

    def start_editing(self, run_script=True):
        if self.is_editing():
            return
        self._init_value()
        if run_script is True:
            self.run_start_gcode()

    def get_value(self):
        return self._input_value

    def heartbeat(self, eventtime):
        super(MenuInput, self).heartbeat(eventtime)
        if (self._realtime
                and self._is_dirty is True
                and self.__last_change is not None
                and self._input_value is not None
                and (eventtime - self.__last_change) > 0.200):
            self.manager.queue_gcode(self.get_gcode())
            self._is_dirty = False

    def get_context(self, cxt=None):
        context = super(MenuInput, self).get_context(cxt)
        context.update({
            'input': MenuHelper.asfloat(
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
        self.__last_value = None
        self._input_min = MenuHelper.asfloat(self._eval_min())
        self._input_max = MenuHelper.asfloat(self._eval_max())
        value = self._eval_value()
        if MenuHelper.isfloat(value):
            self._input_value = min(self._input_max, max(
                self._input_min, MenuHelper.asfloat(value)))
            if self._realtime:
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

        if self._realtime and last_value != self._input_value:
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

        if self._realtime and last_value != self._input_value:
            self._value_changed()

    # override
    def handle_action(self, name, *args, **kwargs):
        super(MenuInput, self).handle_action(name, *args, **kwargs)
        if name == 'start_editing':
            self.start_editing(*args)
        elif name == 'stop_editing':
            self.stop_editing(*args)


class MenuCallback(MenuContainer):
    def __init__(self, manager, config):
        super(MenuCallback, self).__init__(manager, config)
        self._click_callback = None
        self._back_callback = None
        self._up_callback = None
        self._down_callback = None
        self._render_callback = None
        self._enter_callback = None
        self._leave_callback = None

    # register callbacks
    def register_click_callback(self, callback):
        self._click_callback = callback

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
    def handle_click(self, long_press=False):
        if callable(self._click_callback):
            self._click_callback(long_press)

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


class MenuView(MenuContainer, MenuSelector):
    def __init__(self, manager, config):
        super(MenuView, self).__init__(manager, config)
        self._use_cursor = MenuHelper.asbool(config.get('use_cursor', 'True'))
        self.strict = MenuHelper.asbool(config.get('strict', 'true'))
        self.popup_menu = config.get('popup_menu', None)
        self.content = re.sub(r"\~(\S*):\s*(.+?)\s*\~", self._preproc_content,
                              config.get('content'), 0, re.MULTILINE)
        self._content_tpl = manager.gcode_macro.create_template(
            '%s:content' % (self.ns,), self.content)
        self._enter_gcode_tpl = manager.gcode_macro.load_template(
            config, 'enter_gcode', '')
        self._leave_gcode_tpl = manager.gcode_macro.load_template(
            config, 'leave_gcode', '')
        self._shortpress_gcode_tpl = manager.gcode_macro.load_template(
            config, 'shortpress_gcode', '')
        self._longpress_gcode_tpl = manager.gcode_macro.load_template(
            config, 'longpress_gcode', '')
        self.runtime_items = config.get('items', '')  # mutable list of items
        self.immutable_items = []  # immutable list of items
        self._runtime_index_start = 0
        self._popup_menu = None

    def init(self):
        super(MenuView, self).init()
        self.init_selection()

    def _placeholder(self, s):
        return "~:{}~".format(s)

    def _preproc_content(self, matched):
        full = matched.group(0)  # The entire match
        m = matched.group(1)
        name = matched.group(2)
        if m == "back":
            item = self.manager.menuitem_from({
                'type': 'command',
                'name': repr(name),
                'gcode': '{menu.back()}'
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
                "Unknown placeholder {} in {}:content".format(full, self.ns))
            return ""

    def _names_aslist(self):
        return self.immutable_items

    def _lookup_item(self, item):
        if isinstance(item, dict):
            item = self.manager.menuitem_from(item)
        return super(MenuView, self)._lookup_item(item)

    def is_strict(self):
        return self.strict

    def init_selection(self):
        if not self.is_strict():
            self.select_at(None)
        else:
            self.select_at(0)

    def select_item(self, needle):
        if isinstance(needle, MenuItem):
            if self.selected_item() is not needle:
                index = self.index_of(needle)
                if index is not None:
                    self.select_at(index)
        else:
            logging.error("Cannot select non menuitem")
        return self.selected

    def _populate_extra_items(self):
        # popup menu item
        self._popup_menu = None
        if self.popup_menu is not None:
            menu = self.manager.lookup_menuitem(self.popup_menu)
            if isinstance(menu, MenuContainer):
                menu.assert_recursive_relation(self._parents)
                menu.populate_items()
                self._popup_menu = menu

    def _populate_items(self):
        super(MenuView, self)._populate_items()
        # mark the end of immutable list of items
        # and start of runtime mutable list of items
        self._runtime_index_start = len(self._allitems)
        # populate runtime list of items
        for name in MenuHelper.lines_aslist(self.items):
            self._insert_item(name)
        # populate extra menu items
        self._populate_extra_items()

    def insert_item(self, s, index=None):
        # allow runtime items only after immutable list of items
        if index is None:
            super(MenuView, self).insert_item(s)
        else:
            super(MenuView, self).insert_item(self._runtime_index_start+index)

    def _render_item(self, item, selected=False):
        name = "%s" % str(item.render_name())
        if selected and not self.is_editing():
            if self.use_cursor:
                name = (item.cursor if isinstance(item, MenuItem)
                        else MenuCursor.SELECT) + name
            else:
                name = (name if self.manager.blink_slow_state
                        else ' '*len(name))
        elif selected and self.is_editing():
            if self.use_cursor:
                name = MenuCursor.EDIT + name
            else:
                name = (name if self.manager.blink_fast_state
                        else ' '*len(name))
        elif self.use_cursor:
            name = MenuCursor.NONE + name
        return name

    def render_content(self, eventtime):
        content = ""
        lines = []
        selected_row = None
        context = self.get_context({
            'runtime_items': [
                self._placeholder(n) for i, n in self._allitems[
                    self._runtime_index_start:] if i.is_enabled()
            ]
        })
        try:
            content = self._content_tpl.render(context)
            # postprocess content
            for row, line in enumerate(MenuHelper.lines_aslist(content)):
                s = ""
                for i, text in enumerate(
                        re.split(r"\~:\s*(.+?)\s*\~", line)):
                    if i & 1 == 0:
                        s += text
                    else:
                        idx = self.index_of(text)
                        if idx is not None:
                            current = self[idx]
                            selected = (idx == self.selected)
                            if selected:
                                current.heartbeat(eventtime)
                                selected_row = row
                            s += self._render_item(current, selected)
                lines.append(s)
        except Exception:
            logging.exception('View rendering error')
        return ("\n".join(lines), selected_row)

    def run_enter_gcode(self):
        context = self.get_context()
        self.manager.queue_gcode(self._enter_gcode_tpl.render(context))

    def run_leave_gcode(self):
        context = self.get_context()
        self.manager.queue_gcode(self._leave_gcode_tpl.render(context))

    def get_longpress_gcode(self, cxt=None):
        context = self.get_context(cxt)
        return self._longpress_gcode_tpl.render(context)

    def get_shortpress_gcode(self, cxt=None):
        context = self.get_context(cxt)
        return self._shortpress_gcode_tpl.render(context)

    # override
    def handle_action(self, name, *args, **kwargs):
        super(MenuView, self).handle_action(name, *args, **kwargs)
        if name == 'popup':
            self.manager.push_container(self._popup_menu)

    @property
    def use_cursor(self):
        return self._use_cursor


class MenuVSDCard(MenuView):
    def __init__(self, manager, config):
        super(MenuVSDCard, self).__init__(manager, config)

    def _populate_items(self):
        super(MenuVSDCard, self)._populate_items()
        sdcard = self.manager.objs.get('virtual_sdcard')
        if sdcard is not None:
            files = sdcard.get_file_list()
            for fname, fsize in files:
                gcode = [
                    'M23 /%s' % str(fname)
                ]
                self.insert_item(self.manager.menuitem_from({
                    'type': 'command',
                    'name': repr('%s' % str(fname)),
                    'cursor': '+',
                    'gcode': "\n".join(gcode),
                    'scroll': True
                }))


menu_items = {
    'command': MenuCommand,
    'input': MenuInput,
    'view': MenuView,
    'vsdcard': MenuVSDCard
}

MENU_UPDATE_DELAY = .100
TIMER_DELAY = .200
LONG_PRESS_DURATION = 0.800
BLINK_FAST_SEQUENCE = (True, True, False, False)
BLINK_SLOW_SEQUENCE = (True, True, True, True, False, False, False)


class MenuManager:
    def __init__(self, config, display):
        self.running = False
        self.menuitems = {}
        self.menustack = []
        self._autorun = False
        self.top_row = 0
        self.blink_fast_state = True
        self.blink_slow_state = True
        self._last_eventtime = 0
        self.blink_fast_idx = 0
        self.blink_slow_idx = 0
        self.timeout_idx = 0
        self.display = display
        self.lcd_chip = display.get_lcd_chip()
        self.printer = config.get_printer()
        self.pconfig = self.printer.lookup_object('configfile')
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode_queue = []
        self.context = {}
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
        self.analog_pullup = config.getfloat(
            'analog_pullup_resistor', 4700., above=0.)
        self.analog_pin_debug = config.getboolean('analog_pin_debug', False)
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
                        self.click_callback, self.analog_pin_debug)
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
                        self.back_callback, self.analog_pin_debug)
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
                        self.up_callback, self.analog_pin_debug)
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
                        self.down_callback, self.analog_pin_debug)
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
                        self.kill_callback, self.analog_pin_debug)
                else:
                    self.buttons.register_button_push(
                        self.kill_pin, self.kill_callback)

        # Load local config file in same directory as current module
        self.load_config(os.path.dirname(__file__), 'menu.cfg')
        # Load items from main config
        self.load_menuitems(config)
        # Load menu root
        self.load_root()
        # send init event
        self.send_event('init', self)

    def handle_ready(self):
        # start timer
        reactor = self.printer.get_reactor()
        reactor.register_timer(self.timer_event, reactor.NOW)

    def timer_event(self, eventtime):
        self._last_eventtime = eventtime
        # take next from sequence
        self.blink_fast_idx = (
            (self.blink_fast_idx + 1) % len(BLINK_FAST_SEQUENCE)
        )
        self.blink_slow_idx = (
            (self.blink_slow_idx + 1) % len(BLINK_SLOW_SEQUENCE)
        )
        self.timeout_idx = (self.timeout_idx + 1) % 5  # 0.2*5 = 1s
        self.blink_fast_state = (
            not not BLINK_FAST_SEQUENCE[self.blink_fast_idx]
        )
        self.blink_slow_state = (
            not not BLINK_SLOW_SEQUENCE[self.blink_slow_idx]
        )
        if self.timeout_idx == 0:
            self.timeout_check(eventtime)
        # check long press
        if (self._last_click_press > 0 and (
                eventtime - self._last_click_press) >= LONG_PRESS_DURATION):
            # long click
            self._last_click_press = 0
            self._click_callback(eventtime, True)
        return eventtime + TIMER_DELAY

    def timeout_check(self, eventtime):
        # check timeout
        if (self.is_running() and self.timeout > 0
                and self.root is not None
                and self._autorun is True
                and self._allow_timeout()):
            if self.timer >= self.timeout:
                self.exit()
            else:
                self.timer += 1
        else:
            self.timer = 0

    def _allow_timeout(self):
        container = self.stack_peek()
        if (container is self.root):
            if (isinstance(container, MenuView)
                and ((container.is_strict() and container.selected != 0)
                     or (not container.is_strict()
                         and container.selected is not None))):
                return True
            return False
        return True

    def restart(self, root=None, force_exit=True):
        if self.is_running():
            self.exit(force_exit)
        self.load_root(root, True)

    def load_root(self, root=None, autorun=False):
        root = self._root if root is None else root
        if root is not None:
            self.root = self.lookup_menuitem(root)
            self._autorun = autorun

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
        Starttime values less than 3600 are considered as timeout/delay seconds
        from current reactor time."""
        def callit(eventtime):
            callback(eventtime, *args)
        reactor = self.printer.get_reactor()
        starttime = max(0., float(starttime))
        if starttime < 3600.0:  # 1h
            starttime = reactor.monotonic() + starttime
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
            logging.error("Invalid root '%s', menu stopped!" % str(self._root))
        self.running = False

    def get_status(self, eventtime):
        return {
            'eventtime': eventtime,
            'timeout': self.timeout,
            'autorun': self._autorun,
            'running': self.running,
            'blink_fast': self.blink_fast_state,
            'blink_slow': self.blink_slow_state,
            'rows': self.rows,
            'cols': self.cols
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
        self.context = {
            'printer': self.gcode_macro.create_status_wrapper(eventtime),
            'object': parameter
        }

    def stack_push(self, container):
        if not isinstance(container, MenuContainer):
            raise error("Wrong type, expected MenuContainer")
        top = self.stack_peek()
        if top is not None:
            if isinstance(top, MenuView):
                top.run_leave_gcode()
            elif isinstance(top, MenuCallback):
                top.handle_leave()
        if isinstance(container, MenuView):
            container.run_enter_gcode()
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
                    container.run_leave_gcode()
                elif isinstance(container, MenuCallback):
                    container.handle_leave()
                if isinstance(top, MenuView):
                    top.run_enter_gcode()
                elif isinstance(top, MenuCallback):
                    top.handle_enter()
            else:
                if isinstance(container, MenuView):
                    container.run_leave_gcode()
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
                while viewport_row > (self.top_row + self.rows):
                    self.top_row += 1
                while viewport_row < self.top_row and self.top_row > 0:
                    self.top_row -= 1
            else:
                self.top_row = 0
            for row, text in enumerate(
                    MenuHelper.aslatin(content).splitlines()):
                if self.top_row <= row < self.top_row + self.rows:
                    lines.append(MenuHelper.asliteral(text))
        return lines

    def screen_update_event(self, eventtime):
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
                container.select_prev()
            elif isinstance(container, MenuCallback):
                container.handle_up(fast_rate)

    def down(self, fast_rate=False):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            if isinstance(container, MenuSelector):
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
                container.run_leave_gcode()
            elif isinstance(container, MenuCallback):
                container.handle_leave()
            self.send_event('exit', self)
            self.running = False

    def handle_action(self, name, *args, **kwargs):
        if name == 'back':
            self.back(*args)
        elif name == 'exit':
            self.exit(*args)
        elif name == 'reset':
            # reset container selection
            container = self.stack_peek()
            if self.running:
                if isinstance(container, MenuContainer):
                    container.stop_editing()
                if isinstance(container, MenuSelector):
                    container.init_selection()

    def push_container(self, menu):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            if (isinstance(menu, MenuContainer)
                    and not container.is_editing()
                    and menu is not container):
                self.stack_push(menu)
                return True
        return False

    def enter(self, long_press=False):
        # action context
        actions = MenuTemplateActions()
        context = {'menu': actions.get_caller()}
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            if isinstance(container, MenuSelector):
                current = container.selected_item()
                if isinstance(current, MenuContainer):
                    self.stack_push(current)
                elif isinstance(current, MenuInput):
                    if current.is_editing():
                        if long_press is True:
                            gcode = current.get_longpress_gcode(context)
                            if current.is_auto() is True:
                                self.queue_gcode(gcode)
                            else:
                                actions(current, 'run_gcode', gcode=gcode)
                        else:
                            gcode = current.get_gcode(context)
                            if current.is_auto() is True:
                                if not current.is_realtime():
                                    self.queue_gcode(gcode)
                                current.stop_editing()
                            else:
                                actions(current, 'run_gcode', gcode=gcode)
                        actions(current, 'start_editing, stop_editing')
                    else:
                        current.start_editing()
                elif isinstance(current, MenuCommand):
                    gcode = current.get_gcode(context)
                    if current.is_auto() is True:
                        self.queue_gcode(gcode)
                    else:
                        actions(current, 'run_gcode', gcode=gcode)
                # process general item actions
                if isinstance(current, MenuItem):
                    actions(current, 'emit, log')
                else:  # current is None, no selection
                    if isinstance(container, MenuView):
                        if long_press is True:
                            gcode = container.get_longpress_gcode(context)
                        else:
                            gcode = container.get_shortpress_gcode(context)
                        self.queue_gcode(gcode)
                # process container actions
                actions(container, 'popup')
                # process manager actions
                actions(self, 'back, exit, reset')
                # find leftovers
                for name, args in actions.iter_pop('*'):
                    logging.error("Unknown action: {}({})".format(
                        name, ','.join(map(str, args[0:]))))
            elif isinstance(container, MenuCallback):
                container.handle_click(long_press)

    def queue_gcode(self, script):
        if script is None:
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
        return MenuHelper.aschoice(
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
        return cfg

    def load_menuitems(self, config):
        for cfg in config.get_prefix_sections('menu '):
            item = self.menuitem_from(cfg)
            self.add_menuitem(item.ns, item)

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
                if (eventtime - self._last_click_press) < LONG_PRESS_DURATION:
                    # short click
                    self._last_click_press = 0
                    self._click_callback(eventtime)

    def _click_callback(self, eventtime, long_press=False):
        if self.is_running():
            self.enter(long_press)
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
