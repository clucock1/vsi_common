import subprocess
import inspect

''' Version of subprocess.Popen that runs in the background on windows '''


class PopenBg(subprocess.Popen):

  def __init__(self, *args, **kwargs):
    if subprocess.mswindows:
      kwargs = inspect.getcallargs(
          subprocess.Popen.__init__, self, *args, **kwargs)
      args = []
      kwargs.pop('self')
      startup_info = kwargs.pop('startupinfo')
      if startup_info is None:
        startup_info = subprocess.STARTUPINFO()
      startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
      kwargs['startupinfo'] = startup_info
    return super(PopenBg, self).__init__(*args, **kwargs)

if __name__ == '__main__':
  import sys
  pid = PopenBg(sys.argv[1:])
