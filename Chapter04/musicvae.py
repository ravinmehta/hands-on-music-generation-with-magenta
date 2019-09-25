# -*- coding: utf-8 -*-
"""MusicVAE.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/notebooks/magenta/music_vae/music_vae.ipynb

Copyright 2017 Google LLC.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

# MusicVAE: A Hierarchical Latent Vector Model for Learning Long-Term Structure in Music.
### ___Adam Roberts, Jesse Engel, Colin Raffel, Curtis Hawthorne, and Douglas Eck___

[MusicVAE](https://g.co/magenta/music-vae) learns a latent space of musical scores, providing different modes
of interactive musical creation, including:

* Random sampling from the prior distribution.
* Interpolation between existing sequences.
* Manipulation of existing sequences via attribute vectors.

Examples of these interactions can be generated below, and selections can be heard in our
[YouTube playlist](https://www.youtube.com/playlist?list=PLBUMAYA6kvGU8Cgqh709o5SUvo-zHGTxr).

For short sequences (e.g., 2-bar "loops"), we use a bidirectional LSTM encoder
and LSTM decoder. For longer sequences, we use a novel hierarchical LSTM
decoder, which helps the model learn longer-term structures.

We also model the interdependencies between instruments by training multiple
decoders on the lowest-level embeddings of the hierarchical decoder.

For additional details, check out our [blog post](https://g.co/magenta/music-vae) and [paper](https://goo.gl/magenta/musicvae-paper).
___

This colab notebook is self-contained and should run natively on google cloud. The [code](https://github.com/tensorflow/magenta/tree/master/magenta/models/music_vae) and [checkpoints](http://download.magenta.tensorflow.org/models/music_vae/checkpoints.tar.gz) can be downloaded separately and run locally, which is required if you want to train your own model.

# Basic Instructions

1. Double click on the hidden cells to make them visible, or select "View > Expand Sections" in the menu at the top.
2. Hover over the "`[ ]`" in the top-left corner of each cell and click on the "Play" button to run it, in order.
3. Listen to the generated samples.
4. Make it your own: copy the notebook, modify the code, train your own models, upload your own MIDI, etc.!

# Environment Setup
Includes package installation for sequence synthesis. Will take a few minutes.
"""

#@title Setup Environment
#@test {"output": "ignore"}

import glob

print 'Copying checkpoints and example MIDI from GCS. This will take a few minutes...'
!gsutil -q -m cp -R gs://download.magenta.tensorflow.org/models/music_vae/colab2/* /content/

print 'Installing dependencies...'
!apt-get update -qq && apt-get install -qq libfluidsynth1 fluid-soundfont-gm build-essential libasound2-dev libjack-dev
!pip install -q pyfluidsynth
!pip install -qU magenta

# Hack to allow python to pick up the newly-installed fluidsynth lib.
# This is only needed for the hosted Colab environment.
import ctypes.util
orig_ctypes_util_find_library = ctypes.util.find_library
def proxy_find_library(lib):
  if lib == 'fluidsynth':
    return 'libfluidsynth.so.1'
  else:
    return orig_ctypes_util_find_library(lib)
ctypes.util.find_library = proxy_find_library


print 'Importing libraries and defining some helper functions...'
from google.colab import files
import magenta.music as mm
from magenta.models.music_vae import configs
from magenta.models.music_vae.trained_model import TrainedModel
import numpy as np
import os
import tensorflow as tf

# Necessary until pyfluidsynth is updated (>1.2.5).
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

def play(note_sequence):
  mm.play_sequence(note_sequence, synth=mm.fluidsynth)

