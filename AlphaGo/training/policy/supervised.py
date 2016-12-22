import numpy as np
import os
import h5py as h5
import json
from keras import backend as K
from keras.optimizers import SGD
from keras.callbacks import Callback
from AlphaGo.models.policy import CNNPolicy
from AlphaGo.preprocessing.preprocessing import Preprocess

# default settings
DEFAULT_MAX_VALIDATION = 1000000000
DEFAULT_TRAIN_VAL_TEST = [.95, .05, .0]
DEFAULT_LEARNING_RATE = 0.03
DEFAULT_BATCH_SIZE = 16
DEFAULT_DECAY = .0001
DEFAULT_EPOCH = 10

TRANSFORMATION_INDICES = {
    "noop": 0,
    "rot90": 1,
    "rot180": 2,
    "rot270": 3,
    "fliplr": 4,
    "flipud": 5,
    "diag1": 6,
    "diag2": 7
}

BOARD_TRANSFORMATIONS = {
    0: lambda feature: feature,
    1: lambda feature: np.rot90(feature, 1),
    2: lambda feature: np.rot90(feature, 2),
    3: lambda feature: np.rot90(feature, 3),
    4: lambda feature: np.fliplr(feature),
    5: lambda feature: np.flipud(feature),
    6: lambda feature: np.transpose(feature),
    7: lambda feature: np.fliplr(np.rot90(feature, 1))
}


def one_hot_action(action, size=19):
    """Convert an (x,y) action into a size x size array of zeros with a 1 at x,y
    """

    categorical = np.zeros((size, size))
    categorical[action] = 1
    return categorical


def shuffled_hdf5_batch_generator(state_dataset, action_dataset,
                                  indices, batch_size):
    """A generator of batches of training data for use with the fit_generator function
       of Keras. Data is accessed in the order of the given indices for shuffling.
    """

    state_batch_shape = (batch_size,) + state_dataset.shape[1:]
    game_size = state_batch_shape[-1]
    Xbatch = np.zeros(state_batch_shape)
    Ybatch = np.zeros((batch_size, game_size * game_size))
    batch_idx = 0
    while True:
        for data_idx in indices:
            # get rotation symmetry belonging to state
            transform = BOARD_TRANSFORMATIONS[data_idx[1]]

            # get state from dataset and transform it.
            # loop comprehension is used so that the transformation acts on the
            # 3rd and 4th dimensions
            state = np.array([transform(plane) for plane in state_dataset[data_idx[0]]])

            # must be cast to a tuple so that it is interpreted as (x,y) not [(x,:), (y,:)]
            action_xy = tuple(action_dataset[data_idx[0]])
            action = transform(one_hot_action(action_xy, game_size))
            Xbatch[batch_idx] = state
            Ybatch[batch_idx] = action.flatten()
            batch_idx += 1
            if batch_idx == batch_size:
                batch_idx = 0
                yield (Xbatch, Ybatch)


def confirm(prompt=None, resp=False):
    """prompts for yes or no response from the user. Returns True for yes and
       False for no.
       'resp' should be set to the default value assumed by the caller when
       user simply types ENTER.
       created by:
       http://code.activestate.com/recipes/541096-prompt-the-user-for-confirmation/
    """

    if prompt is None:
        prompt = 'Confirm'

    if resp:
        prompt = '%s [%s]|%s: ' % (prompt, 'y', 'n')
    else:
        prompt = '%s [%s]|%s: ' % (prompt, 'n', 'y')

    while True:
        ans = raw_input(prompt)
        if not ans:
            return resp
        if ans not in ['y', 'Y', 'n', 'N']:
            print 'please enter y or n.'
            continue
        if ans == 'y' or ans == 'Y':
            return True
        if ans == 'n' or ans == 'N':
            return False


