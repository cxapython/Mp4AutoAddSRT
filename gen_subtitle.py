# -*- coding: utf-8 -*-
# @Time : 2021/8/28 11:18 下午
# @Author : chenxiangan
# @File : gen_subtitle.py
# @Software: PyCharm

from __future__ import absolute_import, print_function, unicode_literals

import audioop
import math
import multiprocessing
import os
import subprocess
import tempfile
import wave

from aip import AipSpeech
from autosubb.constants import LANGUAGE_CODES
from autosubb.formatters import FORMATTERS
from progressbar import ProgressBar, Percentage, Bar, ETA

DEFAULT_SUBTITLE_FORMAT = 'srt'
DEFAULT_CONCURRENCY = 1
DEFAULT_LANGUAGE = '1537'


def percentile(arr, percent):
    """
    Calculate the given percentile of arr.
    """
    arr = sorted(arr)
    index = (len(arr) - 1) * percent
    floor = math.floor(index)
    ceil = math.ceil(index)
    if floor == ceil:
        return arr[int(index)]
    low_value = arr[int(floor)] * (ceil - index)
    high_value = arr[int(ceil)] * (index - floor)
    return low_value + high_value


def extract_audio(filename, channels=1, rate=16000):
    """
    Extract audio from an input file to a temporary WAV file.
    ffmpeg  参数
    -i: 表示输入的音频或视频
    -ac: channel 设置通道3, 默认为1
    -ar: sample rate 设置音频采样率
    -acodec: 使用codec编解码，pcm_s16le指位深16bit，转flac此处参数则需改成flac
    -ab: bitrate 设置音频码率
    -vn: 不做视频记录
    -loglevel : 日志等级
    """
    temp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
    if not os.path.isfile(filename):
        print("The given file does not exist: {}".format(filename))
        raise Exception("Invalid filepath: {}".format(filename))
    command = ["ffmpeg", "-y", "-i", filename,
               "-ac", str(channels), "-ar", str(rate),
               "-loglevel", "error", temp.name]
    use_shell = True if os.name == "nt" else False
    subprocess.check_output(command, stdin=open(os.devnull), shell=use_shell)
    return temp.name


class WAVConverter(object):
    """
    Class for converting a region of an input audio or video file into a WAV audio file
    """

    def __init__(self, source_path, include_before=0.25, include_after=0.25):
        self.source_path = source_path
        self.include_before = include_before
        self.include_after = include_after

    def __call__(self, region):
        """
        将文件直接复制到临时目录
        :param region:
        :return:
        """
        try:
            start, end = region
            start = max(0, start - self.include_before)
            end += self.include_after
            temp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            command = ["ffmpeg", "-ss", str(start), "-t", str(end - start),
                       "-y", "-i", self.source_path,
                       "-loglevel", "error", temp.name]
            use_shell = True if os.name == "nt" else False
            subprocess.check_output(command, stdin=open(os.devnull), shell=use_shell)
            read_data = temp.read()
            temp.close()
            os.unlink(temp.name)
            return temp.name, read_data

        except KeyboardInterrupt:
            return None


class SpeechRecognizer(object):
    """
    Class for performing speech-to-text for an input WAV file.
    """

    _client = None

    def __init__(self, app_id, api_key, secret_key, dev_pid='1537', rate=16000, retries=3):
        self.app_id = app_id
        self.api_key = api_key
        self.secret_key = secret_key
        self.rate = rate
        self.dev_pid = dev_pid
        self.retries = retries if retries >= 0 else 0

    @property
    def client(self):
        if not self._client:
            self._client = AipSpeech(self.app_id, self.api_key, self.secret_key)
        return self._client

    def __call__(self, data):
        try:
            for _ in range(self.retries):
                response = self.client.asr(data, 'wav', self.rate, {'dev_pid': self.dev_pid})
                if response['err_no']:
                    continue
                return response['result'][0]
            raise Exception('SpeechRecognizer: %s, err_code: %d' % (response['err_msg'], response['err_no']))
        except KeyboardInterrupt:
            return None


def extract_audio(filename, channels=1, rate=16000):
    """
    Extract audio from an input file to a temporary WAV file.
    """
    temp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
    if not os.path.isfile(filename):
        print("The given file does not exist: {}".format(filename))
        raise Exception("Invalid filepath: {}".format(filename))
    command = ["ffmpeg", "-y", "-i", filename,
               "-ac", str(channels), "-ar", str(rate),
               "-loglevel", "error", temp.name]
    use_shell = True if os.name == "nt" else False
    subprocess.check_output(command, stdin=open(os.devnull), shell=use_shell)
    return temp.name, rate


