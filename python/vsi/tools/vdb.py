import sys
import pdb
import IPython.core.debugger
from bdb import BdbQuit
import os
import signal
from functools import partial
import traceback

#from vsi.tools import static

if os.name == 'nt':
  from vsi.windows.named_pipes import Pipe
  import threading
  import ctypes
  ATTACH_SIGNAL = signal.SIGINT
else:
  ATTACH_SIGNAL=signal.SIGUSR1


class Tracer(IPython.core.debugger.Tracer):
  ''' Used by Vdb '''
  def __init__(self, colors=None, skipInput = True, *args, **kwargs):
    try:
      super(Tracer, self).__init__(colors)
    except ValueError:
      #This is JUST IN CASE invalid color is specified, should not be relied on
      super(Tracer, self).__init__('Linux') 
    self.debugger = Vdb(skipInput, self.debugger.color_scheme_table.active_scheme_name, *args, **kwargs)
    #This may be dirty, but is less likely to miss features in the future

class Vdb(IPython.core.debugger.Pdb):
  ''' VSI Debugger '''
  def __init__(self, skipInput=True, *args, **kwargs):
    self.__ignore_next_user_return = skipInput
    IPython.core.debugger.Pdb.__init__(self, *args, **kwargs)
    self.prompt = 'vdb> '

  #Modifications to skip initial user input
  def user_return(self, frame, return_value):
    if self.__ignore_next_user_return:
      self.__ignore_next_user_return = False
      self.onecmd('c')#continue, effectively ignoring the first input
    else:
      IPython.core.debugger.Pdb.interaction(self, frame, None)
    
  #everything needed from set_trace, minus sys.settrace
  def _pre_settrace(self, frame=None):
    if frame is None:
      frame = sys._getframe().f_back
    f2 = frame

    self.reset()
    while f2:
      f2.f_trace = self.trace_dispatch
      self.botframe = f2
      f2 = f2.f_back
    self.setup(frame, None)

  #Manually call sys.settrace to use out mods
  def _settrace(self):
    sys.settrace(self.trace_dispatch)

try:
  delattr(IPython.core.debugger.OldPdb, 'do_r')
  delattr(IPython.core.debugger.OldPdb, 'do_q')
  delattr(IPython.core.debugger.Pdb, 'do_q'); #New quit in newer ipython
except:
  pass
#I HATE these! Too powerful and too easy to do by accident

def runpdb(lines, debugger=None):
  ''' Executes a list of vdb command

      Arguments:
      lines - list/tuple/etc... of strings to be executed as if you were 
              already in the debugger. Useful for setting breakpoints 
              programatically.
              
      Returns the debugger object, since this can only be executed on the
      debugger object, you can optionally pass it in as the second argument
      if you want to call rubpdb multiple times. If you do not, a new
      debugger object is created, and all the "memory" of the last debugger
      is lost, such as breakpoints, etc...'''
  try:
    lines + ' ' #Is str like
    lines = [lines] #make it a lise
  except:
    pass

  if not debugger:
    debugger = Tracer().debugger
    
  debugger._pre_settrace(frame=sys._getframe().f_back)
  
  for line in lines:
    debugger.onecmd(line)
  
  debugger._settrace()
  
  return debugger

def get_colors(colors=None):
  if colors is None:
    from IPython import get_ipython
    ip = get_ipython()
    if ip is None:
      colors='Linux'
    else:
     colors = ip.colors
  return colors

def find_frame(frame, depth=0):
  if not frame:
    frame = sys._getframe()
  for d in range(depth):
    if frame.f_back is None:
      break
    frame = frame.f_back  
  return frame
  
def set_trace(frame=None, colors=None, depth=None):
  ''' Helper function, like pdb.set_trace

      set colors = "NoColor", "Linux", or "LightBG"  ''' 
  colors=get_colors(colors)
  frame = find_frame(frame, depth if depth is not None else 2 if frame is None else 0)
  Tracer(skipInput=False, colors=colors).debugger.set_trace(frame)

