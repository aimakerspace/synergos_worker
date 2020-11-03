'''
The method is to spawn new process using the subprocess module when running FL training/evaluate/prediction phases
Reduce the inter-dependencies required for changing the Synergos TTP/Worker code
asyncio usally have await function, not suitable for running independent function like HardwareStatsLogger
Can explore threading/multi-threading class, but requires changes to the Synergos code JUST to work with the HardwareStatsLogger
The easiest way is to extract out the HardwareStatsLogger into it's own proprietary class
so we just need to open another subprocess in the server.py file in TTP and Worker
inside the function start_expt_run_training(..) during any FL training phase
This is one of the way to do it if the Hardware stats should only be logged during specific invoked function/
https://stackoverflow.com/questions/636561/how-can-i-run-an-external-command-asynchronously-from-python
'''
import Sysmetrics
import os

class Test():

    def test_func():
        file_path = os.path.dirname(os.path.abspath(__file__) + '/' + __file__)

        Sysmetrics.run(file_path=file_path, class_name=Test.__name__, function_name=Test.test_func.__name__)

        for i in range(1000000): # ... do other stuff while subprocess is running
            print(i)

        Sysmetrics.terminate()

Test.test_func()