class LrDecayCallback(Callback):
    """Set learning rate every batch according to:
       initial_learning_rate * (1. / (1. + self.decay * curent_batch))
    """

    def __init__(self, learning_rate, decay):
        super(Callback, self).__init__()
        self.learning_rate = learning_rate
        self.decay = decay

    def set_lr(self):
        # calculate learning rate
        batch = self.model.optimizer.current_batch
        new_lr = self.learning_rate * (1. / (1. + self.decay * batch))

        # set new learning rate
        self.model.optimizer.lr = K.variable(value=new_lr)

    def on_train_begin(self, logs={}):
        # set initial learning rate
        self.set_lr()

    def on_batch_begin(self, batch, logs={}):
        # using batch is not usefull as it starts at 0 every epoch

        # set new learning rate
        self.set_lr()

        # increment current_batch
        # increment current_batch in LrDecayCallback because order of activation
        # can differ and incorrect current_batch would be used
        self.model.optimizer.current_batch += 1


class LrStepDecayCallback(Callback):
    """Set learning rate every decay_every batches according to:
       initial_learning_rate * (decay ^ (current_batch / decay every))
    """

    def __init__(self, learning_rate, decay_every, decay, verbose):
        super(Callback, self).__init__()
        self.learning_rate = learning_rate
        self.decay_every = decay_every
        self.verbose = verbose
        self.decay = decay

    def set_lr(self):
        # calculate learning rate
        n_decay = int(self.model.optimizer.current_batch / self.decay_every)
        new_lr = self.learning_rate * (self.decay ** n_decay)

        # set new learning rate
        self.model.optimizer.lr = K.variable(value=new_lr)

        # print new learning rate if verbose
        if self.verbose:
            print("Batch: " + str(self.model.optimizer.current_batch) +
                  " New learning rate: " + str(new_lr))

    def on_train_begin(self, logs={}):
        # set initial learning rate
        self.set_lr()

    def on_batch_begin(self, batch, logs={}):
        # using batch is not usefull as it starts at 0 every epoch

        # check if learning rate has to change
        # - if we reach a new decay_every batch
        if self.model.optimizer.current_batch % self.decay_every == 0:
            # change learning rate
            self.set_lr()

        # increment current_batch
        # increment current_batch in LrSchedulerCallback because order of activation
        # can differ and incorrect current_batch would be used
        self.model.optimizer.current_batch += 1


class MetadataWriterCallback(Callback):
    """Set current batch at training start
       Save metadata and Model after every epoch
    """

    def __init__(self, path, root):
        super(Callback, self).__init__()
        self.file = path
        self.root = root
        self.metadata = {
            "epoch_logs": [],
            "current_batch": 0,
            "current_epoch": 0,
            "best_epoch": 0
        }

    def on_train_begin(self, logs={}):
        # set current_batch from metadata
        self.model.optimizer.current_batch = self.metadata['current_batch']

    def on_epoch_end(self, epoch, logs={}):
        # in case appending to logs (resuming training), get epoch number ourselves
        epoch = len(self.metadata["epoch_logs"])

        # append log to metadata
        self.metadata["epoch_logs"].append(logs)
        # save current_batch to metadata
        self.metadata["current_batch"] = self.model.optimizer.current_batch
        # save current epoch
        self.metadata["current_epoch"] = epoch

        if "val_loss" in logs:
            key = "val_loss"
        else:
            key = "loss"

        best_loss = self.metadata["epoch_logs"][self.metadata["best_epoch"]][key]
        if logs.get(key) < best_loss:
            self.metadata["best_epoch"] = epoch

        # save meta to file
        with open(self.file, "w") as f:
            json.dump(self.metadata, f, indent=2)

        # save model to file with correct epoch
        save_file = os.path.join(self.root, "weights.{epoch:05d}.hdf5".format(epoch=epoch))
        self.model.save(save_file)