def post_mortem(tb=None, colors=None):
  ''' Helper function, like pdb.post_mortem '''
  # handling the default
  if tb is None:
    # sys.exc_info() returns (type, value, traceback) if an exception is
    # being handled, otherwise it returns None
    tb = sys.exc_info()[2]
    if tb is None:
      raise ValueError("A valid traceback must be passed if no "
                       "exception is being handled")
  colors = get_colors(colors)
  tracer = Tracer(skipInput=False, colors=colors)
  tracer.debugger.reset()
  tracer.debugger.interaction(None, tb)
 
def set_attach(db_cmd=None):
  ''' Set up this process to be "debugger attachable" 
  
      Just like gdb can attach to a running process, if you execute this on a 
      process, now you can "attach" to the running python using the attach 
      command

      This works pretty well, and allows you to resume the code UNLESS you are
      running in windows and happen to interrupt a sleep command.'''
  #Todo: Add tcp OPTION?

  signal.signal(ATTACH_SIGNAL, partial(handle_db, db_cmd=db_cmd))
  if os.name == 'nt':
    thread = threading.Thread(target=pipe_server)
    thread.daemon = True
    thread.start()
  #print(os.getpid())
  
def attach(pid):
  ''' Trigger a python pid that's been already run set_attach
  
      This is the second part of attaching to a python process. Once 
      set_attach is run, on another prompt running attach will trigger
      the interrupt thing attaching or triggering whatever db_cmd was'''
  if os.name == 'nt':
    pipe = Pipe('vdb_%d' % pid)
    pipe.write('vsi')
    pipe.close()
  else:
    os.kill(pid, ATTACH_SIGNAL)

def pipe_server():
  ''' Part of attach/set_attach for Windows '''
  while 1:
    pipe = Pipe('vdb_%d' % os.getpid(), server=True)
    knock = pipe.read(3)
    if knock == 'vsi':
      os.kill(0, signal.CTRL_C_EVENT)      
      #ctypes.windll.kernel32.GenerateConsoleCtrlEvent(0, os.getpid())
    pipe.disconnect()
    pipe.close()

def handle_db(sig, frame, db_cmd=None):
  ''' signal handler part of attach/set_attach '''
  if sig == ATTACH_SIGNAL:
    #if not hasattr(sys, 'ps1'): #If not interactive
    if db_cmd:
      db_cmd()
    else: #default behavior
      set_trace(frame)

class PostMortemHook(object):
  original_excepthook = None
  
  @staticmethod
  def dbclear_if_error():
    if PostMortemHook.original_excepthook != None:
      sys.excepthook = PostMortemHook.original_excepthook
      PostMortemHook.original_excepthook = None

  @classmethod
  def dbstop_if_error(cls, interactive=False, *args, **kwargs):
    if PostMortemHook.original_excepthook == None:
      PostMortemHook.original_excepthook = sys.excepthook
    cls.set_post_mortem(interactive, *args, **kwargs)

  @staticmethod
  def set_post_mortem(interactive=False):
    ''' Overrite this function for each debugger '''
    raise Exception('Purely virtual function')
    
class VdbPostMortemHook(PostMortemHook):
  @staticmethod
  def set_post_mortem(interactive=False, colors=None):
    sys.excepthook = partial(dbstop_exception_hook, 
                             post_mortem=partial(post_mortem, colors=colors),
                             interactive=interactive)

def dbclear_if_error():
  VdbPostMortemHook.dbclear_if_error()

def dbstop_if_error(interactive=False, colors=None):
  ''' Run this to auto start the vdb debugger on an exception. 

      Optional arguments:
      interactive - Default False. dbstop if console is interactive. You are
                    still able to print and run commands in the debugger, just
                    listing code declared interactively will not work. Does
                    not appear to work in ipython. Use %debug instead. This
                    will not help in the multithread case in ipython... 
                    ipython does too much, just don't try that. Unless
                    someone adds a way to override ipython's override.
      colors - Default None. Set ipython debugger color scheme'''
  VdbPostMortemHook.dbstop_if_error(interactive=interactive, colors=colors)

