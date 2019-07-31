#! /usr/bin/env python

import os
import sys
import time
import pickle
import json
import datetime
from collections import OrderedDict

import numpy as np
import tensorflow as tf
from sklearn import metrics

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from text_lstm import TextLSTM


tf.flags.DEFINE_integer('num_embedding_size', 16, "Number of embedding size")
tf.flags.DEFINE_integer('num_timesteps', 50, "Step of LSTM")
tf.flags.DEFINE_integer('num_lstm_layers', 2, "Number of LSTM layers")
tf.flags.DEFINE_list('num_lstm_nodes', [32, 32], "Number of LSTM layer's node")
tf.flags.DEFINE_integer('num_fc_nodes', 32, "nodes of full connection layer")
tf.flags.DEFINE_integer('batch_size', 1000, "batch size for training")
tf.flags.DEFINE_float('keep_prob', 0.5, "keep_prob")
tf.flags.DEFINE_float('clip_lstm_grads', 1.0, "clip lstm grads")
tf.flags.DEFINE_float('learning_rate', 0.001, "learning rate")
tf.flags.DEFINE_integer('num_word_threshold', 10, "num_word_threshold")
tf.flags.DEFINE_integer("num_checkpoints", 1, "Number of checkpoints to store (default: 5)")
tf.flags.DEFINE_integer("num_epochs", 10, "Number of training epochs (default: 10)")

# Misc Parameters
tf.flags.DEFINE_boolean("allow_soft_placement", True, "Allow device soft device placement")
tf.flags.DEFINE_boolean("log_device_placement", False, "Log placement of ops on devices")

FLAGS = tf.flags.FLAGS

with open("./data/train_data.pickle", 'rb') as f:
    train_data = pickle.loads(f.read())
with open("./data/test_data.pickle", 'rb') as f:
    test_data = pickle.loads(f.read())

classify = {}
tags = {}
for i, cls in enumerate(train_data.keys()):
    tmp = [0] * len(train_data.keys())
    tmp[i] = 1
    classify[cls] = tmp
    tags[i] = cls

x_train, y_train = [], []
for cls, data in train_data.items():
    x_train.extend(data)
    y_train.extend([classify[cls]] * len(data))
x_test, y_test = [], []
for cls, data in test_data.items():
    # data = data[:int(0.5 * len(data))]
    x_test.extend(data)
    y_test.extend([classify[cls]] * len(data))

t1 = time.time()
max_document_length = max([len(x.split(" ")) for x in x_train])
vocab_processor = tf.contrib.learn.preprocessing.VocabularyProcessor(max_document_length)
x_train = np.array(list(vocab_processor.fit_transform(x_train)))
y_train = np.array(y_train)
print("Vocabulary Size: {:d}".format(len(vocab_processor.vocabulary_)))