def interpolate(model, start_seq, end_seq, num_steps, max_length=32,
                assert_same_length=True, temperature=0.5,
                individual_duration=4.0):
  """Interpolates between a start and end sequence."""
  note_sequences = model.interpolate(
      start_seq, end_seq,num_steps=num_steps, length=max_length,
      temperature=temperature,
      assert_same_length=assert_same_length)

  print 'Start Seq Reconstruction'
  play(note_sequences[0])
  print 'End Seq Reconstruction'
  play(note_sequences[-1])
  print 'Mean Sequence'
  play(note_sequences[num_steps // 2])
  print 'Start -> End Interpolation'
  interp_seq = mm.sequences_lib.concatenate_sequences(
      note_sequences, [individual_duration] * len(note_sequences))
  play(interp_seq)
  mm.plot_sequence(interp_seq)
  return interp_seq if num_steps > 3 else note_sequences[num_steps // 2]

def download(note_sequence, filename):
  mm.sequence_proto_to_midi_file(note_sequence, filename)
  files.download(filename)

print 'Done'

"""# 2-Bar Drums Model

Below are 4 pre-trained models to experiment with. The first 3 map the 61 MIDI drum "pitches" to a reduced set of 9 classes (bass, snare, closed hi-hat, open hi-hat, low tom, mid tom, high tom, crash cymbal, ride cymbal) for a simplified but less expressive output space. The last model uses a [NADE](http://homepages.inf.ed.ac.uk/imurray2/pub/11nade/) to represent all possible MIDI drum "pitches".

* **drums_2bar_oh_lokl**: This *low* KL model was trained for more *realistic* sampling. The output is a one-hot encoding of 2^9 combinations of hits. It has a single-layer bidirectional LSTM encoder with 512 nodes in each direction, a 2-layer LSTM decoder with 256 nodes in each layer, and a Z with 256 dimensions. During training it was given 0 free bits, and had a fixed beta value of 0.8. After 300k steps, the final accuracy is 0.73 and KL divergence is 11 bits.
* **drums_2bar_oh_hikl**: This *high* KL model was trained for *better reconstruction and interpolation*. The output is a one-hot encoding of 2^9 combinations of hits. It has a single-layer bidirectional LSTM encoder with 512 nodes in each direction, a 2-layer LSTM decoder with 256 nodes in each layer, and a Z with 256 dimensions. During training it was given 96 free bits and had a fixed beta value of 0.2. It was trained with scheduled sampling with an inverse sigmoid schedule and a rate of 1000. After 300k, steps the final accuracy is 0.97 and KL divergence is 107 bits.
* **drums_2bar_nade_reduced**: This model outputs a multi-label "pianoroll" with 9 classes. It has a single-layer bidirectional LSTM encoder with 512 nodes in each direction, a 2-layer LSTM-NADE decoder with 512 nodes in each layer and 9-dimensional NADE with 128 hidden units, and a Z with 256 dimensions. During training it was given 96 free bits and has a fixed beta value of 0.2. It was trained with scheduled sampling with an inverse sigmoid schedule and a rate of 1000. After 300k steps, the final accuracy is 0.98 and KL divergence is 110 bits.
* **drums_2bar_nade_full**:  The output is a multi-label "pianoroll" with 61 classes. A single-layer bidirectional LSTM encoder with 512 nodes in each direction, a 2-layer LSTM-NADE decoder with 512 nodes in each layer and 61-dimensional NADE with 128 hidden units, and a Z with 256 dimensions. During training it was given 0 free bits and has a fixed beta value of 0.2. It was trained with scheduled sampling with an inverse sigmoid schedule and a rate of 1000. After 300k steps, the final accuracy is 0.90 and KL divergence is 116 bits.
"""

#@title Load Pretrained Models

drums_models = {}
# One-hot encoded.
drums_config = configs.CONFIG_MAP['cat-drums_2bar_small']
drums_models['drums_2bar_oh_lokl'] = TrainedModel(drums_config, batch_size=4, checkpoint_dir_or_path='/content/checkpoints/drums_2bar_small.lokl.ckpt')
drums_models['drums_2bar_oh_hikl'] = TrainedModel(drums_config, batch_size=4, checkpoint_dir_or_path='/content/checkpoints/drums_2bar_small.hikl.ckpt')

# Multi-label NADE.
drums_nade_reduced_config = configs.CONFIG_MAP['nade-drums_2bar_reduced']
drums_models['drums_2bar_nade_reduced'] = TrainedModel(drums_nade_reduced_config, batch_size=4, checkpoint_dir_or_path='/content/checkpoints/drums_2bar_nade.reduced.ckpt')
drums_nade_full_config = configs.CONFIG_MAP['nade-drums_2bar_full']
drums_models['drums_2bar_nade_full'] = TrainedModel(drums_nade_full_config, batch_size=4, checkpoint_dir_or_path='/content/checkpoints/drums_2bar_nade.full.ckpt')

"""## Generate Samples"""

#@title Generate 4 samples from the prior of one of the models listed above.
drums_sample_model = "drums_2bar_oh_lokl" #@param ["drums_2bar_oh_lokl", "drums_2bar_oh_hikl", "drums_2bar_nade_reduced", "drums_2bar_nade_full"]
temperature = 0.5 #@param {type:"slider", min:0.1, max:1.5, step:0.1}
drums_samples = drums_models[drums_sample_model].sample(n=4, length=32, temperature=temperature)
for ns in drums_samples:
  play(ns)

#@title Optionally download generated MIDI samples.
for i, ns in enumerate(drums_samples):
  download(ns, '%s_sample_%d.mid' % (drums_sample_model, i))

"""## Generate Interpolations"""

#@title Option 1: Use example MIDI files for interpolation endpoints.
input_drums_midi_data = [
    tf.gfile.Open(fn).read()
    for fn in sorted(tf.gfile.Glob('/content/midi/drums_2bar*.mid'))]

#@title Option 2: upload your own MIDI files to use for interpolation endpoints instead of those provided.
input_drums_midi_data = files.upload().values() or input_drums_midi_data

#@title Extract drums from MIDI files. This will extract all unique 2-bar drum beats using a sliding window with a stride of 1 bar.
drums_input_seqs = [mm.midi_to_sequence_proto(m) for m in input_drums_midi_data]
extracted_beats = []
for ns in drums_input_seqs:
  extracted_beats.extend(drums_nade_full_config.data_converter.to_notesequences(
      drums_nade_full_config.data_converter.to_tensors(ns)[1]))
for i, ns in enumerate(extracted_beats):
  print "Beat", i
  play(ns)

#@title Interpolate between 2 beats, selected from those in the previous cell.
drums_interp_model = "drums_2bar_oh_hikl" #@param ["drums_2bar_oh_lokl", "drums_2bar_oh_hikl", "drums_2bar_nade_reduced", "drums_2bar_nade_full"]
start_beat = 0 #@param {type:"integer"}
end_beat = 1 #@param {type:"integer"}
start_beat = extracted_beats[start_beat]
end_beat = extracted_beats[end_beat]

temperature = 0.5 #@param {type:"slider", min:0.1, max:1.5, step:0.1}
num_steps = 13 #@param {type:"integer"}

drums_interp = interpolate(drums_models[drums_interp_model], start_beat, end_beat, num_steps=num_steps, temperature=temperature)

#@title Optionally download interpolation MIDI file.
download(drums_interp, '%s_interp.mid' % drums_interp_model)

"""# 2-Bar Melody Model

The pre-trained model consists of a single-layer bidirectional LSTM encoder with 2048 nodes in each direction, a 3-layer LSTM decoder with 2048 nodes in each layer, and Z with 512 dimensions. The model was given 0 free bits, and had its beta valued annealed at an exponential rate of 0.99999 from 0 to 0.43 over 200k steps. It was trained with scheduled sampling with an inverse sigmoid schedule and a rate of 1000. The final accuracy is 0.95 and KL divergence is 58 bits.
"""

#@title Load the pre-trained model.
mel_2bar_config = configs.CONFIG_MAP['cat-mel_2bar_big']
mel_2bar = TrainedModel(mel_2bar_config, batch_size=4, checkpoint_dir_or_path='/content/checkpoints/mel_2bar_big.ckpt')

"""## Generate Samples"""

#@title Generate 4 samples from the prior.
temperature = 0.5 #@param {type:"slider", min:0.1, max:1.5, step:0.1}
mel_2_samples = mel_2bar.sample(n=4, length=32, temperature=temperature)
for ns in mel_2_samples:
  play(ns)

#@title Optionally download samples.
for i, ns in enumerate(mel_2_samples):
  download(ns, 'mel_2bar_sample_%d.mid' % i)

"""## Generate Interpolations"""

#@title Option 1: Use example MIDI files for interpolation endpoints.
input_mel_midi_data = [
    tf.gfile.Open(fn).read()
    for fn in sorted(tf.gfile.Glob('/content/midi/mel_2bar*.mid'))]

#@title Option 2: Upload your own MIDI files to use for interpolation endpoints instead of those provided.
input_mel_midi_data = files.upload().values() or input_mel_midi_data

#@title Extract melodies from MIDI files. This will extract all unique 2-bar melodies using a sliding window with a stride of 1 bar.
mel_input_seqs = [mm.midi_to_sequence_proto(m) for m in input_mel_midi_data]
extracted_mels = []
for ns in mel_input_seqs:
  extracted_mels.extend(
      mel_2bar_config.data_converter.to_notesequences(
          mel_2bar_config.data_converter.to_tensors(ns)[1]))
for i, ns in enumerate(extracted_mels):
  print "Melody", i
  play(ns)

#@title Interpolate between 2 melodies, selected from those in the previous cell.
start_melody = 0 #@param {type:"integer"}
end_melody = 1 #@param {type:"integer"}
start_mel = extracted_mels[start_melody]
end_mel = extracted_mels[end_melody]

temperature = 0.5 #@param {type:"slider", min:0.1, max:1.5, step:0.1}
num_steps = 13 #@param {type:"integer"}

mel_2bar_interp = interpolate(mel_2bar, start_mel, end_mel, num_steps=num_steps, temperature=temperature)

#@title Optionally download interpolation MIDI file.
download(mel_2bar_interp, 'mel_2bar_interp.mid')

"""# 16-bar Melody Models

The pre-trained hierarchical model consists of a 2-layer stacked bidirectional LSTM encoder with 2048 nodes in each direction for each layer, a 16-step 2-layer LSTM "conductor" decoder with 1024 nodes in each layer, a 2-layer LSTM core decoder with 1024 nodes in each layer, and a Z with 512 dimensions. It was given 256 free bits, and had a fixed beta value of 0.2. After 25k steps, the final accuracy is 0.90 and KL divergence is 277 bits.
"""

#@title Load the pre-trained models.
mel_16bar_models = {}
hierdec_mel_16bar_config = configs.CONFIG_MAP['hierdec-mel_16bar']
mel_16bar_models['hierdec_mel_16bar'] = TrainedModel(hierdec_mel_16bar_config, batch_size=4, checkpoint_dir_or_path='/content/checkpoints/mel_16bar_hierdec.ckpt')

flat_mel_16bar_config = configs.CONFIG_MAP['flat-mel_16bar']
mel_16bar_models['baseline_flat_mel_16bar'] = TrainedModel(flat_mel_16bar_config, batch_size=4, checkpoint_dir_or_path='/content/checkpoints/mel_16bar_flat.ckpt')

"""## Generate Samples"""

#@title Generate 4 samples from the selected model prior.
mel_sample_model = "hierdec_mel_16bar" #@param ["hierdec_mel_16bar", "baseline_flat_mel_16bar"]
temperature = 0.5 #@param {type:"slider", min:0.1, max:1.5, step:0.1}
mel_16_samples = mel_16bar_models[mel_sample_model].sample(n=4, length=256, temperature=temperature)
for ns in mel_16_samples:
  play(ns)

#@title Optionally download MIDI samples.
for i, ns in enumerate(mel_16_samples):
  download(ns, '%s_sample_%d.mid' % (mel_sample_model, i))

"""## Generate Means"""

#@title Option 1: Use example MIDI files for interpolation endpoints.
input_mel_16_midi_data = [
    tf.gfile.Open(fn).read()
    for fn in sorted(tf.gfile.Glob('/content/midi/mel_16bar*.mid'))]

#@title Option 2: upload your own MIDI files to use for interpolation endpoints instead of those provided.
input_mel_16_midi_data = files.upload().values() or input_mel_16_midi_data

#@title Extract melodies from MIDI files. This will extract all unique 16-bar melodies using a sliding window with a stride of 1 bar.
mel_input_seqs = [mm.midi_to_sequence_proto(m) for m in input_mel_16_midi_data]
extracted_16_mels = []
for ns in mel_input_seqs:
  extracted_16_mels.extend(
      hierdec_mel_16bar_config.data_converter.to_notesequences(
          hierdec_mel_16bar_config.data_converter.to_tensors(ns)[1]))
for i, ns in enumerate(extracted_16_mels):
  print "Melody", i
  play(ns)

#@title Compute the reconstructions and mean of the two melodies, selected from the previous cell.
mel_interp_model = "hierdec_mel_16bar" #@param ["hierdec_mel_16bar", "baseline_flat_mel_16bar"]

start_melody = 0 #@param {type:"integer"}
end_melody = 1 #@param {type:"integer"}
start_mel = extracted_16_mels[start_melody]
end_mel = extracted_16_mels[end_melody]

temperature = 0.5 #@param {type:"slider", min:0.1, max:1.5, step:0.1}

mel_16bar_mean = interpolate(mel_16bar_models[mel_interp_model], start_mel, end_mel, num_steps=3, max_length=256, individual_duration=32, temperature=temperature)

#@title Optionally download mean MIDI file.
download(mel_16bar_mean, '%s_mean.mid' % mel_interp_model)

"""#16-bar "Trio" Models (lead, bass, drums)

We present two pre-trained models for 16-bar trios: a hierarchical model and a flat (baseline) model.

The pre-trained hierarchical model consists of a 2-layer stacked bidirectional LSTM encoder with 2048 nodes in each direction for each layer, a 16-step 2-layer LSTM "conductor" decoder with 1024 nodes in each layer, 3 (lead, bass, drums) 2-layer LSTM core decoders with 1024 nodes in each layer, and a Z with 512 dimensions. It was given 1024 free bits, and had a fixed beta value of 0.1.  It was trained with scheduled sampling with an inverse sigmoid schedule and a rate of 1000. After 50k steps, the final accuracy is 0.82 for lead, 0.87 for bass, and 0.90 for drums, and the KL divergence is 1027 bits.

The pre-trained flat model consists of a 2-layer stacked bidirectional LSTM encoder with 2048 nodes in each direction for each layer, a 3-layer LSTM decoder with 2048 nodes in each layer, and a Z with 512 dimensions. It was given 1024 free bits, and had a fixed beta value of 0.1.  It was trained with scheduled sampling with an inverse sigmoid schedule and a rate of 1000. After 50k steps, the final accuracy is 0.67 for lead, 0.66 for bass, and 0.79 for drums, and the KL divergence is 1016 bits.
"""

#@title Load the pre-trained models.
trio_models = {}
hierdec_trio_16bar_config = configs.CONFIG_MAP['hierdec-trio_16bar']
trio_models['hierdec_trio_16bar'] = TrainedModel(hierdec_trio_16bar_config, batch_size=4, checkpoint_dir_or_path='/content/checkpoints/trio_16bar_hierdec.ckpt')

flat_trio_16bar_config = configs.CONFIG_MAP['flat-trio_16bar']
trio_models['baseline_flat_trio_16bar'] = TrainedModel(flat_trio_16bar_config, batch_size=4, checkpoint_dir_or_path='/content/checkpoints/trio_16bar_flat.ckpt')

"""## Generate Samples"""

#@title Generate 4 samples from the selected model prior.
trio_sample_model = "hierdec_trio_16bar" #@param ["hierdec_trio_16bar", "baseline_flat_trio_16bar"]
temperature = 0.5 #@param {type:"slider", min:0.1, max:1.5, step:0.1}

trio_16_samples = trio_models[trio_sample_model].sample(n=4, length=256, temperature=temperature)
for ns in trio_16_samples:
  play(ns)

#@title Optionally download MIDI samples.
for i, ns in enumerate(trio_16_samples):
  download(ns, '%s_sample_%d.mid' % (trio_sample_model, i))

"""## Generate Means"""

#@title Option 1: Use example MIDI files for interpolation endpoints.
input_trio_midi_data = [
    tf.gfile.Open(fn).read()
    for fn in sorted(tf.gfile.Glob('/content/midi/trio_16bar*.mid'))]

#@title Option 2: Upload your own MIDI files to use for interpolation endpoints instead of those provided.
input_trio_midi_data = files.upload().values() or input_trio_midi_data

#@title Extract trios from MIDI files. This will extract all unique 16-bar trios using a sliding window with a stride of 1 bar.
trio_input_seqs = [mm.midi_to_sequence_proto(m) for m in input_trio_midi_data]
extracted_trios = []
for ns in trio_input_seqs:
  extracted_trios.extend(
      hierdec_trio_16bar_config.data_converter.to_notesequences(
          hierdec_trio_16bar_config.data_converter.to_tensors(ns)[1]))
for i, ns in enumerate(extracted_trios):
  print "Trio", i
  play(ns)

#@title Compute the reconstructions and mean of the two trios, selected from the previous cell.
trio_interp_model = "hierdec_trio_16bar" #@param ["hierdec_trio_16bar", "baseline_flat_trio_16bar"]

start_trio = 0 #@param {type:"integer"}
end_trio = 1 #@param {type:"integer"}
start_trio = extracted_trios[start_trio]
end_trio = extracted_trios[end_trio]

temperature = 0.5 #@param {type:"slider", min:0.1, max:1.5, step:0.1}
trio_16bar_mean = interpolate(trio_models[trio_interp_model], start_trio, end_trio, num_steps=3, max_length=256, individual_duration=32, temperature=temperature)

#@title Optionally download mean MIDI file.
download(trio_16bar_mean, '%s_mean.mid' % trio_interp_model)