class DbStopIfErrorGeneric(object):
  ''' With statement for local dbstop situations '''

  ignore_exception = False

  def __init__(self, *args, **kwargs):
    self.args = args
    self.kwargs = kwargs

  def __enter__(self):
    pass

  def __exit__(self, exc_type, exc_value, tb):
    if tb is not None:
      print 'Exception detected!!!'
      pm = self.get_post_mortem()
      pm(tb, *self.args, **self.kwargs)
      if self.ignore_exception:
        return True

  def get_post_mortem(self):
    ''' Should return a function that takes a traceback as the first argument
        and any additional args/kwargs sent to __init__ after that'''
    raise Exception('Purely virtual function')

  @classmethod
  def set_continue_exception(cls):
    ''' Continue running code after exception

        After the with statement scope failes, if this is called, python will
        continue running as if there was no error. Can be useful, can also be
        dangerous. So don't abuse it!'''
    cls.ignore_exception = True


class DbStopIfError(DbStopIfErrorGeneric):
  ''' With statement for local dbstop situations '''
  def __init__(self, threading_support=False, *args, **kwargs):
    ''' Optional arguments:
        threading_support - Support the threading module and patch a bug 
                            preventing catching exceptions in other threads.
                            See add_threading_excepthook for more info. Only
                            neccesary if you want to catch exceptions not on
                            the main thread. This is only patched after 
                            __enter__ unpatched at __exit__

        All other args from db_stop_if_error()'''
    self.threading_support=threading_support

    super(DbStopIfError, self).__init__(*args, **kwargs)

  #This is all needed JUST for threading. It uses syshook instead of __exit__
  def __enter__(self):
    super(DbStopIfError, self).__enter__()

    if self.threading_support:
      import threading
      self.threading_init = threading.Thread.__init__
      add_threading_excepthook()

      self.original_excepthook = sys.excepthook
      self.get_post_mortem_class().set_post_mortem(*self.args, **self.kwargs)

  def __exit__(self, exc_type, exc_value, tb):
    if self.threading_support:
      import threading
      threading.Thread.__init__ = self.threading_init
      sys.excepthook = self.original_excepthook

    super(DbStopIfError, self).__exit__(exc_type, exc_value, tb)

  def get_post_mortem_class(self):
    ''' Get post mortem class for Vdb '''
    return VdbPostMortemHook

  def get_post_mortem(self):
    return post_mortem


def dbstop_exception_hook(type, value, tb, 
                          post_mortem=partial(post_mortem, colors=None),
                          interactive=False):
    if not interactive and (hasattr(sys, 'ps1') or not sys.stderr.isatty()):
    # we are in interactive mode or we don't have a tty-like
    # device, so we call the default hook
      sys.__excepthook__(type, value, tb)
    else:
      #we are NOT in interactive mode, print the exception
      traceback.print_exception(type, value, tb)
      # ...then start the debugger in post-mortem mode.
      post_mortem(tb)

def break_pool_worker():
  ''' Setup the ThreadPool to break when an exception occurs (so that it can 
      be debugged)
  
      The ThreadPool class (and the Pool class too, but not useful here) 
      always catches any exception and raises it in the main thread. This
      is nice for normal behavior, but for debugging, it makes it impossible
      to do post mortem debugging. In order to automatically attach a post
      mortem debugger, the exception has to be thrown. An exception being
      thrown WILL BREAK the pool call, and not allow your main function to
      continue, however you can now attach a debugger post_mortem. Useful
      with dbstop_if_error
      
      Threading has a "bug" where exceptions are also automatically caught.
      http://bugs.python.org/issue1230540
      In order to make THIS work, call add_threading_excepthook too
      
      Example:
      >>> from multiprocessing.pool import ThreadPool
      >>> import vsi.tools.vdb as vdb
      >>> def a(b):
      ...   print(b)
      ...   if b==3:
      ...     does_not_exist()
      >>> vdb.dbstop_if_error()
      >>> vdb.break_pool_worker()
      >>> vdb.add_threading_excepthook()
      >>> tp = ThreadPool(3)
      >>> tp.map(a, range(10))
      '''
  import multiprocessing.pool
  
  def worker(inqueue, outqueue, initializer=None, initargs=(), maxtasks=None):
    assert maxtasks is None or (type(maxtasks) == int and maxtasks > 0)
    put = outqueue.put
    get = inqueue.get
    if hasattr(inqueue, '_writer'):
      inqueue._writer.close()
      outqueue._reader.close()

    if initializer is not None:
      initializer(*initargs)

    completed = 0
    while maxtasks is None or (maxtasks and completed < maxtasks):
      try:
        task = get()
      except (EOFError, IOError):
        multiprocessing.pool.debug('worker got EOFError or IOError -- exiting')
        break

      if task is None:
        multiprocessing.pool.debug('worker got sentinel -- exiting')
        break

      job, i, func, args, kwds = task
