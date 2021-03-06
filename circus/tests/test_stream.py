import time
import sys
import os
import tempfile
import tornado

from datetime import datetime
from circus.py3compat import StringIO

from circus.client import make_message
from circus.tests.support import TestCircus, async_poll_for, truncate_file
from circus.tests.support import TestCase, EasyTestSuite
from circus.stream import FileStream
from circus.stream import FancyStdoutStream


def run_process(testfile, *args, **kw):
    try:
        # print once, then wait
        sys.stdout.write('stdout')
        sys.stdout.flush()
        sys.stderr.write('stderr')
        sys.stderr.flush()
        with open(testfile, 'a+') as f:
            f.write('START')
        time.sleep(1.)
    except:
        return 1


class TestWatcher(TestCircus):
    dummy_process = 'circus.tests.test_stream.run_process'

    @tornado.gen.coroutine
    def start_arbiter(self):
        cls = TestWatcher
        fd, cls.stdout = tempfile.mkstemp()
        os.close(fd)
        fd, cls.stderr = tempfile.mkstemp()
        os.close(fd)
        cls.stdout_stream = FileStream(cls.stdout)
        cls.stderr_stream = FileStream(cls.stderr)
        stdout = {'stream': cls.stdout_stream}
        stderr = {'stream': cls.stderr_stream}
        self.file, self.arbiter = cls._create_circus(cls.dummy_process,
                                                     stdout_stream=stdout,
                                                     stderr_stream=stderr,
                                                     debug=True, async=True)
        yield self.arbiter.start()

    @tornado.gen.coroutine
    def stop_arbiter(self):
        cls = TestWatcher
        yield self.arbiter.stop()
        cls.stdout_stream.close()
        cls.stderr_stream.close()
        if os.path.exists(self.file):
            os.remove(self.file)
        if os.path.exists(self.stdout):
            os.remove(cls.stdout)
        if os.path.exists(self.stderr):
            os.remove(cls.stderr)

    @tornado.gen.coroutine
    def restart_arbiter(self):
        yield self.arbiter.restart()

    @tornado.gen.coroutine
    def call(self, _cmd, **props):
        msg = make_message(_cmd, **props)
        resp = yield self.cli.call(msg)
        raise tornado.gen.Return(resp)

    @tornado.testing.gen_test
    def test_file_stream(self):
        yield self.start_arbiter()
        stream = FileStream(self.stdout, max_bytes='12', backup_count='3')
        self.assertTrue(isinstance(stream._max_bytes, int))
        self.assertTrue(isinstance(stream._backup_count, int))
        yield self.stop_arbiter()
        stream.close()

    @tornado.testing.gen_test
    def test_stream(self):
        yield self.start_arbiter()
        # wait for the process to be started
        res1 = yield async_poll_for(self.stdout, 'stdout')
        res2 = yield async_poll_for(self.stderr, 'stderr')
        self.assertTrue(res1)
        self.assertTrue(res2)

        # clean slate
        truncate_file(self.stdout)
        truncate_file(self.stderr)

        # restart and make sure streams are still working
        yield self.restart_arbiter()

        # wait for the process to be restarted
        res1 = yield async_poll_for(self.stdout, 'stdout')
        res2 = yield async_poll_for(self.stderr, 'stderr')
        self.assertTrue(res1)
        self.assertTrue(res2)
        yield self.stop_arbiter()


