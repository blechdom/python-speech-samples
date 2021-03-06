#!/usr/bin/env python

# Copyright 2018 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Google Cloud Speech API sample application using the streaming API.

NOTE: This module requires the additional dependency `pyaudio` and `playsound`.
To install using pip:

    pip install pyaudio
    pip install playsound
    pip install mutagen

the --languageFrom argument requires a language code from this list: https://cloud.google.com/speech-to-text/docs/languages
the --translateLanguage argument requires a language code from this list: https://cloud.google.com/translate/docs/languages
the --languageTo argument requires a language code from this list: https://cloud.google.com/text-to-speech/docs/voices

Example usage:
    python streaming-speech-translation.py --languageFrom 'en-US' --translateLanguage 'fr' --languageTo 'fr-FR'
    python streaming-speech-translation.py --languageFrom 'en-US' --translateLanguage 'it' --languageTo 'it-IT'
    python streaming-speech-translation.py --languageFrom 'en-US' --translateLanguage 'jp' --languageTo 'jp-JP'
    python streaming-speech-translation.py --languageFrom 'en-US' --translateLanguage 'de' --languageTo 'de-DE'
    python streaming-speech-translation.py --languageFrom 'en-US' --translateLanguage 'sv' --languageTo 'sv-SE'
    python streaming-speech-translation.py --languageFrom 'en-US' --translateLanguage 'tr' --languageTo 'tr-TR'
    python streaming-speech-translation.py --languageFrom 'en-US' --translateLanguage 'pt' --languageTo 'pt-BR'
    python streaming-speech-translation.py --languageFrom 'en-US' --translateLanguage 'nl' --languageTo 'nl-NL'
    python streaming-speech-translation.py --languageFrom 'en-US' --translateLanguage 'es' --languageTo 'es-ES'
    python streaming-speech-translation.py --languageFrom 'en-US' --translateLanguage 'ko' --languageTo 'ko-KR'
    python streaming-speech-translation.py --languageFrom 'fr-FR' --translateLanguage 'en' --languageTo 'en-US'
    python streaming-speech-translation.py --languageFrom 'de-DE' --translateLanguage 'en' --languageTo 'en-US'