# Training
with tf.Graph().as_default():
    session_conf = tf.ConfigProto(
        allow_soft_placement=FLAGS.allow_soft_placement,
        log_device_placement=FLAGS.log_device_placement
    )
    sess = tf.Session(config=session_conf)
    with sess.as_default():
        lstm = TextLSTM(
            sequence_length=x_train.shape[1],
            batch_size=FLAGS.batch_size,
            vocab_size=len(vocab_processor.vocabulary_),
            num_embedding_size=FLAGS.num_embedding_size,
            num_lstm_nodes=FLAGS.num_lstm_nodes,
            num_fc_nodes=FLAGS.num_fc_nodes,
            num_classes=y_train.shape[1]
        )

        # Define Training procedure
        global_step = tf.Variable(0, name="global_step", trainable=False)
        optimizer = tf.train.AdamOptimizer(1e-3)
        grads_and_vars = optimizer.compute_gradients(lstm.loss)
        train_op = optimizer.apply_gradients(grads_and_vars, global_step=global_step)

        # Checkpoint directory. Tensorflow assumes this directory already exists so we need to create it
        checkpoint_dir = os.path.abspath(os.path.join(os.path.curdir, "checkpoints"))
        checkpoint_prefix = os.path.join(checkpoint_dir, "text_cnn_model")
        if not os.path.exists(checkpoint_dir):
            os.makedirs(checkpoint_dir)
        saver = tf.train.Saver(tf.global_variables(), max_to_keep=FLAGS.num_checkpoints)

        # Write vocabulary
        vocab_processor.save("./models/vocab.model")

        # Initialize all variables
        sess.run(tf.global_variables_initializer())

        fout = open("log.txt", "w", encoding="utf-8")

        def train_step(x_batch, y_batch):
            """
            A single training step
            """
            feed_dict = {
              lstm.inputs: x_batch,
              lstm.outputs: y_batch,
              lstm.keep_prob: FLAGS.keep_prob
            }
            _, step, loss, accuracy = sess.run(
                [train_op, global_step, lstm.loss, lstm.accuracy],
                feed_dict)
            time_str = datetime.datetime.now().isoformat()
            print("{}: step {}, loss {:g}, acc {:g}".format(time_str, step, loss, accuracy))
            fout.write("{}: step {}, loss {:g}, acc {:g}\n".format(time_str, step, loss, accuracy))
            fout.flush()
            # train_summary_writer.add_summary(summaries, step)

        def dev_step(x_batch, y_batch):
            """
            Evaluates model on a dev set
            """
            feed_dict = {
                lstm.inputs: x_batch,
                lstm.outputs: y_batch,
                lstm.keep_prob: 1.0
            }
            accuracy = sess.run(lstm.accuracy, feed_dict)
            return accuracy

        def test_step(x_batch, y_batch):
            """
            Evaluates model on a dev set
            """
            feed_dict = {
                lstm.inputs: x_batch,
                lstm.outputs: y_batch,
                lstm.keep_prob: 1.0
            }
            predictions, accuracy = sess.run([lstm.predictions, lstm.accuracy], feed_dict)
            return predictions, accuracy

        def batch_iter(data, batch_size, num_epochs, shuffle=True):
            """
            Generates a batch iterator for a dataset.
            """
            data = np.array(data)
            data_size = len(data)
            num_batches_per_epoch = int((len(data) - 1) / batch_size) + 1
            for epoch in range(num_epochs):
                # Shuffle the data at each epoch
                if shuffle:
                    shuffle_indices = np.random.permutation(np.arange(data_size))
                    shuffled_data = data[shuffle_indices]
                else:
                    shuffled_data = data
                for batch_num in range(num_batches_per_epoch):
                    start_index = batch_num * batch_size
                    end_index = min((batch_num + 1) * batch_size, data_size)
                    yield shuffled_data[start_index:end_index]

        # Generate batches
        batches = batch_iter(list(zip(x_train, y_train)), FLAGS.batch_size, FLAGS.num_epochs)
        # Training loop. For each batch...

        best_acc = 0.0
        for batch in batches:
            x_batch, y_batch = zip(*batch)
            train_step(x_batch, y_batch)
            current_step = tf.train.global_step(sess, global_step)
            if current_step % FLAGS.evaluate_every == 0:
                print("\nEvaluation:")
                fout.write("\nEvaluation:")
                fout.flush()
                y_true, y_pred, y_acc = [], [], 0
                for x, y in zip(x_test, y_test):
                    data = np.array(list(vocab_processor.transform([x])))
                    pred, acc = test_step(data, np.array([y]))
                    y_acc += acc
                    y_true.append(tags[y.index(max(y))])
                    y_pred.append(tags[pred[0]])
                classify_report = metrics.classification_report(y_true, y_pred)
                y_acc = y_acc / len(y_true)
                print(classify_report)
                print(y_acc)
                fout.write(str(classify_report))
                fout.write(str(y_acc))
                fout.flush()

                if y_acc > best_acc:
                    best_acc = y_acc
                    path = saver.save(sess, checkpoint_prefix, global_step=current_step)
                    print("Saved model checkpoints to {}\n".format(path))
                    fout.write("Saved model checkpoints to {}\n".format(path))
                    fout.flush()

t2 = time.time()
print('train model over. it took {0}s'.format((t2 - t1)))