class TestFancyStdoutStream(TestCase):

    def color_start(self, code):
        return '\033[0;3%s;40m' % code

    def color_end(self):
        return '\033[0m\n'

    def get_stream(self, *args, **kw):
        # need a constant timestamp
        now = datetime.now()
        stream = FancyStdoutStream(*args, **kw)

        # patch some details that will be used
        stream.out = StringIO()
        stream.now = lambda: now

        return stream

    def get_output(self, stream):
        # stub data
        data = {'data': 'hello world',
                'pid': 333}

        # get the output
        stream(data)
        output = stream.out.getvalue()
        stream.out.close()

        expected = self.color_start(stream.color_code)
        expected += stream.now().strftime(stream.time_format) + " "
        expected += "[333] | " + data['data'] + self.color_end()
        return output, expected

    def test_random_colored_output(self):
        stream = self.get_stream()
        output, expected = self.get_output(stream)
        self.assertEqual(output, expected)

    def test_red_colored_output(self):
        stream = self.get_stream(color='red')
        output, expected = self.get_output(stream)
        self.assertEqual(output, expected)

    def test_time_formatting(self):
        stream = self.get_stream(time_format='%Y/%m/%d %H.%M.%S')
        output, expected = self.get_output(stream)
        self.assertEqual(output, expected)

    def test_data_split_into_lines(self):
        stream = self.get_stream(color='red')
        data = {'data': '\n'.join(['foo', 'bar', 'baz']),
                'pid': 333}

        stream(data)
        output = stream.out.getvalue()
        stream.out.close()

        # NOTE: We expect 4 b/c the last line needs to add a newline
        #       in order to prepare for the next chunk
        self.assertEqual(len(output.split('\n')), 4)

    def test_data_with_extra_lines(self):
        stream = self.get_stream(color='red')

        # There is an extra newline
        data = {'data': '\n'.join(['foo', 'bar', 'baz', '']),
                'pid': 333}

        stream(data)
        output = stream.out.getvalue()
        stream.out.close()

        self.assertEqual(len(output.split('\n')), 4)

    def test_color_selections(self):
        # The colors are chosen from an ordered list where each index
        # is used to calculate the ascii escape sequence.
        for i, color in enumerate(FancyStdoutStream.colors):
            stream = self.get_stream(color)
            self.assertEqual(i + 1, stream.color_code)
            stream.out.close()


class TestFileStream(TestCase):

    def get_stream(self, *args, **kw):
        # need a constant timestamp
        now = datetime.now()
        stream = FileStream(*args, **kw)

        # patch some details that will be used
        stream._file.close()
        stream._file = StringIO()
        stream._open = lambda: stream._file
        stream.now = lambda: now

        return stream

    def get_output(self, stream):
        # stub data
        data = {'data': 'hello world',
                'pid': 333}

        # get the output
        stream(data)
        output = stream._file.getvalue()
        stream._file.close()

        expected = stream.now().strftime(stream.time_format) + " "
        expected += "[333] | " + data['data'] + '\n'
        return output, expected

    def test_time_formatting(self):
        stream = self.get_stream(time_format='%Y/%m/%d %H.%M.%S')
        output, expected = self.get_output(stream)
        self.assertEqual(output, expected)

    def test_data_split_into_lines(self):
        stream = self.get_stream(time_format='%Y/%m/%d %H.%M.%S')
        data = {'data': '\n'.join(['foo', 'bar', 'baz']),
                'pid': 333}

        stream(data)
        output = stream._file.getvalue()
        stream._file.close()

        # NOTE: We expect 4 b/c the last line needs to add a newline
        #       in order to prepare for the next chunk
        self.assertEqual(len(output.split('\n')), 4)

    def test_data_with_extra_lines(self):
        stream = self.get_stream(time_format='%Y/%m/%d %H.%M.%S')

        # There is an extra newline
        data = {'data': '\n'.join(['foo', 'bar', 'baz', '']),
                'pid': 333}

        stream(data)
        output = stream._file.getvalue()
        stream._file.close()
        self.assertEqual(len(output.split('\n')), 4)

    def test_data_with_no_EOL(self):
        stream = self.get_stream()

        # data with no newline and more than 1024 chars
        data = {'data': '*' * 1100, 'pid': 333}

        stream(data)
        stream(data)
        output = stream._file.getvalue()
        stream._file.close()

        self.assertEqual(output, '*' * 2200)


test_suite = EasyTestSuite(__name__)