def validate_feature_planes(verbose, dataset, model_features):
    """Verify that dataset's features match the model's expected features.
    """

    if 'features' in dataset:
        dataset_features = dataset['features'][()]
        dataset_features = dataset_features.split(",")
        if len(dataset_features) != len(model_features) or \
           any(df != mf for (df, mf) in zip(dataset_features, model_features)):
            raise ValueError("Model JSON file expects features \n\t%s\n"
                             "But dataset contains \n\t%s" % ("\n\t".join(model_features),
                                                              "\n\t".join(dataset_features)))
        elif verbose:
            print("Verified that dataset features and model features exactly match.")
    else:
        # Cannot check each feature, but can check number of planes.
        n_dataset_planes = dataset["states"].shape[1]
        tmp_preprocess = Preprocess(model_features)
        n_model_planes = tmp_preprocess.output_dim
        if n_dataset_planes != n_model_planes:
            raise ValueError("Model JSON file expects a total of %d planes from features \n\t%s\n"
                             "But dataset contains %d planes" % (n_model_planes,
                                                                 "\n\t".join(model_features),
                                                                 n_dataset_planes))
        elif verbose:
            print("Verified agreement of number of model and dataset feature planes, but cannot "
                  "verify exact match using old dataset format.")


def load_indices_from_file(shuffle_file):
    # load indices from shuffle_file
    with open(shuffle_file, "r") as f:
        indices = np.load(f)

    return indices


def save_indices_to_file(shuffle_file, indices):
    # save indices to shuffle_file
    with open(shuffle_file, "w") as f:
        np.save(f, indices)


def remove_unused_symmetries(indices, symmetries):
    # remove all rows with a symmetry not in symmetries
    remove = []

    # find all rows with incorrect symmetries
    for row in range(len(indices)):
        if not indices[row][1] in symmetries:
            remove.append(row)

    # remove rows and return new array
    return np.delete(indices, remove, 0)


def create_and_save_shuffle_indices(train_val_test, max_validation,
                                    n_total_data_size, shuffle_file_train,
                                    shuffle_file_val, shuffle_file_test):
    """ create an array with all unique state and symmetry pairs,
        calculate test/validation/training set sizes,
        seperate those sets and save them to seperate files.
    """

    symmetries = TRANSFORMATION_INDICES.values()

    # Create an array with a unique row for each combination of a training example
    # and a symmetry.
    # shuffle_indices[i][0] is an index into training examples,
    # shuffle_indices[i][1] is the index (from 0 to 7) of the symmetry transformation to apply
    shuffle_indices = np.empty(shape=[n_total_data_size * len(symmetries), 2], dtype=int)
    for dataset_idx in range(n_total_data_size):
        for symmetry_idx in range(len(symmetries)):
            shuffle_indices[dataset_idx * len(symmetries) + symmetry_idx][0] = dataset_idx
            shuffle_indices[dataset_idx * len(symmetries) +
                            symmetry_idx][1] = symmetries[symmetry_idx]

    # shuffle rows without affecting x,y pairs
    np.random.shuffle(shuffle_indices)

    # validation set size
    n_val_data = int(train_val_test[1] * len(shuffle_indices))
    # limit validation set to --max-validation
    if n_val_data > max_validation:
        n_val_data = max_validation

    # test set size
    n_test_data = int(train_val_test[2] * len(shuffle_indices))

    # train set size
    n_train_data = len(shuffle_indices) - n_val_data - n_test_data

    # create training set and save to file shuffle_file_train
    train_indices = shuffle_indices[0:n_train_data]
    save_indices_to_file(shuffle_file_train, train_indices)

    # create validation set and save to file shuffle_file_val
    val_indices = shuffle_indices[n_train_data:n_train_data + n_val_data]
    save_indices_to_file(shuffle_file_val, val_indices)

    # create test set and save to file shuffle_file_test
    test_indices = shuffle_indices[n_train_data + n_val_data:
                                   n_train_data + n_val_data + n_test_data]
    save_indices_to_file(shuffle_file_test, test_indices)