"""

from __future__ import division

import argparse
import time
import re
import sys
import six
import html

from google.cloud import speech
from google.cloud import texttospeech
from google.cloud import translate

import pyaudio
from playsound import playsound
from mutagen.mp3 import MP3
from six.moves import queue

# Audio recording parameters
STREAMING_LIMIT = 55000
SAMPLE_RATE = 16000
CHUNK_SIZE = int(SAMPLE_RATE / 10)  # 100ms
RECORD_INC = 0
PLAY_INC = 0

def get_current_time():
    return int(round(time.time() * 1000))


def duration_to_secs(duration):
    return duration.seconds + (duration.nanos / float(1e9))


class ResumableMicrophoneStream:
    """Opens a recording stream as a generator yielding the audio chunks."""
    def __init__(self, rate, chunk_size):
        self._rate = rate
        self._chunk_size = chunk_size
        self._num_channels = 1
        self._max_replay_secs = 5

        # Create a thread-safe buffer of audio data
        self._buff = queue.Queue()
        self.closed = True
        self.start_time = get_current_time()

        # 2 bytes in 16 bit samples
        self._bytes_per_sample = 2 * self._num_channels
        self._bytes_per_second = self._rate * self._bytes_per_sample

        self._bytes_per_chunk = (self._chunk_size * self._bytes_per_sample)
        self._chunks_per_second = (
                self._bytes_per_second // self._bytes_per_chunk)

    def __enter__(self):
        self.closed = False

        self._audio_interface = pyaudio.PyAudio()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            channels=self._num_channels,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk_size,
            # Run the audio stream asynchronously to fill the buffer object.
            # This is necessary so that the input device's buffer doesn't
            # overflow while the calling thread makes network requests, etc.
            stream_callback=self._fill_buffer,
        )

        return self

    def __exit__(self, type, value, traceback):
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self.closed = True
        # Signal the generator to terminate so that the client's
        # streaming_recognize method will not block the process termination.
        self._buff.put(None)
        self._audio_interface.terminate()

    def _fill_buffer(self, in_data, *args, **kwargs):
        """Continuously collect data from the audio stream, into the buffer."""
        self._buff.put(in_data)
        return None, pyaudio.paContinue

    def generator(self):
        while not self.closed:
            if get_current_time() - self.start_time > STREAMING_LIMIT:
                self.start_time = get_current_time()
                break
            # Use a blocking get() to ensure there's at least one chunk of
            # data, and stop iteration if the chunk is None, indicating the
            # end of the audio stream.
            chunk = self._buff.get()
            if chunk is None:
                return
            data = [chunk]

            # Now consume whatever other data's still buffered.
            while True:
                try:
                    chunk = self._buff.get(block=False)
                    if chunk is None:
                        return
                    data.append(chunk)
                except queue.Empty:
                    break

            yield b''.join(data)

def synthesize_text(text, langTo):
    global RECORD_INC
    global PLAY_INC
    # print(text)
    """Synthesizes speech from the input string of text."""

    client = texttospeech.TextToSpeechClient()

    input_text = texttospeech.types.SynthesisInput(text=text)

    # Note: the voice can also be specified by name.
    # Names of voices can be retrieved with client.list_voices().
    voice = texttospeech.types.VoiceSelectionParams(
        language_code=langTo,
        ssml_gender=texttospeech.enums.SsmlVoiceGender.FEMALE)

    audio_config = texttospeech.types.AudioConfig(
        audio_encoding=texttospeech.enums.AudioEncoding.MP3)

    response = client.synthesize_speech(input_text, voice, audio_config)

    # The response's audio_content is binary.
    with open('output_' + str(RECORD_INC) + '.mp3', 'wb') as out:
        out.write(response.audio_content)
        print('Audio content written to file output_' + str(RECORD_INC) + '.mp3')

    print('Record increment: ' + str(RECORD_INC))
    if PLAY_INC == RECORD_INC:
        mp3Length = MP3('output_' + str(PLAY_INC) + '.mp3').info.length
        print(mp3Length)
        start = time.time()
        playsound('output_' + str(PLAY_INC) + '.mp3', False)
        while time.time() - start < mp3Length:
            PLAY_INC += 1
            break
        print('Play increment: ' + str(PLAY_INC))


def translate_text(text, translateLang, langTo):
    translate_client = translate.Client()
    translation = translate_client.translate(
        text,
        target_language=translateLang)
    translation = html.unescape(translation['translatedText'])
    synthesize_text(translation, langTo)
    print("Translation: " + translation)

def listen_loop(responses, stream, translateLang, langTo):
    global RECORD_INC
    responses = (r for r in responses if (
            r.results and r.results[0].alternatives))

    num_chars_printed = 0
    for response in responses:
        if not response.results:
            continue

        # The `results` list is consecutive. For streaming, we only care about
        # the first result being considered, since once it's `is_final`, it
        # moves on to considering the next utterance.
        result = response.results[0]
        if not result.alternatives:
            continue

        # Display the transcription of the top alternative.
        top_alternative = result.alternatives[0]
        transcript = top_alternative.transcript

        # Display interim results, but with a carriage return at the end of the
        # line, so subsequent lines will overwrite them.
        #
        # If the previous result was longer than this one, we need to print
        # some extra spaces to overwrite the previous result
        overwrite_chars = ' ' * (num_chars_printed - len(transcript))

        if not result.is_final:
            sys.stdout.write(transcript + overwrite_chars + '\r')
            sys.stdout.flush()

            num_chars_printed = len(transcript)
        else:
            print(transcript + overwrite_chars)
            # Exit recognition if any of the transcribed phrases could be
            # one of our keywords.
            if re.search(r'\b(exit|quit)\b', transcript, re.I):
                print('Exiting..')
                stream.closed = True
                break
            translate_text(transcript, translateLang, langTo)
            RECORD_INC += 1
            num_chars_printed = 0

def main(langFrom, translateLang, langTo):
    client = speech.SpeechClient()
    config = speech.types.RecognitionConfig(
        encoding=speech.enums.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=SAMPLE_RATE,
        language_code=langFrom,
        max_alternatives=1,
        enable_word_time_offsets=True)
    streaming_config = speech.types.StreamingRecognitionConfig(
        config=config,
        interim_results=True)

    mic_manager = ResumableMicrophoneStream(SAMPLE_RATE, CHUNK_SIZE)

    print('Say "Quit" or "Exit" to terminate the program.')

    with mic_manager as stream:
        while not stream.closed:
            audio_generator = stream.generator()
            requests = (speech.types.StreamingRecognizeRequest(
                audio_content=content)
                for content in audio_generator)

            responses = client.streaming_recognize(streaming_config,
                                                   requests)
            # Now, put the transcription responses to use.
            listen_loop(responses, stream, translateLang, langTo)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-lf', '--languageFrom', dest='langFrom', required=True, help='the language code you are translating from from speech api')
    parser.add_argument('-tl', '--translateLanguage', dest='translateLang', required=True, help='the language code you are translating to from translate api')
    parser.add_argument('-lt', '--languageTo', dest='langTo', required=True, help='the language code you are translating to from text-to-speech api')
    args = parser.parse_args()
    main(args.langFrom, args.translateLang, args.langTo)