#      try:
      result = (True, func(*args, **kwds))
#      except Exception, e:
#        result = (False, e)
      try:
        put((job, i, result))
      except Exception as e:
        wrapped = multiprocessing.pool.MaybeEncodingError(e, result[1])
        multiprocessing.pool.debug("Possible encoding error while sending result: %s" % (wrapped))
        put((job, i, (False, wrapped)))
      completed += 1
    multiprocessing.pool.debug('worker exiting after %d tasks' % completed)
  multiprocessing.pool.worker = worker

def add_threading_excepthook():
  """
  Workaround for sys.excepthook thread bug
  From
  http://spyced.blogspot.com/2007/06/workaround-for-sysexcepthook-bug.html
 
  (https://sourceforge.net/tracker/?func=detail&atid=105470&aid=1230540&group_id=5470).
  Call once from __main__ before creating any threads.
  If using psyco, call psyco.cannotcompile(threading.Thread.run)
  since this replaces a new-style class method.
  """
  import threading, sys
  init_old = threading.Thread.__init__
  def init(self, *args, **kwargs):
    import sys
    init_old(self, *args, **kwargs)
    run_old = self.run
    def run_with_except_hook(*args, **kw):
      try:
        run_old(*args, **kw)
      except (KeyboardInterrupt, SystemExit):
        raise
      except:
        sys.excepthook(*sys.exc_info())
    self.run = run_with_except_hook
  threading.Thread.__init__ = init
      
def main():
  import argparse
  parser = argparse.ArgumentParser()
  parser.add_argument('--pid', '-p', type=int, default=None)
  db = parser.add_mutually_exclusive_group(required=False)
  db.add_argument('--rpdb2', '-r', default=False, action='store_true',
                  help='Attach using rpdb2')
  db.add_argument('--rpdb', default=False, action='store_true',
                  help='Attach using rpdb (Client not implemented, use putty)')
  db.add_argument('--winpdb', '--gui', '-g', default=False, action='store_true',
                  help='Attach using winpdb')
  parser.add_argument('--ip', default='127.0.0.1',
                      help='Set ip address for rpdb/rpdb2/winpdb to attach on')
  parser.add_argument('--port', default=4444, type=int,
                      help='Set port for rpdb to attach on')
  parser.add_argument('--password', '--pw', default='vsi')
  parser.add_argument('args', nargs='*', 
                      help='Command to run with vdb attached. Not implemented yet')
  args = parser.parse_args()
  
  if args.pid:
    #attach to a pid
    if args.rpdb2 or args.winpdb:
      from .vdb_rpdb2 import attach as rpdb2_attach
      rpdb2_attach(args.pid, password=args.password, ip=args.ip, gui=args.winpdb)
    elif args.rpdb:
      from .vdb_rpdb import attach as rpdb_attach
      rpdb_attach(args.pid, ip=args.ip, port=args.port)
    else:
      attach(args.pid)
  else:
    pass #Do whatever pdb does to run the command
    #Copy pdb.main or ipdb.main

if __name__=='__main__':
  main()