def load_train_val_test_indices(verbose, arg_symmetries, dataset_length, batch_size, directory):
    """Load indices from .npz files
       Remove unwanted symmerties
       Make Train set dividable by batch_size
       Return train/val/test set
    """
    # shuffle file locations for train/validation/test set
    shuffle_file_train = os.path.join(directory, "shuffle_train.npz")
    shuffle_file_val = os.path.join(directory, "shuffle_validate.npz")
    shuffle_file_test = os.path.join(directory, "shuffle_test.npz")

    # load from .npz files
    train_indices = load_indices_from_file(shuffle_file_train)
    val_indices = load_indices_from_file(shuffle_file_val)
    test_indices = load_indices_from_file(shuffle_file_test)

    # used symmetries
    if arg_symmetries == "all":
        # add all symmetries
        symmetries = TRANSFORMATION_INDICES.values()
    elif arg_symmetries == "none":
        # only add standart orientation
        symmetries = [TRANSFORMATION_INDICES["noop"]]
    else:
        # add specified symmetries
        symmetries = [TRANSFORMATION_INDICES[name] for name in arg_symmetries.strip().split(",")]

    if verbose:
        print("Used symmetries: " + arg_symmetries)

    # remove symmetries not used during current run
    if len(symmetries) != len(TRANSFORMATION_INDICES):
        train_indices = remove_unused_symmetries(train_indices, symmetries)
        test_indices = remove_unused_symmetries(test_indices, symmetries)
        val_indices = remove_unused_symmetries(val_indices, symmetries)

    # Need to make sure training data is dividable by minibatch size or get
    # warning mentioning accuracy from keras
    if len(train_indices) % batch_size != 0:
        # remove first len(train_indices) % args.minibatch rows
        train_indices = np.delete(train_indices, [row for row in range(len(train_indices)
                                                  % batch_size)], 0)

    if verbose:
        print("dataset loaded")
        print("\t%d total positions" % dataset_length)
        print("\t%d total samples" % (dataset_length * len(symmetries)))
        print("\t%d total samples check" % (len(train_indices) +
              len(val_indices) + len(test_indices)))
        print("\t%d training samples" % len(train_indices))
        print("\t%d validation samples" % len(val_indices))
        print("\t%d test samples" % len(test_indices))

    return train_indices, val_indices, test_indices


