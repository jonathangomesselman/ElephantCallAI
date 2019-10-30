from matplotlib import pyplot as plt
from matplotlib import mlab as ml
import numpy as np
import csv
import os
import time
import multiprocessing
from scipy.io import wavfile
from visualization import visualize
import math
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--data', dest='dataDir', default='../elephant_dataset/New_Data/Truth_Logs/', 
    type=str, help='The top level directory with the data (e.g. Truth_Logs)')
parser.add_argument('--out', dest='outputDir', default='../elephant_dataset/New_Data/Spectrograms/',
     help='The output directory')

# For use on quatro
#parser.add_argument('--data', dest='dataDir', default='/home/data/elephants/rawdata/raw_2018', 
#    type=str, help='The top level directory with the data (e.g. Truth_Logs)')
#parser.add_argument('--out', dest='outputDir', default='/home/data/elephants/rawdata/Spectrograms/',
     #help='The output directory')
parser.add_argument('--NFFT', type=int, default=3208, help='Window size used for creating spectrograms') 
parser.add_argument('--hop', type=int, default=641, help='Hop size used for creating spectrograms')
parser.add_argument('--window', type=int, default=256, 
    help='Deterimes the window size in frames of the resulting spectrogram') # Default corresponds to 21s
parser.add_argument('--max_f', dest='max_freq', type=int, default=100, help='Deterimes the maximum frequency band')
parser.add_argument('--pad', dest='pad_to', type=int, default=4096, 
    help='Deterimes the padded window size that we want to give a particular grid spacing (i.e. 1.95hz')

np.random.seed(8)

def generate_labels(labels, spectrogram_info, len_labels):
    '''
        Given ground truth label file 'label' create the full 
        segmentation labeling for a .wav file. Namely, return
        a vector containing a 0/1 labeling for each time slice
        corresponding to the .wav file transformed into a spectrogram.
        The key challenge here is that we want the labeling to match
        up with the corresponding spectrogram without actually creating
        the spectrogram 
    '''
    labelFile = csv.DictReader(open(labels,'rt'), delimiter='\t')
    labelMatrix = np.zeros(shape=(len_labels),dtype=int)

    samplerate = spectrogram_info['samplerate']
    # Iterates through labels and marks the segments with elephant calls
    for row in labelFile:
        # Use the file offset to determine the start of the call
        start_time = float(row['File Offset (s)'])
        call_length = float(row['End Time (s)']) - float(row['Begin Time (s)'])
        end_time = start_time + call_length
        
        # Figure out for a given start and end time
        # the corresponding spectrogram columns / frames.
        # This math transforms .wav indeces to spectrogram
        # indices
        start_spec = max(math.ceil((start_time * samplerate - spectrogram_info['NFFT'] / 2.) / spectrogram_info['hop']), 0)
        end_spec = min(math.ceil((end_time * samplerate - spectrogram_info['NFFT'] / 2.) / spectrogram_info['hop']), labelMatrix.shape[0])
        labelMatrix[start_spec : end_spec] = 1

    return labelMatrix


def generate_whole_spectogram(audio_file, spectrogram_info, id, chunk_size=1000):
    """
        For a given complete audio file generate the corresponding
        spectrogram in chunks. Namley, generate 1000 window block
        spectrograms at a time, limiting the max frequency to save
        on memory and cut out uneeded information. We generate in chunks
        to deal with memory issues and efficiency involved with doing
        the complete DFT at once
    """
    samplerate, raw_audio = wavfile.read(audio_file)
    NFFT = spectrogram_info['NFFT']
    hop = spectrogram_info['hop']
    max_freq = spectrogram_info['max_freq']
    pad_to = spectrogram_info['pad_to']

    # Generate the spectogram in chunks
    # of 1000 frames.
    len_chunk = (chunk_size - 1) * hop + NFFT

    final_spec = None
    start_chunk = 0
    i = 0
    while start_chunk + len_chunk < raw_audio.shape[0]:
        if (i % 10 == 0):
            print (str(i) + ": " + id)
        [spectrum, freqs, t] = ml.specgram(raw_audio[start_chunk: start_chunk + len_chunk], 
                NFFT=NFFT, Fs=samplerate, noverlap=(NFFT - hop), window=ml.window_hanning, pad_to=pad_to)
        # Cutout the high frequencies that are not of interest
        spectrum = spectrum[(freqs <= max_freq)]

        if i == 0:
            final_spec = spectrum
        else:
            final_spec = np.concatenate((final_spec, spectrum), axis=1)

        # Remember that we want to start as if we are doing one continuous sliding window
        start_chunk += len_chunk - NFFT + hop 
        i += 1

    # Do one final chunk for whatever remains at the end
    [spectrum, freqs, t] = ml.specgram(raw_audio[start_chunk: start_chunk + len_chunk], 
            NFFT=NFFT, Fs=samplerate, noverlap=(NFFT - hop), window=ml.window_hanning, pad_to=pad_to)
    # Cutout the high frequencies that are not of interest
    spectrum = spectrum[(freqs <= max_freq)]
    final_spec = np.concatenate((final_spec, spectrum), axis=1)

    return final_spec



