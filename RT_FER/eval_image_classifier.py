"""Generic evaluation script that evaluates a model using a given dataset."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import math,time
import tensorflow as tf

from datasets import dataset_factory
from nets import nets_factory
from preprocessing import preprocessing_factory
from tensorboard import summary as summary_lib

slim = tf.contrib.slim

tf.app.flags.DEFINE_integer(
    'batch_size', 60, 'The number of samples in each batch.')

tf.app.flags.DEFINE_integer(
    'max_num_batches', None,
    'Max number of batches to evaluate by default use all.')

tf.app.flags.DEFINE_string(
    'master', '', 'The address of the TensorFlow master to use.')

tf.app.flags.DEFINE_string(
    'checkpoint_path',
    './tfmodel_mobilenet_v1/ur_directory',
    'The directory where the model was written to or an absolute path to a '
    'checkpoint file.')

tf.app.flags.DEFINE_string(
    'eval_dir',
    './eval/mobilenet_v1/ur_directory',
    'Directory where the results are saved to.')

tf.app.flags.DEFINE_integer(
    'num_preprocessing_threads', 4,
    'The number of threads used to create the batches.')

tf.app.flags.DEFINE_string(
    'dataset_name', 'jaffe', 'The name of the dataset to load.')

tf.app.flags.DEFINE_string(
    'dataset_split_name', 'valid', 'The name of the train/test split.')


tf.app.flags.DEFINE_string(
    'dataset_dir', '/home/ur_directory/validation', 'The directory where the dataset files are stored.')

tf.app.flags.DEFINE_integer(
    'labels_offset', 0,
    'An offset for the labels in the dataset. This flag is primarily used to '
    'evaluate the VGG and ResNet architectures which do not use a background '
    'class for the ImageNet dataset.')

tf.app.flags.DEFINE_string(
    'model_name', 'mobilenet_v1', 'The name of the architecture to evaluate.')

tf.app.flags.DEFINE_string(
    'preprocessing_name', 'mobilenet_v1', 'The name of the preprocessing to use. If left '
    'as `None`, then the model_name flag is used.')

tf.app.flags.DEFINE_float(
    'moving_average_decay', None,
    'The decay to use for the moving average.'
    'If left as None, then moving averages are not used.')

tf.app.flags.DEFINE_integer(
    'eval_image_size', 48, 'Eval image size')

FLAGS = tf.app.flags.FLAGS


def main(_):
  if not FLAGS.dataset_dir:
    raise ValueError('You must supply the dataset directory with --dataset_dir')

  tf.logging.set_verbosity(tf.logging.INFO)
  with tf.Graph().as_default():
    tf_global_step = slim.get_or_create_global_step()

    ######################
    # Select the dataset #
    ######################
    dataset = dataset_factory.get_dataset(
        FLAGS.dataset_name, FLAGS.dataset_split_name, FLAGS.dataset_dir)

    ####################
    # Select the model #
    ####################
    network_fn = nets_factory.get_network_fn(
        FLAGS.model_name,
        num_classes=(dataset.num_classes - FLAGS.labels_offset),
        is_training=False)

    ##############################################################
    # Create a dataset provider that loads data from the dataset #
    ##############################################################
    provider = slim.dataset_data_provider.DatasetDataProvider(
        dataset,
        shuffle=False,
        common_queue_capacity=2 * FLAGS.batch_size,
        common_queue_min=FLAGS.batch_size)
    [image, label] = provider.get(['image', 'label'])
    label -= FLAGS.labels_offset

    #####################################
    # Select the preprocessing function #
    #####################################
    preprocessing_name = FLAGS.preprocessing_name or FLAGS.model_name
    image_preprocessing_fn = preprocessing_factory.get_preprocessing(
        preprocessing_name,
        is_training=False)

    eval_image_size = FLAGS.eval_image_size or network_fn.default_image_size

    image = image_preprocessing_fn(image, eval_image_size, eval_image_size)

    images, labels = tf.train.batch(
        [image, label],
        batch_size=FLAGS.batch_size,
        num_threads=FLAGS.num_preprocessing_threads,
        capacity=5 * FLAGS.batch_size)

    ####################
    # Define the model #
    ####################
    logits, _ = network_fn(images)

    if FLAGS.moving_average_decay:
      variable_averages = tf.train.ExponentialMovingAverage(
          FLAGS.moving_average_decay, tf_global_step)
      variables_to_restore = variable_averages.variables_to_restore(
          slim.get_model_variables())
      variables_to_restore[tf_global_step.op.name] = tf_global_step
    else:
      variables_to_restore = slim.get_variables_to_restore()

    predictions = tf.argmax(logits, 1)
    labels = tf.squeeze(labels)


    prediction = tf.cast(logits, tf.float32) #add
    prediction = tf.nn.softmax(prediction)  #add


    # Define the metrics:
    names_to_values, names_to_updates = slim.metrics.aggregate_metric_map({
        'Accuracy': slim.metrics.streaming_accuracy(predictions, labels),
        #'Recall_5': slim.metrics.streaming_recall_at_k(
        #    logits, labels, 5),
        # 'Mean_Squared_Error': slim.metrics.streaming_mean_squared_error(predictions,labels),
        #'Precision': slim.metrics.streaming_precision(predictions,labels),  #add
        #'Recall': slim.metrics.streaming_recall(predictions,labels),    #add


        #'pr_curve': slim.metrics.streaming_curve_points(labels=labels,predictions=tf.cast(predictions,tf.float32),curve='PR',)

    })
    

    # revised:
    for name, value in names_to_values.items():
        summary_name = 'eval/%s' % name
        op = tf.summary.scalar(summary_name, value, collections=[])
        op = tf.Print(op, [value], summary_name)
        tf.add_to_collection(tf.GraphKeys.SUMMARIES, op)

    #summaries |= set(tf.get_collection(tf.GraphKeys.SUMMARIES))
    #summary_op = tf.summary.merge(list(summaries), name='summary_op')

    # TODO(sguada) use num_epochs=1
    if FLAGS.max_num_batches:
      num_batches = FLAGS.max_num_batches
    else:
      # This ensures that we make a single pass over all of the data.
      num_batches = math.ceil(dataset.num_samples / float(FLAGS.batch_size))

    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True
    #config = tf.ConfigProto(device_count={'GPU': 0})

    exist=[]
    while True:
        states = tf.train.get_checkpoint_state(FLAGS.checkpoint_path)
        checkpoint_paths = states.all_model_checkpoint_paths
        for checkpoint_path in checkpoint_paths:
            if checkpoint_path not in exist:
                tf.logging.info('Evaluating %s' % checkpoint_path)

                slim.evaluation.evaluate_once(
                    master=FLAGS.master,
                    checkpoint_path=checkpoint_path,
                    logdir=FLAGS.eval_dir,
                    num_evals=num_batches,
                    eval_op=list(names_to_updates.values()),
                    session_config=config,
                    variables_to_restore=variables_to_restore)
            exist.append(checkpoint_path)
        time.sleep(5)


if __name__ == '__main__':
  tf.app.run()