def set_training_settings(resume, args, metadata, dataset_length):
    """ save all args to metadata,
        check if critical settings have been changed and prompt user about it.
        create new shuffle files if needed.
    """

    # shuffle file locations for train/validation/test set
    shuffle_file_train = os.path.join(args.out_directory, "shuffle_train.npz")
    shuffle_file_val = os.path.join(args.out_directory, "shuffle_validate.npz")
    shuffle_file_test = os.path.join(args.out_directory, "shuffle_test.npz")

    # determine if new shuffle files have to be created
    save_new_shuffle_indices = not resume

    if resume:
        # check if argument model and meta model are the same
        if metadata["model_file"] != args.model:
            # verify if user really wants to use new model file
            # TODO better explanation why this might be bad
            print("the model file is different from the model file used last run: " +
                  metadata["model_file"] + ". It might be different than the old one.")
            if args.override or not confirm("Are you sure you want to use the new model?", False):  # noqa: E501
                raise ValueError("User abort after mismatch model files.")

        # check if decay_every is the same
        # TODO better explanation why this might be bad
        if args.decay_every is not None and metadata["decay_every"] != args.decay_every:
            print("Setting a new --decay-every might result in a different learning rate, restarting training might be advisable.")  # noqa: E501
            if args.override or confirm("Are you sure you want to use new decay every setting?", False):  # noqa: E501
                metadata["decay_every"] = args.decay_every

        # check if learning_rate is the same
        # TODO better explanation why this might be bad
        if args.learning_rate is not None and metadata["learning_rate"] != args.learning_rate:
            print("Setting a new --learning-rate might result in a different learning rate, restarting training might be advisable.")  # noqa: E501
            if args.override or confirm("Are you sure you want to use new learning rate setting?", False):  # noqa: E501
                metadata["learning_rate"] = args.learning_rate

        # check if decay is the same
        # TODO better explanation why this might be bad
        if args.decay is not None and metadata["decay"] != args.decay:
            print("Setting a new --decay might result in a different learning rate, restarting training might be advisable.")  # noqa: E501
            if args.override or confirm("Are you sure you want to use new decay setting?", False):  # noqa: E501
                metadata["decay"] = args.decay

        # check if batch_size is the same
        # TODO better explanation why this might be bad
        if args.minibatch is not None and metadata["batch_size"] != args.minibatch:
            print("current_batch will be recalculated, restarting training might be advisable.")
            if args.override or confirm("Are you sure you want to use new minibatch setting?", False):  # noqa: E501
                metadata["current_batch"] = int((metadata["current_batch"] *
                                                 metadata["batch_size"]) / args.minibatch)
                metadata["batch_size"] = args.minibatch

        # check if max_validation is the same
        # TODO better explanation why this might be bad
        if args.max_validation is not None and metadata["max_validation"] != args.max_validation:
            print("Training set and validation set should be stricktly separated, setting a new fraction will generate a new validation set that might include data from the current traing set.")  # noqa: E501
            print("We reccommend you not to use the new max-validation setting.")
            if args.override or confirm("Are you sure you want to use new max-validation setting?", False):  # noqa: E501
                metadata["max_validation"] = args.max_validation
                # new shuffle files have to be created
                save_new_shuffle_indices = True

        # check if train_val_test is the same
        # TODO better explanation why this might be bad
        if args.train_val_test is not None and metadata["train_val_test"] != args.train_val_test:
            print("Training set and validation set should be stricktly separated, setting a new fraction will generate a new validation set that might include data from the current traing set.")  # noqa: E501
            print("We reccommend you not to use the new fraction.")
            if args.override or confirm("Are you sure you want to use new train-val-test fraction setting?", False):  # noqa: E501
                metadata["train_val_test"] = args.train_val_test
                # new shuffle files have to be created
                save_new_shuffle_indices = True

        # check if epochs is the same
        if args.epochs is not None and metadata["epochs"] != args.epochs:
            metadata["epochs"] = args.epochs

        # check if epoch_length is the same
        if args.epoch_length is not None and metadata["epoch_length"] != args.epoch_length:
            metadata["epoch_length"] = args.epoch_length

        # check if shuffle files exist and data file is the same
        if not os.path.exists(shuffle_file_train) or not os.path.exists(shuffle_file_val) or \
           not os.path.exists(shuffle_file_test) or \
           metadata["training_data"] != args.train_data or \
           metadata["available_states"] != dataset_length:
            # shuffle files do not exist or training data file has changed
            # TODO better explanation why this might be bad
            print("WARNING! shuffle files have to be recreated.")
            save_new_shuffle_indices = True
    else:
        # save all argument or default settings to metadata

        # save used model file to metadata
        metadata["model_file"] = args.model

        # save decay_every to metadata
        metadata["decay_every"] = args.decay_every

        # save learning_rate to metadata
        if args.learning_rate is not None:
            metadata["learning_rate"] = args.learning_rate
        else:
            metadata["learning_rate"] = DEFAULT_LEARNING_RATE

        # save decay to metadata
        if args.decay is not None:
            metadata["decay"] = args.decay
        else:
            metadata["decay"] = DEFAULT_DECAY

        # save batch_size to metadata
        if args.minibatch is not None:
            metadata["batch_size"] = args.minibatch
        else:
            metadata["batch_size"] = DEFAULT_BATCH_SIZE

        # save max_validation to metadata
        if args.max_validation is not None:
            metadata["max_validation"] = args.max_validation
        else:
            metadata["max_validation"] = DEFAULT_MAX_VALIDATION

        # save train_val_test to metadata
        if args.train_val_test is not None:
            metadata["train_val_test"] = args.train_val_test
        else:
            metadata["train_val_test"] = DEFAULT_TRAIN_VAL_TEST

        # save epochs to metadata
        if args.epochs is not None:
            metadata["epochs"] = args.epochs
        else:
            metadata["epochs"] = DEFAULT_EPOCH

        # save epoch_length to metadata
        if args.epoch_length is not None:
            metadata["epoch_length"] = args.epoch_length
        else:
            metadata["epoch_length"] = dataset_length

    # Record all command line args in a list so that all args are recorded even
    # when training is stopped and resumed.
    meta_args_data = metadata.get("cmd_line_args", [])
    meta_args_data.append(vars(args))
    metadata["cmd_line_args"] = meta_args_data

    # create and save new shuffle indices if needed
    if save_new_shuffle_indices:
        # create and save new shuffle indices to file
        create_and_save_shuffle_indices(
                metadata["train_val_test"], metadata["max_validation"], dataset_length,
                shuffle_file_train, shuffle_file_val, shuffle_file_test)

        # save total amount of states to metadata
        metadata["available_states"] = dataset_length

        # save training data file name to metadata
        metadata["training_data"] = args.train_data

        if args.verbose:
            print("created new data shuffling indices")