#########################
######## Execute ########
if __name__ == '__main__':
    args = parser.parse_args()
    dataDir = args.dataDir
    outputDir = args.outputDir
    spectrogram_info = {'NFFT': args.NFFT,
                        'hop': args.hop,
                        'max_freq': args.max_freq,
                        'window': args.window,
                        'samplerate': 8000,
                        'pad_to': args.pad_to}

    # Iterate through all data directories
    allDirs = [];
    # Get the directories that contain the data files
    for (dirpath, dirnames, filenames) in os.walk(dataDir):
        allDirs.extend(dirnames);
        break

    feature_set = []
    label_set = []
    # Iterate through all files with in data directories
    for dirName in allDirs:
        #Iterate through each dir and get files within
        currentDir = dataDir + '/' + dirName;
        for(dirpath, dirnames, filenames) in os.walk(dataDir+'/'+dirName):
            # Iterate through the files to create data/label 
            # pairs (i.e. (.wav, .txt))
            data_pairs = {}
            for eachFile in filenames:
                # Strip off the location and time tags
                tags = eachFile.split('_')
                data_id = tags[0] + '_' + tags[1]
                file_type = eachFile.split('.')[1]

                if (file_type not in ['wav', 'txt']):
                    continue

                # Insert the file name into the dictionary
                # with the file type tag for a given id
                if not data_id in data_pairs:
                    data_pairs[data_id] = {}

                data_pairs[data_id][file_type] = eachFile
                data_pairs[data_id]['id'] = data_id
                
            # Create a list of (wav_file, label_file, id) tuples to be processed
            file_pairs = [(pair['wav'], pair['txt'], pair['id']) for _, pair in data_pairs.items()]

            def wrapper_processData(data_pair):
                audio_file = data_pair[0]
                label_file = data_pair[1]
                data_id = data_pair[2]

                spectrogram = generate_whole_spectogram(currentDir + '/' + audio_file, spectrogram_info, data_id)
                print (spectrogram.shape)
                labels = generate_labels(currentDir + '/' + label_file, spectrogram_info, spectrogram.shape[1])
                
                # Save these to spectrogram output folder with
                # name dictated by the data_id
                dir = os.path.join(outputDir,dirName)
                if not os.path.exists(dir):
                    os.mkdir(dir)
                np.save(dir + '/' + data_id + "_spec.npy", spectrogram)
                np.save(dir + '/' + data_id + "_label.npy", labels)

                print ("processed " + data_id)

            
            pool = multiprocessing.Pool()
            print('Multiprocessing on {} CPU cores'.format(os.cpu_count()))
            start_time = time.time()
            output = pool.map(wrapper_processData, file_pairs)
            print('Multiprocessed took {}'.format(time.time()-start_time))
            pool.close()
            print('Multiprocessed took {}'.format(time.time()-start_time))





##############################################
####### # Old unused code examples ###########
##############################################
"""
def generate_labels2(labels, len_spect, time_indeces, spectrogram_info):
    '''
        Given ground truth label file 'label' create the full 
        segmentation labeling for a corresponding audio 
        spectrogram. Namely, return a vector containing a 0/1 labeling 
        for each spectrogram time slice
    '''
    labelFile = csv.DictReader(open(labels,'rt'), delimiter='\t')
    
    labelMatrix = np.zeros(shape=(len_spect),dtype=int)

    samplerate = spectrogram_info['samplerate']
    # Iterates through labels and marks the segments with elephant calls
    for row in labelFile:
        # Use the file offset to determine the start of the call
        start_time = float(row['File Offset (s)'])
        call_length = float(row['End Time (s)']) - float(row['Begin Time (s)'])
        end_time = start_time + call_length
        
        # Figure out which spectrogram slices we are on
        # to get columns that we want to span with the given
        # slice. This math transforms .wav indeces to spectrogram
        # indices
        labelMatrix[(time_indeces >= start_time) & (end_time > time_indeces)] = 1
        
    return labelMatrix

def generate_whole_spectogram(audio_file, outputDir, spectrogram_info):
    samplerate, raw_audio = wavfile.read(audio_file)
    NFFT = spectrogram_info['NFFT']
    hop = spectrogram_info['hop']
    max_freq = spectrogram_info['max_freq']

    # Generate the spectogram in chunks
    # Should be full lengthed spectrograms
    # i.e. should be able to divide the audio
    # into complete windows 
    len_chunk = 999 * hop + NFFT

    final_spec = None
    time_series = None
    start_chunk = 0
    i = 0
    while start_chunk + len_chunk < raw_audio.shape[0]:
        print (i)
        [spectrum, freqs, t] = ml.specgram(raw_audio[start_chunk: start_chunk + len_chunk], 
                NFFT=NFFT, Fs=samplerate, noverlap=(NFFT - hop), window=ml.window_hanning, pad_to=4096)
        print (spectrum.shape)
        # Cutout the high frequencies that are not of interest
        spectrum = spectrum[(freqs <= max_freq)]

        if i == 0:
            final_spec = spectrum
            time_series = t
        else:
            final_spec = np.concatenate((final_spec, spectrum), axis=1)
            time_series = np.concatenate((time_series, time_series[-1] + (np.arange(t.shape[0]) + 1) * hop / samplerate))

        # Remember that we want to start as if we are doing one continuous sliding window
        i += 1
        start_chunk += len_chunk - NFFT + hop 

    # Do one final chunk?
    [spectrum, freqs, t] = ml.specgram(raw_audio[start_chunk: start_chunk + len_chunk], 
            NFFT=NFFT, Fs=samplerate, noverlap=(NFFT - hop), window=ml.window_hanning, pad_to=4096)
    print (spectrum.shape)
    # Cutout the high frequencies that are not of interest
    spectrum = spectrum[(freqs <= max_freq)]
    final_spec = np.concatenate((final_spec, spectrum), axis=1)
    time_series = np.concatenate((time_series, time_series[-1] + (np.arange(t.shape[0]) + 1) * hop / samplerate))

    #np.save(outputDir + '/spec.npy', final_spec)
    return final_spec, time_series
"""



