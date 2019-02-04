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

"""Google Cloud Speech API sample that demonstrates using DLP to automatically discover and redact sensitve data.

Example usage:
    python speech-to-text-to-nlp.py deidentify -p <ProjectID>
    python speech-to-text-to-nlp.py deidentify -f './resources/sallybrown.flac' -p <ProjectID>
"""
import argparse
import io
import re
from pathlib import Path

# Imports the Google Cloud client library
from google.cloud import speech
from google.cloud import dlp
from google.cloud.speech import enums
from google.cloud.speech import types
from google.cloud import language
from google.cloud.language import enums as enumsnlp
from google.cloud.language import types as typesnlp

def deidentify(file_name, projectID):
    # Instantiates a client
    speechClient = speech.SpeechClient()

    dlpClient = dlp.DlpServiceClient()
    nlpClient = language.LanguageServiceClient()

    parent = dlpClient.project_path(projectID)

    # Prepare info_types by converting the list of strings into a list of
    info_types = ['PHONE_NUMBER', 'EMAIL_ADDRESS', 'CREDIT_CARD_NUMBER', 'US_SOCIAL_SECURITY_NUMBER']
    # dictionaries (protos are also accepted).
    inspect_config = {
        'info_types': [{'name': info_type} for info_type in info_types]
    }
    # Construct deidentify configuration dictionary
    deidentify_config = {
        'info_type_transformations': {
            'transformations': [
                {
                    'primitive_transformation': {
                        'replace_with_info_type_config': {

                        }
                    }
                }
            ]
        }
    }

    # The name of the audio file and path to transcribe
    #file_name = Path('./resources/sallybrown.flac')


    # Loads the audio into memory
    with io.open(file_name, 'rb') as audio_file:
        content = audio_file.read()
        audio = types.RecognitionAudio(content=content)

    config = types.RecognitionConfig(
        encoding=enums.RecognitionConfig.AudioEncoding.FLAC,
        sample_rate_hertz=16000,
        language_code='en-US')

    # Detects speech in the audio file
    response = speechClient.recognize(config, audio)

    transcript = ""

    for result in response.results:
        transcript = transcript + result.alternatives[0].transcript;

    print('Original Transcript: {}'.format(transcript))

    # Check transcription for email address, since speech-to-text returns " at " instead of "@"
    # Format with regex before sending to DLP api
    # Currently social security numbers and credit card numbers are interpreted as phone numbers

    regex = r".([A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*)(\sat\s+)((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9]))"

    updatedTranscript = re.sub(regex, r" \1@\3", transcript)

    print('Email addresses reformatted: {}'.format(updatedTranscript))

    # Construct item
    item = {'value': updatedTranscript}

    # Call the API
    dlpResponse = dlpClient.deidentify_content(
        parent, inspect_config=inspect_config,
        deidentify_config=deidentify_config, item=item)

    # Print out the results.
    print('Final Result with sensitive content redacted: {}'.format(dlpResponse.item.value))

    # The text to analyze
    text = dlpResponse.item.value
    document = typesnlp.Document(
        content=text,
        type=enumsnlp.Document.Type.PLAIN_TEXT)

    # Detects the sentiment of the text
    sentiment = nlpClient.analyze_sentiment(document=document).document_sentiment

    print('Sentiment: {}, {}'.format(sentiment.score, sentiment.magnitude))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', help="deidentify: replace sensitive data with [INFO TYPE]")
    parser.add_argument('-f', '--filename', dest='filename', required=False,
        default='./resources/sallybrown.flac', help='speech file to transcribe and then auto-redact')
    parser.add_argument('-p', '--projectID', dest='projectID', required=True, help='the name of your Google API project ID')
    args = parser.parse_args()

    if args.command == 'deidentify':
        deidentify(args.filename, args.projectID)