def run_training(cmd_line_args=None):
    """Run training. command-line args may be passed in as a list
    """
    import argparse
    parser = argparse.ArgumentParser(description='Perform supervised training on a policy network.')
    # required args
    parser.add_argument("model", help="Path to a JSON model file (i.e. from CNNPolicy.save_model())")  # noqa: E501
    parser.add_argument("train_data", help="A .h5 file of training data")
    parser.add_argument("out_directory", help="directory where metadata and weights will be saved")
    # frequently used args
    parser.add_argument("--minibatch", "-B", help="Size of training data minibatches. Default: " + str(DEFAULT_BATCH_SIZE), type=int, default=None)  # noqa: E501
    parser.add_argument("--epochs", "-E", help="Total number of iterations on the data. Default: " + str(DEFAULT_EPOCH), type=int, default=None)  # noqa: E501
    parser.add_argument("--epoch-length", "-l", help="Number of training examples considered 'one epoch'. Default: # training data", type=int, default=None)  # noqa: E501
    parser.add_argument("--learning-rate", "-r", help="Learning rate - how quickly the model learns at first. Default: " + str(DEFAULT_LEARNING_RATE), type=float, default=None)  # noqa: E501
    parser.add_argument("--decay", "-d", help="The rate at which learning decreases. Default: " + str(DEFAULT_DECAY), type=float, default=None)  # noqa: E501
    # TODO better explanation
    parser.add_argument("--decay-every", "-de", help="Use step-decay: decay --learning-rate with --decay every --decay-every batches. Default: None", type=int, default=None)  # noqa: E501
    parser.add_argument("--verbose", "-v", help="Turn on verbose mode", default=False, action="store_true")  # noqa: E501
    parser.add_argument("--override", help="Turn on prompt override mode", default=False, action="store_true")  # noqa: E501
    # slightly fancier args
    parser.add_argument("--weights", help="Name of a .h5 weights file (in the output directory) to load to resume training", default=None)  # noqa: E501
    parser.add_argument("--train-val-test", help="Fraction of data to use for training/val/test. Must sum to 1. Default: " + str(DEFAULT_TRAIN_VAL_TEST), nargs=3, type=float, default=None)  # noqa: E501
    parser.add_argument("--max-validation", help="maximum validation set size. default: " + str(DEFAULT_MAX_VALIDATION), type=int, default=None)  # noqa: E501
    parser.add_argument("--symmetries", help="none, all or comma-separated list of transforms, subset of: noop,rot90,rot180,rot270,fliplr,flipud,diag1,diag2. Default: all", default='all')  # noqa: E501

    # show help or parse arguments
    if cmd_line_args is None:
        args = parser.parse_args()
    else:
        args = parser.parse_args(cmd_line_args)

    # set resume
    resume = args.weights is not None

    if args.verbose:
        if resume:
            print("trying to resume from %s with weights %s" %
                  (args.out_directory, os.path.join(args.out_directory, args.weights)))
        else:
            if os.path.exists(args.out_directory):
                print("directory %s exists. any previous data will be overwritten" %
                      args.out_directory)
            else:
                print("starting fresh output directory %s" % args.out_directory)

    # load model from json spec
    policy = CNNPolicy.load_model(args.model)
    model_features = policy.preprocessor.feature_list
    model = policy.model
    # load weights
    if resume:
        model.load_weights(os.path.join(args.out_directory, args.weights))

    # features of training data
    dataset = h5.File(args.train_data)

    # Verify that dataset's features match the model's expected features.
    validate_feature_planes(args.verbose, dataset, model_features)

    # ensure output directory is available
    if not os.path.exists(args.out_directory):
        os.makedirs(args.out_directory)

    # create metadata file and the callback object that will write to it
    # and saves model  at the same time
    # the MetadataWriterCallback only sets 'epoch', 'best_epoch' and 'current_batch'.
    # We can add in anything else we like here
    meta_file = os.path.join(args.out_directory, "metadata.json")
    meta_writer = MetadataWriterCallback(meta_file, args.out_directory)

    # load prior data if it already exists
    if os.path.exists(meta_file) and resume:
        with open(meta_file, "r") as f:
            meta_writer.metadata = json.load(f)

        if args.verbose:
            print("previous metadata loaded: %d epochs. new epochs will be appended." %
                  len(meta_writer.metadata["epoch_logs"]))
    elif args.verbose:
        print("starting with empty metadata")

    # set all settings: default, from args or from metadata
    # generate new shuffle files if needed
    set_training_settings(resume, args, meta_writer.metadata, len(dataset["states"]))

    # get train/validation/test indices
    train_indices, val_indices, test_indices \
        = load_train_val_test_indices(args.verbose, args.symmetries, len(dataset["states"]),
                                      meta_writer.metadata["batch_size"], args.out_directory)

    # create dataset generators
    train_data_generator = shuffled_hdf5_batch_generator(
        dataset["states"],
        dataset["actions"],
        train_indices,
        meta_writer.metadata["batch_size"])
    val_data_generator = shuffled_hdf5_batch_generator(
        dataset["states"],
        dataset["actions"],
        val_indices,
        meta_writer.metadata["batch_size"])

    # check if step decay has to be applied
    if meta_writer.metadata["decay_every"] is None:
        # use normal decay without momentum
        lr_scheduler_callback = LrDecayCallback(meta_writer.metadata["learning_rate"],
                                                meta_writer.metadata["decay"])
    else:
        # use step decay
        lr_scheduler_callback = LrStepDecayCallback(meta_writer.metadata["learning_rate"],
                                                    meta_writer.metadata["decay_every"],
                                                    meta_writer.metadata["decay"], args.verbose)

    sgd = SGD(lr=meta_writer.metadata["learning_rate"])
    model.compile(loss='categorical_crossentropy', optimizer=sgd, metrics=["accuracy"])

    if args.verbose:
        print("STARTING TRAINING")

    model.fit_generator(
        generator=train_data_generator,
        samples_per_epoch=meta_writer.metadata["epoch_length"],
        nb_epoch=meta_writer.metadata["epochs"],
        callbacks=[meta_writer, lr_scheduler_callback],
        validation_data=val_data_generator,
        nb_val_samples=len(val_indices))


if __name__ == '__main__':
    run_training()