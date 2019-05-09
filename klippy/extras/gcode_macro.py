# Add ability to define custom g-code macros
#
# Copyright (C) 2018-2019  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import traceback, logging
import jinja2


class sentinel:
    pass


######################################################################
# Template handling
######################################################################


# Wrapper for "status" access to printer object get_status() methods
class StatusWrapper:
    def __init__(self, printer, eventtime=None):
        self.printer = printer
        self.eventtime = eventtime
        self.cache = {}

    def __specialreplace(self, s):
        """Replace triple underscores with spaces inside string.
        First and last characters are excluded."""
        return "".join((s[0], s[1:-1].replace('___', ' '), s[-1]))

    def __getitem__(self, val):
        sval = self.__specialreplace(str(val).strip())
        if sval in self.cache:
            return self.cache[sval]
        po = self.printer.lookup_object(sval, sentinel)
        if po is sentinel:
            raise KeyError(val)
        if self.eventtime is None:
            self.eventtime = self.printer.get_reactor().monotonic()
        self.cache[sval] = res = (dict() if not hasattr(po, 'get_status')
                                  else dict(po.get_status(self.eventtime)))
        return res

    def __setitem__(self, key, val):
        skey = self.__specialreplace(str(key).strip())
        self.cache[skey] = val

    def __contains__(self, val):
        sval = self.__specialreplace(str(val).strip())
        if sval not in self.cache and \
                self.printer.lookup_object(sval, sentinel) is sentinel:
            return False
        return True

    def __iter__(self):
        for name, obj in self.printer.lookup_objects():
            yield name

    def __len__(self):
        return len(self.printer.lookup_objects())


# Abstract wrapper around a Jinja2 environment
class EnvironmentWrapper(object):
    def __init__(self, printer, env, name, script):
        self.printer = printer
        self.name = name
        self.script = script
        self.env = env
        self.gcode = self.printer.lookup_object('gcode')

    def create_status_wrapper(self, eventtime=None):
        return StatusWrapper(self.printer, eventtime)

    def create_default_context(self, context=None, eventtime=None):
        if context is None:
            context = {'status': self.create_status_wrapper(eventtime)}
        return context

    def _parse_ast(self):
        return self.env.parse(self.script)

    def find_calls(self):
        """Finds all call names and constant arguments from the template."""
        try:
            ast = self._parse_ast()
        except Exception as e:
            msg = "Error parsing template '%s': %s" % (
                self.name, traceback.format_exception_only(type(e), e)[-1])
            logging.exception(msg)
            raise self.gcode.error(msg)

        for node in ast.find_all(jinja2.nodes.Call):
            if not isinstance(node.node, jinja2.nodes.Name):
                continue
            args = []
            for arg in node.args:
                if isinstance(arg, jinja2.nodes.Const):
                    args.append(arg.value)
                else:
                    args.append(None)
            for arg in node.kwargs:
                args.append(None)
            if node.dyn_args is not None:
                args.append(None)
            if node.dyn_kwargs is not None:
                args.append(None)
            args = tuple(x for x in args if x is not None)
            yield node.node.name, args


# Wrapper around a Jinja2 template
class TemplateWrapper(EnvironmentWrapper):
    def __init__(self, printer, env, name, script):
        super(TemplateWrapper, self).__init__(printer, env, name, script)
        try:
            self.template = env.from_string(script)
        except Exception as e:
            msg = "Error loading template '%s': %s" % (
                name, traceback.format_exception_only(type(e), e)[-1])
            logging.exception(msg)
            raise printer.config_error(msg)

    def render(self, context=None):
        context = self.create_default_context(context)
        try:
            return str(self.template.render(context))
        except Exception as e:
            msg = "Error evaluating '%s': %s" % (
                self.name, traceback.format_exception_only(type(e), e)[-1])
            logging.exception(msg)
            raise self.gcode.error(msg)

    def run_gcode_from_command(self, context=None):
        self.gcode.run_script_from_command(self.render(context))


# Wrapper around a Jinja2 expression
class ExpressionWrapper(EnvironmentWrapper):
    def __init__(self, printer, env, name, script):
        super(ExpressionWrapper, self).__init__(printer, env, name, script)
        try:
            self.expression = env.compile_expression(script)
        except Exception as e:
            msg = "Error loading expression '%s': %s" % (
                name, traceback.format_exception_only(type(e), e)[-1])
            logging.exception(msg)
            raise printer.config_error(msg)

    def _parse_ast(self):
        return self.env.parse("".join([
            self.env.variable_start_string,
            self.script,
            self.env.variable_end_string
        ]))

    def evaluate(self, context=None):
        context = self.create_default_context(context)
        try:
            return self.expression(context)
        except Exception as e:
            msg = "Error evaluating '%s': %s" % (
                self.name, traceback.format_exception_only(type(e), e)[-1])
            logging.exception(msg)
            raise self.gcode.error(msg)


# Main gcode macro template tracking
class PrinterGCodeMacro:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.env = jinja2.Environment(
            '{%', '%}', '{', '}',
            line_statement_prefix='%%',
            extensions=['jinja2.ext.do'])

    def load_template(self, config, option, default=sentinel):
        name = "%s:%s" % ('<dict>' if isinstance(config, dict)
                          else config.get_name(), option)
        script = (config.get(option) if default is sentinel
                  else config.get(option, default))
        return TemplateWrapper(self.printer, self.env, name, script)

    def load_expression(self, config, option, default=sentinel):
        name = "%s:%s" % ('<dict>' if isinstance(config, dict)
                          else config.get_name(), option)
        script = (config.get(option) if default is sentinel
                  else config.get(option, default))
        return ExpressionWrapper(self.printer, self.env, name, script)

    def create_status_wrapper(self, eventtime=None):
        return StatusWrapper(self.printer, eventtime)


def load_config(config):
    return PrinterGCodeMacro(config)


######################################################################
# GCode macro
######################################################################

class GCodeMacro:
    def __init__(self, config):
        self.alias = config.get_name().split()[1].upper()
        printer = config.get_printer()
        config.get('gcode')
        gcode_macro = printer.try_load_module(config, 'gcode_macro')
        self.template = gcode_macro.load_template(config, 'gcode', '')
        self.gcode = printer.lookup_object('gcode')
        self.gcode.register_command(self.alias, self.cmd, desc=self.cmd_desc)
        self.in_script = False
        prefix = 'default_parameter_'
        self.kwparams = { o[len(prefix):].upper(): config.get(o)
                          for o in config.get_prefix_options(prefix) }
    cmd_desc = "G-Code macro"
    def cmd(self, params):
        if self.in_script:
            raise self.gcode.error(
                "Macro %s called recursively" % (self.alias,))
        kwparams = dict(self.kwparams)
        kwparams.update(params)
        kwparams['params'] = params
        self.in_script = True
        try:
            self.template.run_gcode_from_command(kwparams)
        finally:
            self.in_script = False


def load_config_prefix(config):
    return GCodeMacro(config)