def find_speech_regions(filename, frame_width=4096, min_region_size=0.5, max_region_size=6):
    """
    Perform voice activity detection on a given audio file.
    """
    reader = wave.open(filename)
    sample_width = reader.getsampwidth()
    rate = reader.getframerate()
    n_channels = reader.getnchannels()
    chunk_duration = float(frame_width) / rate

    n_chunks = int(math.ceil(reader.getnframes() * 1.0 / frame_width))
    energies = []

    for _ in range(n_chunks):
        chunk = reader.readframes(frame_width)
        energies.append(audioop.rms(chunk, sample_width * n_channels))

    threshold = percentile(energies, 0.2)

    elapsed_time = 0

    regions = []
    region_start = None

    for energy in energies:
        is_silence = energy <= threshold
        max_exceeded = region_start and elapsed_time - region_start >= max_region_size

        if (max_exceeded or is_silence) and region_start:
            if elapsed_time - region_start >= min_region_size:
                regions.append((region_start, elapsed_time))
                region_start = None

        elif (not region_start) and (not is_silence):
            region_start = elapsed_time
        elapsed_time += chunk_duration
    return regions


def create_subtitles(source_path,
                     output=None,
                     concurrency=DEFAULT_CONCURRENCY,
                     subtitle_file_format=DEFAULT_SUBTITLE_FORMAT,
                     app_id=None,
                     api_key=None,
                     secret_key=None,
                     dev_pid=DEFAULT_LANGUAGE,
                     ):
    """
    Given an input audio/video file, generate subtitles in the specified language and format.
    """
    if not source_path.endswith(".wav"):
        # 如果不是wav文件，转为wav
        source_path = extract_audio(source_path)
    regions = find_speech_regions(source_path)
    pool = multiprocessing.Pool(concurrency)
    converter = WAVConverter(source_path=source_path)
    recognizer = SpeechRecognizer(app_id=app_id, api_key=api_key, secret_key=secret_key, dev_pid=dev_pid)
    audio_filename = None
    if converter:
        transcripts = []
        if regions:
            try:
                widgets = ["Converting speech regions to WAV files: ", Percentage(), ' ', Bar(), ' ', ETA()]
                pbar = ProgressBar(widgets=widgets, maxval=len(regions)).start()
                extracted_regions = []
                # 将wav切分为很多小的wav文件，然后上传
                for i, each_region in enumerate(pool.imap(converter, regions)):
                    if audio_filename is None:
                        audio_filename = each_region[0]
                    extracted_region = each_region[-1]
                    extracted_regions.append(extracted_region)
                    pbar.update(i)
                pbar.finish()

                widgets = ["Performing speech recognition: ", Percentage(), ' ', Bar(), ' ', ETA()]
                pbar = ProgressBar(widgets=widgets, maxval=len(regions)).start()
                for i, transcript in enumerate(pool.imap(recognizer, extracted_regions)):
                    transcripts.append(transcript)
                    pbar.update(i)
                pbar.finish()

            except KeyboardInterrupt:
                pbar.finish()
                pool.terminate()
                pool.join()
                print("Cancelling transcription")
                raise

        timed_subtitles = [(r, t) for r, t in zip(regions, transcripts) if t]

        if not subtitle_file_format:
            return timed_subtitles

        formatter = FORMATTERS.get(subtitle_file_format)
        formatted_subtitles = formatter(timed_subtitles)

        dest = output

        if not dest:
            base = os.path.splitext(source_path)[0]
            dest = "{base}.{format}".format(base=base, format=subtitle_file_format)

        with open(dest, 'wb') as output_file:
            output_file.write(formatted_subtitles.encode("utf-8"))

        if os.path.exists(audio_filename):
            os.remove(audio_filename)

        return formatted_subtitles


def validate(args):
    """
    Check that the CLI arguments passed to autosub are valid.
    """
    if args.format not in FORMATTERS:
        print(
            "Subtitle format not supported. "
            "Run with --list-formats to see all supported formats."
        )
        return False

    if args.lang not in LANGUAGE_CODES.keys():
        print(
            "Source language not supported. "
            "Run with --list-languages to see all supported languages."
        )
        return False

    if not args.source_path:
        print("Error: You need to specify a source path.")
        return False

    return True
